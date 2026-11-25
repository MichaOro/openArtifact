"""The tool loop of an agent node: requests with tools, tool calls, results back, the limits (ADR-040)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from openartifact.agents.client import Completion, ToolCall
from openartifact.agents.runtime import run_node
from openartifact.agents.tools import (
    TOOL_RESULT_LIMIT_BYTES,
    Tool,
    Toolbox,
    ToolboxError,
    ToolContext,
    open_toolbox,
)
from tests.test_agent_runtime import OK, VIEW, Scripted, _frozen


def _asks(*calls: tuple[str, str, str]) -> Completion:
    """An answer that calls tools: ``(id, name, arguments)``."""
    return Completion("", "tool_calls", 3, 1, 4, 200, tuple(ToolCall(*c) for c in calls))


class Recorder:
    def __init__(self, answer: Any = "Sunny") -> None:
        self.answer = answer
        self.seen: list[dict[str, Any]] = []

    async def __call__(self, arguments: dict[str, Any]) -> str:
        self.seen.append(arguments)
        if isinstance(self.answer, Exception):
            raise self.answer
        if isinstance(self.answer, float):
            await asyncio.sleep(self.answer)
            return "late"
        return str(self.answer)


WEATHER = {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}


def _box(*tools: Tool) -> Any:
    @asynccontextmanager
    async def open_tools() -> AsyncIterator[Toolbox]:
        yield Toolbox(list(tools))

    return open_tools


def _with_tools(**node: Any) -> dict[str, Any]:
    frozen = _frozen(**node)
    frozen["agent"]["tools"] = [
        {
            "node_id": "t1",
            "name": "Weather",
            "kind": "http_tool",
            "tool_name": "weather",
            "config": {},
        }
    ]
    return frozen


async def test_an_agent_without_tools_sends_no_tools_and_makes_one_request() -> None:
    script = Scripted(OK)
    result = await run_node(
        _frozen(), VIEW, "key", complete=script.complete, sleep=script.sleep, open_tools=_box()
    )
    assert result.outcome == "pass" and len(script.calls) == 1
    assert "tools" not in script.calls[0]
    assert [t["tool_calls"] for t in result.detail["turns"]] == [[]]  # type: ignore[index]


async def test_a_tool_call_runs_the_tool_and_sends_its_result_back() -> None:
    weather = Recorder("Sunny, 21 C")
    script = Scripted(_asks(("c1", "weather", '{"city": "Bonn"}')), OK)
    result = await run_node(
        _with_tools(),
        VIEW,
        "key",
        complete=script.complete,
        sleep=script.sleep,
        open_tools=_box(Tool("weather", "The weather of a city", WEATHER, weather)),
    )
    assert (result.outcome, result.output) == ("pass", "Fine")
    assert weather.seen == [{"city": "Bonn"}]
    first, second = script.calls
    assert first["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "weather",
                "description": "The weather of a city",
                "parameters": WEATHER,
            },
        }
    ]
    assert second["messages"][-2:] == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "weather", "arguments": '{"city": "Bonn"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "Sunny, 21 C"},
    ]
    assert result.data["usage"] == {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11}  # type: ignore[index]
    assert result.data["attempts"] == 2 and result.data["iterations"] == 2  # type: ignore[index]
    turns = result.detail["turns"]  # type: ignore[index]
    assert [len(t["attempts"]) for t in turns] == [1, 1]
    (call,) = turns[0]["tool_calls"]
    assert (call["tool"], call["arguments"], call["result"], call["error"]) == (
        "weather",
        '{"city": "Bonn"}',
        "Sunny, 21 C",
        False,
    )
    assert turns[1]["text"] == "Fine"


async def test_an_unknown_tool_bad_arguments_and_a_failing_tool_go_back_to_the_model_as_errors() -> (
    None
):
    broken = Recorder(RuntimeError("the service is down"))
    script = Scripted(
        _asks(
            ("c1", "nothere", "{}"),
            ("c2", "weather", "{not json"),
            ("c3", "weather", "[1]"),
            ("c4", "weather", '{"city": "X"}'),
        ),
        OK,
    )
    result = await run_node(
        _with_tools(),
        VIEW,
        "key",
        complete=script.complete,
        sleep=script.sleep,
        open_tools=_box(Tool("weather", "", WEATHER, broken)),
    )
    assert result.outcome == "pass"
    answers = [m["content"] for m in script.calls[1]["messages"] if m["role"] == "tool"]
    assert answers == [
        "Error: there is no tool named nothere",
        "Error: the arguments are not valid JSON",
        "Error: the arguments are not a JSON object",
        "Error: the tool failed (RuntimeError: the service is down)",
    ]
    assert broken.seen == [{"city": "X"}]
    assert [c["error"] for c in result.detail["turns"][0]["tool_calls"]] == [True] * 4  # type: ignore[index]


async def test_the_iteration_limit_asks_for_the_answer_without_running_the_last_calls() -> None:
    """The limit is a safety net: the agent writes its answer from what it has (one more request, without tools); the step passes
    with a note (card #104; it failed with "Stopped after 2 iterations without a final answer" before)."""
    weather = Recorder()
    script = Scripted(_asks(("c1", "weather", "{}")), _asks(("c2", "weather", "{}")), OK)
    result = await run_node(
        _with_tools(max_iterations=2),
        VIEW,
        "key",
        complete=script.complete,
        sleep=script.sleep,
        open_tools=_box(Tool("weather", "", WEATHER, weather)),
    )
    assert (result.outcome, result.output) == ("pass", "Fine")
    assert "the limit of 2 iterations was reached" in (result.reason or "")
    assert len(weather.seen) == 1, "the calls of the last answer were not run"
    assert len(script.calls) == 3 and "tools" not in script.calls[2], (
        "the final request offers no tools"
    )


async def test_a_long_tool_result_is_cut_for_the_history_and_further_for_the_model() -> None:
    """The step keeps the result up to 16 KiB; the model reads at most the node's tool result limit (agents/context_window.py)."""
    script = Scripted(_asks(("c1", "weather", "{}")), OK)
    huge = "x" * (TOOL_RESULT_LIMIT_BYTES + 500)
    result = await run_node(
        _with_tools(),
        VIEW,
        "key",
        complete=script.complete,
        sleep=script.sleep,
        open_tools=_box(Tool("weather", "", WEATHER, Recorder(huge))),
    )
    stored = result.detail["turns"][0]["tool_calls"][0]["result"]  # type: ignore[index]
    assert len(stored.encode()) <= TOOL_RESULT_LIMIT_BYTES + 100 and stored.endswith(
        "[cut: the result is longer than 16 KiB]"
    ), "the step keeps the result up to 16 KiB"
    sent = script.calls[1]["messages"][-1]["content"]
    assert sent.startswith("x" * 12000) and "[cut for the model:" in sent and len(sent) < 12200


async def test_the_time_limit_of_the_node_covers_the_tool_calls() -> None:
    """A tool that outlasts the time of the node is stopped and reported to the model as an error, then the agent answers from what it
    has (it failed the node with "The tool weather did not finish within the time limit of 1 s" before, card #104)."""
    script = Scripted(_asks(("c1", "weather", "{}")), OK)
    result = await run_node(
        _with_tools(total_timeout_seconds=1),
        VIEW,
        "key",
        complete=script.complete,
        sleep=script.sleep,
        open_tools=_box(Tool("weather", "", WEATHER, Recorder(3.0))),
    )
    assert (result.outcome, result.output) == ("pass", "Fine")
    assert "the time limit of 1 s was reached" in (result.reason or "")
    (call,) = result.detail["turns"][0]["tool_calls"]  # type: ignore[index]
    assert (
        call["error"] is True
        and call["result"] == "Error: the tool weather did not answer within 1 s"
    )
    assert len(script.calls) == 2 and "tools" not in script.calls[1]


async def test_tools_that_cannot_be_opened_fail_the_node_before_any_request() -> None:
    @asynccontextmanager
    async def refuse() -> AsyncIterator[Toolbox]:
        raise ToolboxError("Tool GitHub: The MCP server refused the token (HTTP 401)")
        yield Toolbox([])  # pragma: no cover

    script = Scripted(OK)
    result = await run_node(
        _with_tools(), VIEW, "key", complete=script.complete, sleep=script.sleep, open_tools=refuse
    )
    assert (result.outcome, result.reason) == (
        "fail",
        "Tool GitHub: The MCP server refused the token (HTTP 401)",
    )
    assert script.calls == []


def test_names_for_the_model_are_unique_and_valid() -> None:
    async def nothing(arguments: dict[str, Any]) -> str:
        return ""

    box = Toolbox(
        [
            Tool("search", "", {}, nothing, prefix="github"),
            Tool("search", "", {}, nothing, prefix="jira"),
            Tool("repo.read/file", "", {}, nothing, prefix="github"),
            Tool("weather", "", {}, nothing),
        ]
    )
    names = [s["function"]["name"] for s in box.schemas()]
    assert names == ["github_search", "jira_search", "repo_read_file", "weather"]
    assert all(
        s["function"]["parameters"] == {"type": "object", "properties": {}} for s in box.schemas()
    )
    assert json.dumps(box.schemas())  # sendable as it is


async def test_the_text_of_a_failing_tool_is_masked_before_the_model_reads_it() -> None:
    async def leaks(arguments: dict[str, Any]) -> str:
        raise RuntimeError("could not log in with token-SECRET-42")

    box = Toolbox(
        [Tool("login", "", {}, leaks)], mask=lambda text: text.replace("token-SECRET-42", "***")
    )
    record = await box.call("c1", "login", "{}")
    assert record.result == "Error: the tool failed (RuntimeError: could not log in with ***)"


async def test_two_local_tools_with_one_name_get_their_node_names_in_front() -> None:
    frozen = [
        {
            "node_id": f"n{n}",
            "name": node,
            "kind": "code_tool",
            "tool_name": "search",
            "config": {"code": "print(1)"},
        }
        for n, node in enumerate(("Jira", "Wiki search"))
    ]
    async with open_toolbox(frozen, ToolContext({}, False)) as box:
        assert [s["function"]["name"] for s in box.schemas()] == [
            "Jira_search",
            "Wiki_search_search",
        ]


async def test_opening_the_tools_counts_against_the_time_limit_of_the_node() -> None:
    @asynccontextmanager
    async def slow() -> AsyncIterator[Toolbox]:
        await asyncio.sleep(3)
        yield Toolbox([])  # pragma: no cover

    script = Scripted(OK)
    result = await run_node(
        _with_tools(total_timeout_seconds=1),
        VIEW,
        "key",
        complete=script.complete,
        sleep=script.sleep,
        open_tools=slow,
    )
    assert (result.outcome, result.reason) == (
        "fail",
        "The tools could not be opened within the time limit of 1 s",
    )
    assert script.calls == []


async def test_a_later_turn_names_the_time_limit_of_the_node_not_what_was_left() -> None:
    from tests.test_agent_runtime import _transient

    # the request after the tool call fails (the wait of the retry does not fit), and so does the final request
    script = Scripted(
        _asks(("c1", "weather", "{}")), _transient(503), _transient(503), _transient(503)
    )
    result = await run_node(
        _with_tools(total_timeout_seconds=5, retries=1),
        VIEW,
        "key",
        complete=script.complete,
        sleep=script.sleep,
        open_tools=_box(Tool("weather", "", WEATHER, Recorder(2.5))),
    )
    assert result.outcome == "fail"
    assert "the time limit of 5 s" in (result.reason or ""), result.reason
