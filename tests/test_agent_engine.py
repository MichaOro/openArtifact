"""The engine of an agent node (agents/loop.py, context_window.py, completion.py): limits that end in a final answer, a conversation
that does not grow without end, calls that repeat, a request that cannot be answered, the events while it runs (card #104).

The stand-ins are the ones of the other agent tests: ``Scripted`` for the model and ``Recorder`` for a tool."""

from __future__ import annotations

import json
from itertools import pairwise
from typing import Any

import pytest

from openartifact.agents.client import Completion, ProviderError
from openartifact.agents.completion import ATTEMPT_TIMEOUT_CAP, TIMEOUT_GROWTH, run_completion
from openartifact.agents.context_window import fingerprint, shape_messages
from openartifact.agents.loop import REPEAT_HINT_AFTER, STALL_AFTER, Budget
from openartifact.agents.runtime import run_node
from openartifact.agents.schemas import AgentConfig
from openartifact.agents.tools import Tool
from tests.test_agent_loop import WEATHER, Recorder, _asks, _box, _with_tools
from tests.test_agent_runtime import ENDPOINT, OK, VIEW, Scripted, _transient


async def _run(
    script: Scripted, tool: Tool | None = None, events: list[Any] | None = None, **node: Any
) -> Any:
    return await run_node(
        _with_tools(**node),
        VIEW,
        "key",
        complete=script.complete,
        sleep=script.sleep,
        open_tools=_box(tool or Tool("weather", "", WEATHER, Recorder("Sunny"))),
        on_event=(lambda event, data: events.append((event, data))) if events is not None else None,
    )


# ── the limits end in an answer ──────────────────────────────────────


async def test_the_token_budget_ends_in_an_answer_from_what_the_agent_has() -> None:
    script = Scripted(_asks(("c1", "weather", "{}")), OK)  # the first answer used 4 tokens
    result = await _run(script, token_budget=3)
    assert (result.outcome, result.output) == ("pass", "Fine")
    assert "the token budget of 3 tokens was reached" in result.reason
    assert "tools" not in script.calls[1]


async def test_the_final_request_reads_a_short_conversation_and_is_told_to_answer_now() -> None:
    huge = "y" * 9000
    script = Scripted(_asks(("c1", "weather", "{}")), _asks(("c2", "weather", "{}")), OK)
    await _run(script, Tool("weather", "", WEATHER, Recorder(huge)), max_iterations=2)
    final = script.calls[2]["messages"]
    assert final[-1]["role"] == "user" and "Do not call any tool now" in final[-1]["content"]
    tool_results = [m["content"] for m in final if m["role"] == "tool"]
    assert tool_results and all(len(c) < 3300 for c in tool_results), (
        "a much shorter view than 12000 characters"
    )


async def test_a_request_that_fails_for_good_after_tools_ran_still_ends_in_an_answer() -> None:
    """The case of the owner's run: after seven rounds the model did not answer in time, four times. The agent answers from what the
    tools found instead of failing the node and losing it."""
    script = Scripted(
        _asks(("c1", "weather", "{}")),
        ProviderError("Timeout after 60 s", transient=False),
        OK,
    )
    result = await _run(script)
    assert (result.outcome, result.output) == ("pass", "Fine")
    assert (
        "a request that failed for good was reached" not in result.reason
    )  # said in words, not as a limit
    assert "Timeout after 60 s" in result.reason and "may be incomplete" in result.reason
    assert [bool(t.get("wrap_up")) for t in result.detail["turns"]] == [False, False, True]


async def test_when_the_final_request_fails_too_the_node_fails_and_says_so() -> None:
    script = Scripted(
        _asks(("c1", "weather", "{}")),
        ProviderError("Timeout after 60 s", transient=False),
        ProviderError("HTTP 500: down", transient=False),
    )
    result = await _run(script)
    assert result.outcome == "fail"
    assert (
        "Timeout after 60 s" in result.reason
        and "final answer could not be written: HTTP 500: down" in result.reason
    )


async def test_a_request_that_fails_before_any_tool_ran_fails_as_before() -> None:
    script = Scripted(ProviderError("HTTP 401: no", status=401))
    result = await _run(script)
    assert (result.outcome, result.reason) == ("fail", "HTTP 401: no")
    assert len(script.calls) == 1


def test_the_budget_names_the_limit_that_is_reached() -> None:
    import time

    now = time.monotonic()
    budget = Budget(total_seconds=100, iterations=5, tokens=1000, started=now)
    assert budget.reason(5, 0) == "the limit of 5 iterations"
    assert budget.reason(1, 1000) == "the token budget of 1000 tokens"
    assert budget.reason(1, 10) is None
    assert Budget(1, 5, None, now - 10).reason(1, 0) == "the time limit of 1 s"


