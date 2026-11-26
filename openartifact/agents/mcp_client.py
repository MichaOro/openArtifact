"""The MCP Client Tool: the tools of a remote MCP server (Streamable HTTP) for an agent (ADR-040).

:func:`open_mcp` connects to the server for the time of one agent run, lists its tools (filtered by *Tools to
include*) and calls them. Every HTTP request of the MCP SDK goes through :class:`GuardedTransport`: the host is
resolved and every address vetted by the HTTP node's rules (cloud metadata refused always, private networks only
when allowed), the connection is pinned to a vetted address (no DNS rebinding), proxies of the environment are
ignored. The SDK itself follows a redirect only within the endpoint's origin.

The token is sent as ``Authorization: Bearer`` and never appears in a message. A tool's answer is foreign text: it
goes to the model and into the history, and is never interpreted here.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

from openartifact.agents.tool_config import ToolConfigError, check_endpoint, parse_tool_names
from openartifact.engine.http_runner import AddressRefusedError, vetted_addresses

#: The most pages of ``tools/list`` read; a server whose list does not end gives what was read by then.
MAX_TOOL_PAGES = 20
#: The most bytes of one answer of the server (a JSON answer or one stream), read before it is refused.
RESPONSE_LIMIT_BYTES = 4 * 1024 * 1024


class ResponseTooLargeError(httpx2.HTTPError):
    """An answer of the MCP server is larger than the limit (it is not read any further)."""


async def list_all_tools(session: Any) -> list[Any]:
    """The tools of every page, at most :data:`MAX_TOOL_PAGES` pages, ending at a cursor seen before."""
    listed: list[Any] = []
    seen: set[str] = set()
    cursor: str | None = None
    for _ in range(MAX_TOOL_PAGES):
        page = await session.list_tools(params=None if cursor is None else {"cursor": cursor})
        listed.extend(page.tools)
        cursor = getattr(page, "next_cursor", None)
        if not cursor or cursor in seen:
            break
        seen.add(cursor)
    return listed


class _CappedStream(httpx2.AsyncByteStream):
    """The body of an answer, refused once it passes ``limit`` bytes."""

    def __init__(self, inner: httpx2.AsyncByteStream, limit: int) -> None:
        self._inner, self._limit = inner, limit

    async def __aiter__(self) -> AsyncIterator[bytes]:
        read = 0
        async for chunk in self._inner:
            read += len(chunk)
            if read > self._limit:
                raise ResponseTooLargeError(
                    f"The answer of the MCP server is larger than {self._limit} bytes"
                )
            yield chunk

    async def aclose(self) -> None:
        await self._inner.aclose()


class McpToolError(Exception):
    """The MCP server cannot be used (the message is for people and never holds the token)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class GuardedTransport(httpx2.AsyncBaseTransport):
    """An httpx2 transport that vets the addresses of every request's host and connects to one of them."""

    def __init__(self, allow_private: bool, limit: int = RESPONSE_LIMIT_BYTES) -> None:
        self._allow_private = allow_private
        self._limit = limit
        self._inner = httpx2.AsyncHTTPTransport(trust_env=False)
        #: The status of the last answer: the SDK reports a refused request without it.
        self.last_status: int | None = None

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        host = request.url.host
        scheme = request.url.scheme
        port = request.url.port or (443 if scheme == "https" else 80)
        addresses = await vetted_addresses(host, port, self._allow_private)
        default = 443 if scheme == "https" else 80
        named = f"[{host}]" if ":" in host else host  # an IPv6 literal is written in brackets
        headers = request.headers.copy()
        headers["Host"] = named if port == default else f"{named}:{port}"
        extensions = dict(request.extensions)
        if scheme == "https":
            extensions["sni_hostname"] = host
        last: Exception | None = None
        for address in addresses:
            # a copy goes to the address: the request itself keeps its URL, so a redirect the client
            # builds from it still names the host (Host header and TLS name), and is vetted again
            pinned = httpx2.Request(
                request.method,
                request.url.copy_with(host=str(address)),
                headers=headers,
                stream=request.stream,
                extensions=extensions,
            )
            try:
                response = await self._inner.handle_async_request(pinned)
            except httpx2.ConnectError as error:
                last = error
                continue
            self.last_status = response.status_code
            return httpx2.Response(
                response.status_code,
                headers=response.headers,
                stream=_CappedStream(response.stream, self._limit),  # type: ignore[arg-type]
                extensions=response.extensions,
            )
        raise last or httpx2.ConnectError("no address")

    async def aclose(self) -> None:
        await self._inner.aclose()


