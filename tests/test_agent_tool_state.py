"""What an agent run says about its tool nodes: every tool call knows the tool node it belongs to, the loop tells the application when a
call starts and ends (names and states only), and the step keeps a summary per tool node, which the flow shows as the node's state."""

from __future__ import annotations

from typing import Any

from openartifact.agents.loop import tools_used
from openartifact.agents.runtime import run_node
from openartifact.agents.tools import Tool
from tests.test_agent_loop import WEATHER, Recorder, _asks, _box, _with_tools
from tests.test_agent_runtime import OK, VIEW, Scripted


def _tool(name: str, node: str, answer: Any = "ok") -> Tool:
    return Tool(
        name, f"The tool {name}", WEATHER, Recorder(answer), node_id=node, node_name=node.upper()
    )


async def _run(script: Scripted, *tools: Tool) -> tuple[Any, list[dict[str, Any]]]:
    seen: list[dict[str, Any]] = []
    result = await run_node(
        _with_tools(),
        VIEW,
        "key",
        complete=script.complete,
        sleep=script.sleep,
        open_tools=_box(*tools),
        on_event=lambda event, data: seen.append(data) if event == "tool_call" else None,
    )
    return result, seen


async def test_a_call_tells_when_it_starts_and_ends_with_names_and_state_only() -> None:
    result, seen = await _run(
        Scripted(_asks(("c1", "weather", '{"city": "Secretville"}')), OK), _tool("weather", "t1")
    )
    assert result.outcome == "pass"
    assert [e["state"] for e in seen] == ["started", "finished"]
    started, finished = seen
    assert started["agent_node_id"] == finished["agent_node_id"] == _with_tools()["id"]
    assert (started["tool_node_id"], started["tool_node_name"], started["tool"]) == (
        "t1",
        "T1",
        "weather",
    )
    assert finished["ok"] is True and isinstance(finished["duration_ms"], int)
    assert "Secretville" not in repr(seen), "no arguments and no results in an event"


async def test_a_failing_call_ends_as_not_ok_and_the_step_counts_the_error() -> None:
    script = Scripted(_asks(("c1", "weather", "{}"), ("c2", "weather", "{}")), OK)
    result, seen = await _run(script, _tool("weather", "t1", answer=ValueError("down")))
    assert [e.get("ok") for e in seen if e["state"] == "finished"] == [False, False]
    assert result.data["tools"] == [{"node": "t1", "name": "T1", "calls": 2, "errors": 2}]
    calls = [c for t in result.detail["turns"] for c in t["tool_calls"]]
    assert {(c["node_id"], c["node_name"]) for c in calls} == {("t1", "T1")}


async def test_every_tool_node_is_counted_on_its_own_even_when_one_offers_several_tools() -> None:
    script = Scripted(_asks(("c1", "a", "{}"), ("c2", "b", "{}")), _asks(("c3", "a", "{}")), OK)
    result, _ = await _run(script, _tool("a", "t1"), _tool("b", "t2", answer=ValueError("no")))
    assert result.data["tools"] == [
        {"node": "t1", "name": "T1", "calls": 2, "errors": 0},
        {"node": "t2", "name": "T2", "calls": 1, "errors": 1},
    ]


async def test_a_call_of_a_tool_that_does_not_exist_belongs_to_no_node() -> None:
    result, seen = await _run(Scripted(_asks(("c1", "ghost", "{}")), OK), _tool("weather", "t1"))
    assert seen == [], "nothing to show on a node"
    assert "tools" not in result.data, "no summary without a tool node"
    (call,) = result.detail["turns"][0]["tool_calls"]
    assert call["error"] is True and call["node_id"] == ""


def test_records_of_before_have_no_node_and_do_not_break_the_summary() -> None:
    turns = [
        {
            "tool_calls": [
                {"tool": "x", "error": False},
                {"tool": "y", "error": True, "node_id": "t9", "node_name": "N"},
            ]
        },
        {},
    ]
    assert tools_used(turns) == [{"node": "t9", "name": "N", "calls": 1, "errors": 1}]