# ── the model reads a view of the conversation ───────────────────────


def _conversation(rounds: int, size: int) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "user", "content": "Go"}]
    for n in range(rounds):
        messages.append({"role": "assistant", "content": None, "tool_calls": [{"id": f"c{n}"}]})
        messages.append({"role": "tool", "tool_call_id": f"c{n}", "content": f"{n}" * size})
    return messages


def test_older_rounds_are_shortened_and_the_last_ones_cut_at_the_limit() -> None:
    messages = _conversation(5, 5000)
    shaped = shape_messages(messages, result_chars=4000, older_chars=300)
    tools = [m["content"] for m in shaped if m["role"] == "tool"]
    assert [len(c) < 400 for c in tools] == [True, True, True, False, False], (
        "the last two rounds stay (cut at 4000)"
    )
    assert "shortened: an earlier result of 5000 characters" in tools[0]
    assert tools[4].startswith("4" * 4000) and "cut for the model: 1000 more characters" in tools[4]
    assert [len(m["content"]) for m in messages if m["role"] == "tool"] == [5000] * 5, (
        "the conversation itself is not changed"
    )


def test_a_hint_goes_on_the_result_it_is_for() -> None:
    shaped = shape_messages(_conversation(2, 10), result_chars=100, hints={"c1": "Note: same call"})
    assert (
        shaped[-1]["content"].endswith("\n[Note: same call]") and "Note" not in shaped[2]["content"]
    )


def test_the_same_call_is_the_same_whatever_the_order_of_the_arguments() -> None:
    assert fingerprint("get", '{"a": 1, "b": 2}') == fingerprint("get", '{"b":2,"a":1}')
    assert fingerprint("get", '{"path": "a"}') != fingerprint("get", '{"path": "b"}')
    assert fingerprint("get", "{broken") == "get:{broken"


async def test_the_prompt_does_not_grow_by_everything_every_tool_returned() -> None:
    answers = [_asks((f"c{n}", "weather", json.dumps({"n": n}))) for n in range(6)]
    script = Scripted(*answers, OK)
    await _run(script, Tool("weather", "", WEATHER, Recorder("z" * 8000)))
    sizes = [
        sum(len(str(m.get("content") or "")) for m in call["messages"]) for call in script.calls
    ]
    # without shortening the prompt grows by 8000 characters a turn; once the last two rounds are in full, older results count 1500
    assert all(b - a < 1700 for a, b in pairwise(sizes[3:])), sizes
    assert sizes[-1] < sizes[1] * 4, sizes


# ── calls that repeat ────────────────────────────────────────────────


async def test_the_same_call_again_and_again_gets_a_note_the_step_does_not_keep() -> None:
    same = [_asks((f"c{n}", "weather", '{"city": "Bonn"}')) for n in range(REPEAT_HINT_AFTER)]
    script = Scripted(*same, OK)
    result = await _run(script)
    last_seen = [m["content"] for m in script.calls[-1]["messages"] if m["role"] == "tool"]
    assert "same call with the same arguments" not in last_seen[0]
    assert "same call with the same arguments" in last_seen[-1]
    stored = [c["result"] for t in result.detail["turns"] for c in t["tool_calls"]]
    assert all("same call" not in r for r in stored), "the protocol keeps what the tool returned"


async def test_different_arguments_are_no_repetition() -> None:
    script = Scripted(
        *[_asks((f"c{n}", "weather", json.dumps({"city": f"C{n}"}))) for n in range(5)], OK
    )
    await _run(script)
    assert all(
        "same call" not in m["content"] for m in script.calls[-1]["messages"] if m["role"] == "tool"
    )


async def test_a_run_that_makes_no_progress_is_asked_to_answer() -> None:
    same = [_asks((f"c{n}", "weather", '{"city": "Bonn"}')) for n in range(STALL_AFTER)]
    script = Scripted(*same, OK)
    result = await _run(script)
    assert (result.outcome, result.output) == ("pass", "Fine")
    assert "no progress" in result.reason and len(script.calls) == STALL_AFTER + 1


# ── a tool that does not answer ──────────────────────────────────────


async def test_a_tool_that_hangs_becomes_an_error_for_the_model_and_the_run_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("openartifact.agents.loop.TOOL_CALL_SECONDS", 0.2)
    script = Scripted(_asks(("c1", "weather", "{}")), OK)
    result = await _run(
        script, Tool("weather", "", WEATHER, Recorder(5.0)), total_timeout_seconds=600
    )
    assert (result.outcome, result.output) == ("pass", "Fine")
    assert result.reason is None, "the time limit of the node was not reached"
    answers = [m["content"] for m in script.calls[1]["messages"] if m["role"] == "tool"]
    assert answers == ["Error: the tool weather did not answer within 1 s"]


