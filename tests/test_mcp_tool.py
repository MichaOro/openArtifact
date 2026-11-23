"""The MCP Client Tool: a remote MCP server reached through the guarded transport (ADR-040)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from openartifact.agents.mcp_client import McpToolError, open_mcp
from tests.mcp_support import CALLS, TOKEN, mcp_server


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
    with pytest.raises(McpToolError) as caught:
        async with open_mcp(_config(endpoint), TOKEN, allow_private=False):
            pass
    assert caught.value.message == "The address is not allowed (private network address)"
    assert CALLS == [] or all(name != "list_issues" for name, _ in CALLS)


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