@dataclass(frozen=True)
class McpTool:
    """A tool of the server as the model is told about it."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class McpServer:
    """An open connection to one MCP server for the time of one agent run."""

    session: ClientSession
    tools: list[McpTool]
    timeout: float
    offered: set[str] = field(default_factory=set)
    #: Tools *Tools to include* names that the server does not have, and (with a read-only connection) tools it names that were
    #: held back because the server announces them as changing something: the run says so instead of leaving them out silently.
    missing: list[str] = field(default_factory=list)
    held_back: list[str] = field(default_factory=list)

    async def call(self, name: str, arguments: Mapping[str, Any]) -> str:
        """The text of the tool's answer, or ``Error: ...`` (the model reads it and may try otherwise)."""
        if name not in self.offered:
            return f"Error: the tool {name} is not offered to this agent"
        try:
            result = await self.session.call_tool(
                name, dict(arguments), read_timeout_seconds=self.timeout
            )
        except Exception as error:  # the session reports a failed call in many shapes
            return f"Error: the call failed ({_reason(error)})"
        content = getattr(result, "content", None) or []
        parts = [_content_text(item) for item in content]
        if not parts and getattr(result, "structured_content", None) is not None:
            parts.append(json.dumps(result.structured_content, ensure_ascii=False))
        text = "\n".join(parts)
        return f"Error: {text}" if getattr(result, "is_error", False) else text


def _content_text(item: Any) -> str:
    """The text of one piece of a tool's answer: its text, the text of an embedded resource (GitHub answers a file this way:
    the model must read the file, not a marker), or a short note for what cannot be read as text (an image, a binary file)."""
    text = getattr(item, "text", None)
    if isinstance(text, str):
        return text
    resource = getattr(item, "resource", None)
    if resource is not None:
        inner = getattr(resource, "text", None)
        if isinstance(inner, str):
            return inner
        mime = getattr(resource, "mime_type", None) or getattr(resource, "mimeType", None)
        uri = getattr(resource, "uri", None)
        return f"[binary resource {uri or ''} {mime or ''}]".replace("  ", " ").replace(" ]", "]")
    return f"[{getattr(item, 'type', 'content')}]"


def _leaves(error: BaseException) -> list[BaseException]:
    """The exceptions inside (nested) exception groups, or the exception itself."""
    if isinstance(error, BaseExceptionGroup):
        return [leaf for inner in error.exceptions for leaf in _leaves(inner)]
    return [error]


def _reason(error: BaseException) -> str:
    """Why a connection or call failed, in words that never hold a header or the token."""
    for leaf in _leaves(error):
        if isinstance(leaf, AddressRefusedError | ResponseTooLargeError):
            return str(leaf)
        if isinstance(leaf, httpx2.HTTPStatusError):
            status = leaf.response.status_code
            if status in (401, 403):
                return f"refused the token (HTTP {status})"
            return f"HTTP {status}"
        if isinstance(leaf, httpx2.TimeoutException):
            return "timeout"
        if isinstance(leaf, httpx2.ConnectError):
            return "the connection failed"
    leaf = _leaves(error)[0]
    return type(leaf).__name__


def _failure(error: BaseException, status: int | None) -> McpToolError:
    if status in (401, 403):
        return McpToolError(f"The MCP server refused the token (HTTP {status})")
    reason = _reason(error)
    if status is not None and status >= 400 and not reason.startswith("The address"):
        return McpToolError(f"The MCP server could not be reached (HTTP {status})")
    if reason.startswith(("The address", "The answer")):
        return McpToolError(reason)
    if reason.startswith("refused the token"):
        return McpToolError(f"The MCP server {reason}")
    return McpToolError(f"The MCP server could not be reached ({reason})")


