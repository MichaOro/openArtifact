"""The MCP Client Tool: a remote MCP server reached through the guarded transport (ADR-040)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any, ClassVar

import httpx2
import pytest

from openartifact.agents.mcp_client import (
    MAX_TOOL_PAGES,
    GuardedTransport,
    McpToolError,
    ResponseTooLargeError,
    list_all_tools,
    open_mcp,
)
from tests.mcp_support import CALLS, REQUESTS, TOKEN, mcp_server


@pytest.fixture(scope="module")
def endpoint() -> Iterator[str]:
    with mcp_server() as url:
        yield url


def _config(url: str, **more: object) -> dict[str, object]:
    return {"url": url, "tools_mode": "all", "tool_names": "", "timeout_seconds": 10, **more}


async def test_the_tools_of_the_server_are_listed_with_their_schemas(endpoint: str) -> None:
    async with open_mcp(_config(endpoint), TOKEN, allow_private=True) as server:
        names = [t.name for t in server.tools]
        assert names == ["get_issue", "list_issues", "create_issue", "explode"]
        issue = server.tools[0]
        assert issue.description == "Read one issue by its number."
        assert issue.input_schema["properties"]["number"]["type"] == "integer"


@pytest.mark.parametrize(
    ("mode", "names", "expected"),
    [
        ("selected", "get_issue\nlist_issues\nnot_there", ["get_issue", "list_issues"]),
        ("all_except", "create_issue\nexplode", ["get_issue", "list_issues"]),
        ("selected", "", []),
    ],
)
async def test_tools_to_include_filters_what_the_agent_may_use(
    endpoint: str, mode: str, names: str, expected: list[str]
) -> None:
    async with open_mcp(
        _config(endpoint, tools_mode=mode, tool_names=names), TOKEN, allow_private=True
    ) as server:
        assert [t.name for t in server.tools] == expected


async def test_a_tool_is_called_and_its_text_comes_back(endpoint: str) -> None:
    async with open_mcp(_config(endpoint), TOKEN, allow_private=True) as server:
        assert await server.call("get_issue", {"number": 7}) == "Issue #7: Login is broken"
    assert ("get_issue", {"number": 7}) in CALLS


async def test_a_tool_that_fails_or_is_not_offered_is_an_error_text(endpoint: str) -> None:
    async with open_mcp(
        _config(endpoint, tools_mode="all_except", tool_names="create_issue"),
        TOKEN,
        allow_private=True,
    ) as server:
        failed = await server.call("explode", {})
        # the server decides how much of its error it tells; the model gets it marked as an error
        assert failed == "Error: Error executing tool explode"
        refused = await server.call("create_issue", {"title": "x"})
        assert refused == "Error: the tool create_issue is not offered to this agent"
    assert ("create_issue", {"title": "x"}) not in CALLS  # never reached the server


async def test_a_wrong_token_is_refused_with_a_clear_reason(endpoint: str) -> None:
    with pytest.raises(McpToolError) as caught:
        async with open_mcp(_config(endpoint), "wrong", allow_private=True):
            pass
    assert caught.value.message == "The MCP server refused the token (HTTP 401)"
    assert "wrong" not in caught.value.message


async def test_a_private_address_needs_the_permission(endpoint: str) -> None:
    REQUESTS.clear()
    with pytest.raises(McpToolError) as caught:
        async with open_mcp(_config(endpoint), TOKEN, allow_private=False):
            pass
    assert caught.value.message == "The address is not allowed (private network address)"
    assert REQUESTS == []  # refused before a connection was made


async def test_a_metadata_address_is_refused_even_when_private_is_allowed() -> None:
    with pytest.raises(McpToolError) as caught:
        async with open_mcp(_config("http://169.254.169.254/mcp"), None, allow_private=True):
            pass
    assert caught.value.message == "The address is not allowed (cloud metadata address)"


async def test_a_server_that_is_not_there_fails_cleanly() -> None:
    with mcp_server() as gone:
        url = gone
    with pytest.raises(McpToolError) as caught:
        async with open_mcp(_config(url, timeout_seconds=3), TOKEN, allow_private=True):
            pass
    assert caught.value.message.startswith("The MCP server could not be reached")


async def test_a_host_name_is_kept_for_the_server_while_the_connection_goes_to_the_checked_address(
    endpoint: str,
) -> None:
    by_name = endpoint.replace("127.0.0.1", "localhost")
    async with open_mcp(_config(by_name), TOKEN, allow_private=True) as server:
        assert await server.call("get_issue", {"number": 1}) == "Issue #1: Login is broken"


class _Redirects(BaseHTTPRequestHandler):
    seen: ClassVar[list[tuple[str, str]]] = []

    def do_GET(self) -> None:
        _Redirects.seen.append((self.path, self.headers["Host"]))
        if self.path == "/mcp":
            self.send_response(307)
            self.send_header("Location", "/mcp/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"x" * (5000 if self.path == "/big" else 2)
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def plain() -> Iterator[int]:
    _Redirects.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Redirects)
    threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


async def test_a_redirect_on_the_same_origin_keeps_the_host_name(plain: int) -> None:
    transport = GuardedTransport(allow_private=True)
    async with httpx2.AsyncClient(transport=transport, follow_redirects=True) as client:
        response = await client.get(f"http://localhost:{plain}/mcp")
    assert response.status_code == 200
    assert _Redirects.seen == [("/mcp", f"localhost:{plain}"), ("/mcp/", f"localhost:{plain}")]


async def test_an_answer_larger_than_the_limit_is_not_read_into_memory(plain: int) -> None:
    transport = GuardedTransport(allow_private=True, limit=1000)
    async with httpx2.AsyncClient(transport=transport) as client:
        assert (await client.get(f"http://127.0.0.1:{plain}/small")).status_code == 200
        with pytest.raises(
            ResponseTooLargeError, match=r"The answer of the MCP server is larger than 1000 bytes"
        ):
            await client.get(f"http://127.0.0.1:{plain}/big")


class _Pages:
    """A session whose tool list never ends (or repeats its cursor)."""

    def __init__(self, repeat: bool) -> None:
        self.repeat, self.asked = repeat, 0

    async def list_tools(self, params: Any = None) -> Any:
        self.asked += 1
        tool = SimpleNamespace(
            name=f"t{self.asked}", description="", input_schema={"type": "object"}
        )
        return SimpleNamespace(
            tools=[tool], next_cursor="same" if self.repeat else f"c{self.asked}"
        )


async def test_the_tool_list_is_read_in_a_bounded_number_of_pages() -> None:
    endless = _Pages(repeat=False)
    assert len(await list_all_tools(endless)) == MAX_TOOL_PAGES and endless.asked == MAX_TOOL_PAGES
    repeating = _Pages(repeat=True)
    assert (
        len(await list_all_tools(repeating)) == 2 and repeating.asked == 2
    )  # a cursor seen before ends it
