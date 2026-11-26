"""Runs an HTTP node: one request, no redirects, bounded in time and size, and guarded against SSRF.

Before any connection the host name is resolved here and every address is checked; the request is
then sent to the checked address itself (the URL's host becomes the IP, the ``Host`` header and the
TLS server name stay the original), so the name cannot resolve to something else between the check
and the connection (DNS rebinding). Loopback, private, link-local, carrier-grade NAT and other
non-public addresses are refused unless ``http_allow_private_networks`` is on; unspecified,
multicast and cloud metadata addresses are refused always. Redirects are never followed (a 3xx
status is simply a status), proxies from the environment are ignored, and the response body is
read only up to a limit, uncompressed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from openartifact.credentials.refs import SecretReferenceError, check_url_references
from openartifact.engine.context import ContextError, RunView, check_url_placement
from openartifact.engine.results import NodeResult, failed
from openartifact.graph.node_types import SettingError, parse_status_spec

TRUNCATED_MARK = "[response truncated]"
MAX_ADDRESSES = 4
#: Addresses that hand out the credentials of a cloud host; never reachable, whatever the settings.
METADATA_ADDRESSES = frozenset(
    ipaddress.ip_address(a)
    for a in ("169.254.169.254", "169.254.170.2", "100.100.100.200", "fd00:ec2::254")
)
_TOKEN = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class AddressRefusedError(Exception):
    """The address of the host is not one an HTTP node may call."""


def address_problem(address: IPAddress, allow_private: bool) -> str | None:
    """Why ``address`` may not be called (``None``: it may)."""
    if isinstance(address, ipaddress.IPv6Address):
        # ::ffff:10.0.0.1 and the NAT64 form carry an IPv4 address: judge that one
        mapped = address.ipv4_mapped
        if mapped is not None:
            address = mapped
        elif address in ipaddress.ip_network("64:ff9b::/96"):
            address = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    if address in METADATA_ADDRESSES:
        return "cloud metadata address"
    if address.is_unspecified or address.is_multicast:
        return "unspecified or multicast address"
    if not allow_private and not address.is_global:
        return "private network address"
    return None


async def _resolve(host: str, port: int) -> list[IPAddress]:
    """The addresses a name resolves to (numeric forms such as ``0x7f.1`` come out as the IP)."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    found: list[IPAddress] = []
    for info in infos:
        address = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
        if address not in found:
            found.append(address)
    return found


async def vetted_addresses(host: str, port: int, allow_private: bool) -> list[IPAddress]:
    """The addresses of ``host`` that may be called; raises :class:`AddressRefusedError` if any is not.

    One refused address refuses the host: a name that also points at an internal address is not
    trusted for the others.
    """
    try:
        addresses = await _resolve(host, port)
    except (OSError, ValueError) as error:
        raise AddressRefusedError("The host name could not be resolved") from error
    if not addresses:
        raise AddressRefusedError("The host name could not be resolved")
    for address in addresses:
        problem = address_problem(address, allow_private)
        if problem:
            raise AddressRefusedError(f"The address is not allowed ({problem})")
    return addresses[:MAX_ADDRESSES]


def parse_headers(text: str) -> dict[str, str]:
    """``Name: value`` per line (empty lines are skipped); raises :class:`ValueError`."""
    headers: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        name, colon, value = line.partition(":")
        name = name.strip()
        if not colon or not _TOKEN.fullmatch(name):
            raise ValueError(f"Header line {number} is not 'Name: value'")
        if name.lower() in ("host", "content-length", "transfer-encoding", "connection"):
            raise ValueError(f"The header '{name}' cannot be set")
        if any((ord(c) < 32 and c != "\t") or ord(c) == 127 for c in value):
            raise ValueError(f"Header line {number} has a control character")
        headers[name] = value.strip()
    return headers