def _mode(config: Mapping[str, Any]) -> str:
    return str(config.get("tools_mode") or "all")


def _named(config: Mapping[str, Any]) -> list[str]:
    """The tool names the node lists (only when its mode uses them), in the order written."""
    if _mode(config) == "all":
        return []
    return parse_tool_names(str(config.get("tool_names") or ""))


def _included(names: Sequence[str], config: Mapping[str, Any]) -> set[str]:
    mode = _mode(config)
    listed = set(_named(config))
    if mode == "selected":
        return {n for n in names if n in listed}
    if mode == "all_except":
        return {n for n in names if n not in listed}
    return set(names)


@asynccontextmanager
async def open_mcp(
    config: Mapping[str, Any],
    token: str | None,
    *,
    allow_private: bool,
    headers: Mapping[str, str] | None = None,
    read_only: bool = False,
) -> AsyncIterator[McpServer]:
    """Connect to the server of an MCP Client Tool node and list its tools; :class:`McpToolError` if that fails.

    ``headers`` are sent with every request besides the token. ``read_only`` leaves out every tool the server announces as one
    that changes something (``readOnlyHint`` false): a second line behind whatever the server enforces itself."""
    url = str(config.get("url") or "").strip()
    try:
        check_endpoint(url)
    except ToolConfigError as error:
        raise McpToolError(str(error)) from None
    if not url:
        raise McpToolError("The MCP Client Tool has no endpoint")
    timeout = float(config.get("timeout_seconds") or 60)
    sent = {**(headers or {}), **({"Authorization": f"Bearer {token}"} if token else {})}
    transport = GuardedTransport(allow_private)
    try:
        async with _connected(url, sent, timeout, transport, config, read_only) as server:
            yield server
    except BaseExceptionGroup as group:
        # the SDK's task groups wrap what happens inside them; hand on the error itself
        leaves = _leaves(group)
        own = [e for e in leaves if isinstance(e, McpToolError)]
        if own:
            raise own[0] from None
        body = [e for e in leaves if not _is_transport_error(e)]
        if body:
            raise body[0] from None
        raise _failure(group, transport.last_status) from None


def _is_transport_error(error: BaseException) -> bool:
    return isinstance(error, AddressRefusedError | httpx2.HTTPError | MCPError)


@asynccontextmanager
async def _connected(
    url: str,
    headers: dict[str, str],
    timeout: float,
    transport: GuardedTransport,
    config: Mapping[str, Any],
    read_only: bool = False,
) -> AsyncIterator[McpServer]:
    async with AsyncExitStack() as stack:
        try:
            client = await stack.enter_async_context(
                httpx2.AsyncClient(
                    headers=headers,
                    timeout=httpx2.Timeout(timeout),
                    transport=transport,
                    trust_env=False,
                )
            )
            read, write = await stack.enter_async_context(
                streamable_http_client(url, http_client=client, terminate_on_close=False)
            )
            session = await stack.enter_async_context(
                ClientSession(read, write, read_timeout_seconds=timeout)
            )
            await session.initialize()
            listed = await list_all_tools(session)
        except McpToolError:
            raise
        except Exception as error:  # an ExceptionGroup of the SDK included
            raise _failure(error, transport.last_status) from None
        every = {t.name for t in listed}
        if read_only:
            listed = [
                t for t in listed if getattr(t.annotations, "read_only_hint", None) is not False
            ]
        offered = _included([t.name for t in listed], config)
        tools = [
            McpTool(t.name, t.description or "", dict(t.input_schema or {"type": "object"}))
            for t in listed
            if t.name in offered
        ]
        named = _named(config)
        kept = {t.name for t in listed}
        missing = [n for n in named if n not in every]
        held = (
            [n for n in named if n in every and n not in kept]
            if _mode(config) == "selected"
            else []
        )
        yield McpServer(session, tools, timeout, offered, missing, held)
