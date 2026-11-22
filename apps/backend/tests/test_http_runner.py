"""The HTTP node's request: statuses, limits, timeout, redirects and the guard against SSRF."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest

from openartifact.engine import http_runner
from openartifact.engine.http_runner import (
    IPAddress,
    address_problem,
    parse_headers,
    run_http,
)
from openartifact.engine.results import NodeResult


class _Handler(BaseHTTPRequestHandler):
    hits: ClassVar[list[tuple[str, str, dict[str, str], bytes]]] = []

    def _answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        _Handler.hits.append((self.command, self.path, dict(self.headers.items()), body))
        if self.path in ("/redirect", "/to-meta"):
            self.send_response(302)
            self.send_header(
                "Location", "/landed" if self.path == "/redirect" else "http://169.254.169.254/"
            )
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/slow":
            time.sleep(3)
        payload = {
            "/big": b"y" * 5000,
            "/echo": body,
        }.get(self.path, b"hello")
        code = {"/missing": 404, "/boom": 500, "/created": 201}.get(self.path, 200)
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _answer  # noqa: N815

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def server() -> Iterator[int]:
    _Handler.hits = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.block_on_close = False  # a handler still sleeping (/slow) must not delay the teardown
    threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


async def _call(
    url: str,
    *,
    allow: bool = True,
    limit: int = 1024 * 1024,
    secrets: dict[str, str] | None = None,
    **config: Any,
) -> NodeResult:
    return await run_http(
        {"url": url, **config},
        response_limit_bytes=limit,
        allow_private_networks=allow,
        secrets=secrets,
    )


async def test_a_2xx_response_passes_and_gives_status_and_body(server: int) -> None:
    result = await _call(f"http://127.0.0.1:{server}/ok")
    assert (result.outcome, result.output) == ("pass", "hello")
    assert result.data == {"status": 200, "content_type": "text/plain", "truncated": False}


@pytest.mark.parametrize(
    ("path", "spec", "outcome"),
    [
        ("/missing", "200-299", "fail"),
        ("/boom", "200-299", "fail"),
        ("/missing", "200-299, 404", "pass"),
        ("/created", "200", "fail"),
        ("/created", "200, 201", "pass"),
        ("/boom", "500-599", "pass"),
    ],
)
async def test_the_status_decides_by_the_accepted_codes_and_ranges(
    server: int, path: str, spec: str, outcome: str
) -> None:
    result = await _call(f"http://127.0.0.1:{server}{path}", success_status=spec)
    assert result.outcome == outcome
    if outcome == "fail":
        assert result.reason and "not an accepted status" in result.reason


async def test_method_headers_and_body_are_sent(server: int) -> None:
    result = await _call(
        f"http://127.0.0.1:{server}/echo",
        method="POST",
        headers="X-One: 1\n\nX-Two:  two ",
        body='{"a": 1}\nline2',
    )
    assert result.output == '{"a": 1}\nline2'
    method, _, headers, _ = _Handler.hits[-1]
    assert method == "POST"
    assert headers["X-One"] == "1"
    assert headers["X-Two"] == "two"


async def test_a_redirect_is_not_followed(server: int) -> None:
    result = await _call(f"http://127.0.0.1:{server}/redirect")
    assert result.outcome == "fail"
    assert result.data and result.data["status"] == 302
    assert [h[1] for h in _Handler.hits] == ["/redirect"]


async def test_a_redirect_is_not_followed_even_when_accepted(server: int) -> None:
    result = await _call(f"http://127.0.0.1:{server}/redirect", success_status="302")
    assert result.outcome == "pass"
    assert [h[1] for h in _Handler.hits] == ["/redirect"]


async def test_the_body_is_cut_at_the_limit(server: int) -> None:
    result = await _call(f"http://127.0.0.1:{server}/big", limit=100)
    assert result.outcome == "pass"
    assert result.output.startswith("y" * 100)
    assert result.output.endswith("[response truncated]")
    assert result.data and result.data["truncated"] is True


async def test_a_slow_response_times_out(server: int) -> None:
    result = await _call(f"http://127.0.0.1:{server}/slow", timeout_seconds=1)
    assert (result.outcome, result.reason) == ("fail", "Timeout after 1 s")


async def test_a_refused_connection_fails_with_a_reason_without_the_url() -> None:
    result = await _call("http://127.0.0.1:1/secret-path?token=abc")
    assert result.outcome == "fail"
    assert "abc" not in (result.reason or "")


@pytest.mark.parametrize(
    "url",
    ["", "ftp://example.org/", "file:///etc/passwd", "http:///nohost", "http://user:pw@x.org/"],
)
async def test_an_unusable_url_fails_with_a_reason(url: str) -> None:
    result = await _call(url)
    assert result.outcome == "fail"
    assert "pw" not in (result.reason or "")


@pytest.mark.parametrize(
    "config",
    [{"headers": "no colon"}, {"headers": "Host: x"}, {"success_status": "ok"}],
)
async def test_bad_headers_and_status_specs_fail(server: int, config: dict[str, str]) -> None:
    result = await _call(f"http://127.0.0.1:{server}/", **config)  # type: ignore[arg-type]
    assert result.outcome == "fail"
    assert _Handler.hits == []


def test_headers_are_parsed_one_per_line() -> None:
    assert parse_headers("A: 1\n\nB:x:y") == {"A": "1", "B": "x:y"}


# ── SSRF ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "[::1]",
        "10.1.2.3",
        "192.168.0.10",
        "172.16.5.5",
        "169.254.169.254",
        "[fd00:ec2::254]",
        "[::ffff:127.0.0.1]",
        "[::ffff:169.254.169.254]",
        "0.0.0.0",
        "100.64.0.1",
        "224.0.0.1",
        "2130706433",
        "0x7f.1",
        "0177.0.0.1",
    ],
)
async def test_private_loopback_and_metadata_addresses_are_refused(server: int, host: str) -> None:
    result = await _call(f"http://{host}:{server}/", allow=False)
    assert result.outcome == "fail"
    assert _Handler.hits == []
    assert result.reason and (
        "not allowed" in result.reason or "could not be resolved" in result.reason
    )


async def test_a_name_that_resolves_to_loopback_is_refused(
    monkeypatch: pytest.MonkeyPatch, server: int
) -> None:
    async def resolve(host: str, port: int) -> list[IPAddress]:
        return [ipaddress.ip_address("127.0.0.1")]

    monkeypatch.setattr(http_runner, "_resolve", resolve)
    result = await _call(f"http://internal.example:{server}/", allow=False)
    assert (result.outcome, result.reason) == (
        "fail",
        "The address is not allowed (private network address)",
    )
    assert _Handler.hits == []


async def test_one_internal_address_among_public_ones_refuses_the_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def resolve(host: str, port: int) -> list[IPAddress]:
        return [ipaddress.ip_address("93.184.216.34"), ipaddress.ip_address("10.0.0.1")]

    monkeypatch.setattr(http_runner, "_resolve", resolve)
    result = await _call("http://mixed.example/", allow=False)
    assert result.outcome == "fail"
    assert "not allowed" in (result.reason or "")


async def test_the_request_goes_to_the_checked_address_with_the_original_host(
    monkeypatch: pytest.MonkeyPatch, server: int
) -> None:
    calls: list[str] = []

    async def resolve(host: str, port: int) -> list[IPAddress]:
        calls.append(host)
        return [ipaddress.ip_address("127.0.0.1")]

    monkeypatch.setattr(http_runner, "_resolve", resolve)
    result = await _call(f"http://service.example:{server}/ok")
    assert result.outcome == "pass"
    assert calls == ["service.example"]  # resolved once: connecting did not resolve again
    assert _Handler.hits[-1][2]["Host"] == f"service.example:{server}"


async def test_the_flag_allows_private_networks_but_never_metadata_addresses(server: int) -> None:
    assert (await _call(f"http://127.0.0.1:{server}/", allow=True)).outcome == "pass"
    result = await _call("http://169.254.169.254/latest/meta-data/", allow=True)
    assert (result.outcome, result.reason) == (
        "fail",
        "The address is not allowed (cloud metadata address)",
    )
    assert (await _call("http://0.0.0.0/", allow=True)).outcome == "fail"


def test_address_rules() -> None:
    ip = ipaddress.ip_address
    assert address_problem(ip("93.184.216.34"), False) is None
    assert address_problem(ip("2606:2800:220:1:248:1893:25c8:1946"), False) is None
    assert address_problem(ip("::1"), False)
    assert address_problem(ip("fe80::1"), False)
    assert address_problem(ip("64:ff9b::7f00:1"), False)  # NAT64 of 127.0.0.1
    assert address_problem(ip("10.0.0.1"), True) is None


@pytest.mark.parametrize(
    ("address", "problem"),
    [
        ("::ffff:169.254.169.254", "cloud metadata address"),
        ("64:ff9b::a9fe:a9fe", "cloud metadata address"),
        ("::ffff:0.0.0.0", "unspecified or multicast address"),
        ("::ffff:224.0.0.1", "unspecified or multicast address"),
        ("64:ff9b::e000:1", "unspecified or multicast address"),
    ],
)
def test_mapped_and_nat64_forms_are_judged_by_their_ipv4_address_even_when_private_is_allowed(
    address: str, problem: str
) -> None:
    assert address_problem(ipaddress.ip_address(address), True) == problem


@pytest.mark.parametrize(
    "host", ["[::ffff:169.254.169.254]", "[64:ff9b::a9fe:a9fe]", "[::ffff:0.0.0.0]"]
)
async def test_a_mapped_metadata_or_unspecified_host_is_refused_end_to_end_with_private_allowed(
    server: int, host: str
) -> None:
    result = await _call(f"http://{host}:{server}/", allow=True)
    assert result.outcome == "fail"
    assert result.reason in (
        "The address is not allowed (cloud metadata address)",
        "The address is not allowed (unspecified or multicast address)",
    )
    assert _Handler.hits == []


async def test_a_redirect_to_the_metadata_address_is_not_followed_and_not_called(
    server: int,
) -> None:
    result = await _call(f"http://127.0.0.1:{server}/to-meta", allow=True)
    assert (result.outcome, result.data and result.data["status"]) == ("fail", 302)
    assert [h[1] for h in _Handler.hits] == ["/to-meta"]  # the Location was never requested


@pytest.mark.parametrize("answer", [socket.gaierror("no such host"), []], ids=["error", "empty"])
async def test_a_failing_or_empty_resolution_refuses_the_host_without_a_connection(
    monkeypatch: pytest.MonkeyPatch, server: int, answer: Exception | list[Any]
) -> None:
    asked: list[str] = []

    async def getaddrinfo(host: str, port: int, **kwargs: Any) -> list[Any]:
        asked.append(host)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", getaddrinfo)
    result = await _call(f"http://gone.example:{server}/")
    assert (result.outcome, result.reason) == ("fail", "The host name could not be resolved")
    assert asked == ["gone.example"]
    assert _Handler.hits == []


async def test_duplicate_addresses_are_listed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    async def getaddrinfo(host: str, port: int, **kwargs: Any) -> list[Any]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fe80::1%eth0", port, 0, 2)),
        ]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", getaddrinfo)
    assert await http_runner._resolve("x.example", 80) == [
        ipaddress.ip_address("93.184.216.34"),
        ipaddress.ip_address("fe80::1"),
    ]


@pytest.mark.parametrize("value", ["a\x01b", "a\x7fb", "a\x00b"])
def test_a_control_character_in_a_header_value_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match="control character"):
        parse_headers(f"X-Test: {value}")


async def test_a_header_injection_through_a_secret_value_never_reaches_the_server(
    server: int,
) -> None:
    result = await _call(
        f"http://127.0.0.1:{server}/",
        headers="X-Token: ${secret:T}",
        secrets={"T": "abc\r\nX-Evil: 1"},
    )
    assert result.outcome == "fail"
    assert result.reason == "The header 'X-Token' has a control character"
    assert _Handler.hits == []


async def test_a_dropped_connection_fails_with_the_error_type() -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def hang_up() -> None:
        connection, _ = listener.accept()
        connection.recv(4096)
        connection.close()

    thread = threading.Thread(target=hang_up, daemon=True)
    thread.start()
    try:
        result = await _call(f"http://127.0.0.1:{port}/")
    finally:
        thread.join(5)
        listener.close()
    assert (result.outcome, result.reason) == ("fail", "The request failed (RemoteProtocolError)")
    assert result.duration is not None and result.duration > 0