def _url_parts(url: str) -> tuple[str, str, int]:
    """(scheme, host, port) of a valid http(s) URL without credentials; raises :class:`ValueError`."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise ValueError("Only http and https addresses are allowed")
    if not parts.hostname:
        raise ValueError("The address has no host")
    if parts.username is not None or parts.password is not None:
        raise ValueError("The address must not contain a user name or password")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return parts.scheme, parts.hostname, port


def _status_ok(status: int, spec: str) -> bool:
    return any(low <= status <= high for low, high in parse_status_spec(spec))


async def _read_capped(response: httpx.Response, limit: int) -> tuple[str, bool]:
    body = bytearray()
    cut = False
    async for chunk in response.aiter_raw():
        room = limit - len(body)
        body += chunk[: max(room, 0)]
        if len(chunk) > room:
            cut = True
            break
    return body.decode("utf-8", errors="replace"), cut


async def run_http(
    config: dict[str, Any],
    *,
    response_limit_bytes: int,
    allow_private_networks: bool,
    secrets: Mapping[str, str] | None = None,
    view: RunView | None = None,
) -> NodeResult:
    """Send the request the node describes; pass when the status is an accepted one.

    ``secrets`` holds the values of the ``${secret:NAME}`` references in the URL, headers and body;
    ``view`` the run context the ``${node...}`` and ``${var...}`` references read. Both are put in
    here, and only here, in one pass (a replaced value is not scanned again): the URL after the
    substitution (percent-encoded values) is the one that is vetted for SSRF, and a reference before
    the path is refused. A reference that cannot be resolved fails the node.
    """
    values = secrets or {}
    view = view or RunView()
    url = str(config.get("url") or "").strip()
    if not url:
        return failed("The URL is empty")
    started = time.monotonic()
    timeout = int(config.get("timeout_seconds") or 30)
    try:
        check_url_references(url)
        check_url_placement(url)
        url = view.render(url, secrets=values, percent_encode=True)
        scheme, host, port = _url_parts(url)
        headers = {
            name: view.render(value, secrets=values)
            for name, value in parse_headers(str(config.get("headers") or "")).items()
        }
        body = view.render(str(config.get("body") or ""), secrets=values)
        for name, value in headers.items():
            if any((ord(c) < 32 and c != "\t") or ord(c) == 127 for c in value):
                raise ValueError(f"The header '{name}' has a control character")
        accepted = str(config.get("success_status") or "200-299")
        parse_status_spec(accepted)
    except (ValueError, SettingError, SecretReferenceError) as error:
        return failed(
            str(error)
            if isinstance(error, SettingError | SecretReferenceError | ContextError)
            else _clean(error)
        )
    try:
        async with asyncio.timeout(timeout):
            addresses = await vetted_addresses(host, port, allow_private_networks)
            return await _send(
                {**config, "body": body}, url, scheme, host, port, headers, accepted, addresses,
                timeout, response_limit_bytes, started,
            )  # fmt: skip
    except AddressRefusedError as error:
        return failed(str(error), duration=time.monotonic() - started)
    except TimeoutError:
        return failed(f"Timeout after {timeout} s", duration=time.monotonic() - started)


def _clean(error: ValueError) -> str:
    """A message of this module's own checks; any other ValueError (a URL parser's) is not echoed."""
    text = str(error)
    own = ("Only http", "The address", "Header line", "The header")
    return text if text.startswith(own) else "The URL is not valid"


class ConnectFailedError(Exception):
    """None of the checked addresses of the host took the connection."""


@dataclass(frozen=True)
class Exchange:
    """A response as far as it was read: status, headers and the body up to the limit."""

    status: int
    headers: httpx.Headers
    text: str
    truncated: bool


async def _exchange(
    method: str,
    url: str,
    scheme: str,
    host: str,
    port: int,
    headers: Mapping[str, str],
    body: bytes | None,
    addresses: list[IPAddress],
    timeout: float,
    limit: int,
) -> Exchange:
    """Send one request to the checked addresses of ``host``, one after the other until one connects.

    The connection goes to the address itself (``Host`` and the TLS server name stay the host's), no
    redirect is followed, no proxy of the environment is used, the body is read up to ``limit``.
    Raises :class:`ConnectFailedError` when no address connects and ``httpx.HTTPError`` for anything
    that goes wrong after that.
    """
    target = httpx.URL(url.strip())
    default_port = 443 if scheme == "https" else 80
    send_headers = {"Accept-Encoding": "identity", **headers}
    send_headers["Host"] = host if port == default_port else f"{host}:{port}"
    last_error = "The connection failed"
    for address in addresses:
        ip_url = target.copy_with(host=str(address))
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                trust_env=False,
                timeout=httpx.Timeout(timeout),
            ) as client:
                request = client.build_request(
                    method,
                    ip_url,
                    headers=send_headers,
                    content=body or None,
                    extensions={"sni_hostname": host} if scheme == "https" else None,
                )
                response = await client.send(request, stream=True)
                try:
                    text, cut = await _read_capped(response, limit)
                finally:
                    await response.aclose()
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            last_error = f"The connection failed ({type(error).__name__})"
            continue
        return Exchange(response.status_code, response.headers, text, cut)
    raise ConnectFailedError(last_error)


async def guarded_exchange(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None,
    *,
    timeout: float,
    limit: int,
    allow_private: bool,
) -> Exchange:
    """One request with every check an HTTP node gets, for the parts of the application that call out
    themselves (the LLM providers): only http(s) without credentials in the address, every address of
    the host vetted (:func:`vetted_addresses`), the connection pinned to a vetted address, no redirect,
    no proxy, a capped body.

    Raises ``ValueError`` (the address is not usable), :class:`AddressRefusedError`,
    :class:`ConnectFailedError` and ``httpx.HTTPError``; the caller bounds the time as a whole.
    """
    scheme, host, port = _url_parts(url)
    addresses = await vetted_addresses(host, port, allow_private)
    return await _exchange(
        method, url, scheme, host, port, headers, body, addresses, timeout, limit
    )


async def _send(
    config: dict[str, Any],
    url: str,
    scheme: str,
    host: str,
    port: int,
    headers: dict[str, str],
    accepted: str,
    addresses: list[IPAddress],
    timeout: int,
    limit: int,
    started: float,
) -> NodeResult:
    method = str(config.get("method") or "GET")
    body = str(config.get("body") or "")
    try:
        got = await _exchange(
            method, url, scheme, host, port, headers, body.encode("utf-8") if body else None,
            addresses, timeout, limit,
        )  # fmt: skip
    except ConnectFailedError as error:
        return failed(str(error), duration=time.monotonic() - started)
    except httpx.HTTPError as error:
        return failed(
            f"The request failed ({type(error).__name__})",
            duration=time.monotonic() - started,
        )
    ok = _status_ok(got.status, accepted)
    return NodeResult(
        "pass" if ok else "fail",
        output=f"{got.text}\n{TRUNCATED_MARK}" if got.truncated else got.text,
        reason=None if ok else f"HTTP {got.status} is not an accepted status ({accepted})",
        data={
            "status": got.status,
            "content_type": got.headers.get("content-type"),
            "truncated": got.truncated,
        },
        duration=time.monotonic() - started,
    )
