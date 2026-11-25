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


async def test_tools_to_include_selected_offers_only_the_named_tools_and_says_what_the_server_lacks(
    endpoint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tools, "GITHUB_MCP_URL", endpoint)
    frozen = _frozen(tools_mode="selected", tool_names="get_issue\nnot_there\nlist_issues")
    async with open_toolbox([frozen], _context()) as box:
        names = [s["function"]["name"] for s in box.schemas()]
        notes = box.notes
    assert names == ["get_issue", "list_issues"], "only what was named, in the server's order"
    assert notes == ["Tool Hub: the server has no tool named not_there"], "not silent"


async def test_all_except_leaves_the_named_tools_out(
    endpoint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tools, "GITHUB_MCP_URL", endpoint)
    frozen = _frozen(tools_mode="all_except", tool_names="explode")
    async with open_toolbox([frozen], _context()) as box:
        names = [s["function"]["name"] for s in box.schemas()]
    assert names == [
        "get_issue",
        "list_issues",
    ]  # explode is out, create_issue is held back by the read-only connection


async def test_the_selection_works_on_top_of_the_read_only_hold(
    endpoint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tool the server announces as changing something stays out while Allow writes is off, even when it is named."""
    monkeypatch.setattr(tools, "GITHUB_MCP_URL", endpoint)
    named = _frozen(tools_mode="selected", tool_names="get_issue\ncreate_issue")
    async with open_toolbox([named], _context()) as box:
        assert [s["function"]["name"] for s in box.schemas()] == ["get_issue"]
        assert box.notes == [
            "Tool Hub: create_issue not offered (it changes something and Allow writes is off)"
        ]
    with_writes = _frozen(
        tools_mode="selected", tool_names="get_issue\ncreate_issue", allow_write=True
    )
    async with open_toolbox([with_writes], _context()) as box:
        assert [s["function"]["name"] for s in box.schemas()] == ["get_issue", "create_issue"]
        assert box.notes == []


async def test_a_node_that_names_nothing_offers_all_as_before(
    endpoint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tools, "GITHUB_MCP_URL", endpoint)
    async with open_toolbox([_frozen(tools_mode="selected", tool_names="")], _context()) as box:
        assert not box, "selected with an empty list offers nothing (as the MCP Client Tool does)"
    async with open_toolbox([_frozen()], _context()) as box:
        assert len(box.schemas()) == 3
