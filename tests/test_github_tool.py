"""The GitHub MCP node: an agent works with GitHub through GitHub's MCP server, held to reading unless the node allows writes."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from openartifact.agents import tools
from openartifact.agents.tools import ToolContext, open_toolbox, secret_names
from tests.mcp_support import CALLS, READONLY_HEADERS, TOKEN, mcp_server


@pytest.fixture(scope="module")
def endpoint() -> Iterator[str]:
    with mcp_server() as url:
        yield url


def _frozen(**config: Any) -> dict[str, Any]:
    return {
        "kind": "github_tool",
        "name": "Hub",
        "tool_name": "",
        "config": {"secret": "GH", **config},
    }


def _context() -> ToolContext:
    return ToolContext(secrets={"GH": TOKEN}, allow_private_networks=True)


async def test_the_node_reads_only_by_default_and_asks_the_server_to_hold_it_to_reading(
    endpoint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tools, "GITHUB_MCP_URL", endpoint)
    READONLY_HEADERS.clear()
    async with open_toolbox([_frozen()], _context()) as box:
        names = [s["function"]["name"] for s in box.schemas()]
    assert names == ["get_issue", "list_issues", "explode"], (
        "the tool that changes something is left out"
    )
    assert READONLY_HEADERS and set(READONLY_HEADERS) == {"true"}


async def test_with_allow_writes_every_tool_is_offered_and_the_server_is_not_held_to_reading(
    endpoint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tools, "GITHUB_MCP_URL", endpoint)
    READONLY_HEADERS.clear()
    async with open_toolbox([_frozen(allow_write=True)], _context()) as box:
        names = [s["function"]["name"] for s in box.schemas()]
        made = await box.call("c1", "create_issue", '{"title": "x"}')
    assert "create_issue" in names
    assert made.result == "Created #3" and ("create_issue", {"title": "x"}) in CALLS
    assert READONLY_HEADERS == []


def test_the_credential_of_the_node_is_a_secret_the_run_resolves() -> None:
    assert secret_names([_frozen()]) == ["GH"]