# ── a request after a timeout gets more time ─────────────────────────


async def test_after_a_timeout_the_next_attempt_may_take_longer() -> None:
    script = Scripted(
        60.0, 60.0, OK
    )  # the first two requests do not answer in time (slept over the limit)
    seen: list[float] = []
    original = script.complete

    async def spy(endpoint: Any, model: str, messages: Any, **more: Any) -> Completion:
        seen.append(more["timeout"])
        return await original(endpoint, model, messages, **more)

    outcome = await run_completion(
        ENDPOINT,
        "m",
        [{"role": "user", "content": "x"}],
        request_timeout=0.05,
        total_timeout=100,
        retries=2,
        complete=spy,
        sleep=script.sleep,
    )
    assert outcome.completion is not None
    assert (
        seen[0] == 0.05
        and seen[1] == pytest.approx(0.05 * TIMEOUT_GROWTH)
        and seen[2] == pytest.approx(0.05 * TIMEOUT_GROWTH**2)
    )
    assert ATTEMPT_TIMEOUT_CAP == 300.0


async def test_a_failure_that_is_no_timeout_keeps_the_limit() -> None:
    script = Scripted(_transient(503), OK)
    seen: list[float] = []
    original = script.complete

    async def spy(endpoint: Any, model: str, messages: Any, **more: Any) -> Completion:
        seen.append(more["timeout"])
        return await original(endpoint, model, messages, **more)

    await run_completion(
        ENDPOINT,
        "m",
        [{"role": "user", "content": "x"}],
        request_timeout=7,
        retries=1,
        complete=spy,
        sleep=script.sleep,
    )
    assert seen == [7, 7]


# ── what the engine tells while it runs ──────────────────────────────


async def test_the_turns_and_the_calls_are_told_with_names_counts_and_states_only() -> None:
    events: list[Any] = []
    script = Scripted(_asks(("c1", "weather", '{"city": "Secretville"}')), OK)
    await _run(
        script,
        Tool("weather", "", WEATHER, Recorder("SECRET-RESULT"), node_id="t1", node_name="T1"),
        events,
    )
    kinds = [(e, d.get("state")) for e, d in events]
    assert kinds == [
        ("turn", "started"),
        ("turn", "finished"),
        ("tool_call", "started"),
        ("tool_call", "finished"),
        ("turn", "started"),
        ("turn", "finished"),
    ]
    first_done = events[1][1]
    assert first_done["turn"] == 1 and first_done["tool_calls"] == 1 and first_done["tokens"] == 4
    assert events[2][1]["turn"] == 1 and events[2][1]["tool_node_id"] == "t1"
    assert events[-1][1]["text"] == "Fine" and events[-1][1]["total_tokens"] == 11
    assert "Secretville" not in repr(events) and "SECRET-RESULT" not in repr(events)


async def test_the_final_request_is_told_with_its_reason() -> None:
    events: list[Any] = []
    script = Scripted(_asks(("c1", "weather", "{}")), _asks(("c2", "weather", "{}")), OK)
    await _run(script, events=events, max_iterations=2)
    started = [d for e, d in events if e == "turn" and d["state"] == "started"]
    assert [d.get("wrap_up") for d in started] == [None, None, "the limit of 2 iterations"]


def test_the_limits_are_a_loose_safety_net() -> None:
    from openartifact.agents.schemas import (
        ITERATIONS_DEFAULT,
        ITERATIONS_MAX,
        TOKEN_BUDGET_MIN,
        TOOL_RESULT_DEFAULT,
        TOTAL_TIMEOUT_DEFAULT,
        TOTAL_TIMEOUT_MAX,
    )

    assert (ITERATIONS_DEFAULT, ITERATIONS_MAX) == (100, 500)
    assert (TOTAL_TIMEOUT_DEFAULT, TOTAL_TIMEOUT_MAX) == (900, 1800)
    assert AgentConfig().token_budget is None and AgentConfig().tool_result_chars is None
    assert (TOKEN_BUDGET_MIN, TOOL_RESULT_DEFAULT) == (1000, 12000)
    with pytest.raises(ValueError, match="token_budget"):
        AgentConfig(token_budget=999)
    with pytest.raises(ValueError, match="tool_result_chars"):
        AgentConfig(tool_result_chars=499)
