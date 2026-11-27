"""The facts a guard can test about an agent (ADR-060 addendum, card #103): rounds, tool calls, failures, the same call again and again,
tokens, quiet time, and the artifacts in a lane. The examples are the owner's: five minutes without activity is unhealthy, ten times the
same README is unhealthy, ten visits to ten different websites are not, and a pipeline that runs while the backlog is empty is."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from openartifact.agents.tools import args_key
from openartifact.engine.telemetry import MAX_CALLS, MAX_EXECUTIONS, Telemetry
from openartifact.guards.monitor import Monitor
from openartifact.guards.schemas import GuardCondition, GuardGroup
from openartifact.rules import catalog, tree
from tests.test_guard_monitor import Hooks, _guard


class Clock:
    def __init__(self) -> None:
        self.at = datetime(2026, 11, 25, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.at

    def tick(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)


def _call(
    tele: Telemetry, tool: str, arguments: str, ok: bool = True, execution: str = "e1"
) -> None:
    base = {
        "execution_id": execution,
        "tool": tool,
        "args_key": args_key(arguments),
        "tool_node_id": "n",
        "tool_node_name": "Tool",
    }
    tele.record("agent.tool_call", {"state": "started", **base})
    tele.record("agent.tool_call", {"state": "finished", **base, "ok": ok, "duration_ms": 5})


def _turn(tele: Telemetry, total: int, execution: str = "e1") -> None:
    tele.record("agent.turn", {"execution_id": execution, "state": "started", "turn": 1})
    tele.record(
        "agent.turn",
        {
            "execution_id": execution,
            "state": "finished",
            "turn": 1,
            "tokens": 100,
            "total_tokens": total,
        },
    )


# ── the arguments are told apart by a fingerprint, never kept ────────


def test_the_same_arguments_have_the_same_key_whatever_the_order_or_the_spaces_and_others_differ() -> (
    None
):
    assert (
        args_key('{"a": 1, "b": "x"}')
        == args_key('{"b":"x","a":1}')
        == args_key('  {"a":1,"b":"x"}')
    )
    assert args_key('{"path": "README.md"}') != args_key('{"path": "docs/a.md"}')
    assert len(args_key("{}")) == 12 and "README" not in args_key('{"path": "README.md"}')
    assert args_key("not json") == args_key(
        " not json "
    )  # text that is no JSON is told apart as it is


# ── the telemetry of an execution ────────────────────────────────────


def test_an_execution_without_an_agent_has_no_agent_facts_and_a_condition_on_one_never_holds() -> (
    None
):
    tele = Telemetry(Clock())
    assert tele.facts("e1") == {} and tele.facts(None) == {}
    when = GuardGroup.model_validate(
        {
            "type": "group",
            "mode": "all",
            "items": [{"type": "condition", "field": "agent.idle", "op": "at_least", "value": 0}],
        }
    )
    assert tree.evaluate(when, tele.facts("e1")) is False


def test_the_numbers_of_an_agent_run_are_counted_as_it_goes() -> None:
    clock = Clock()
    tele = Telemetry(clock)
    _turn(tele, 120)
    _call(tele, "get_file", '{"path": "a"}')
    clock.tick(30)
    _call(tele, "get_file", '{"path": "b"}', ok=False)
    _turn(tele, 400)
    facts = tele.facts("e1")
    assert (
        facts["agent.turns"] == 2
        and facts["agent.tool_calls"] == 2
        and facts["agent.tool_errors"] == 1
    )
    assert facts["agent.tokens"] == 400, "the step's total so far, not a sum of sums"
    assert facts["agent.idle"] == 0 and facts["agent.since_tool_call"] == 0
    clock.tick(300)
    facts = tele.facts("e1")
    assert facts["agent.idle"] == 300 and facts["agent.since_tool_call"] == 300, (
        "five minutes of quiet"
    )


def test_the_same_call_again_and_again_is_a_storm_and_the_same_tool_for_other_things_is_work() -> (
    None
):
    tele = Telemetry(Clock())
    for _ in range(10):
        _call(tele, "get_file_contents", '{"path": "README.md"}')
    facts = tele.facts("e1")
    assert (facts["agent.repeat"], facts["agent.same_tool"]) == (10, 10), (
        "ten times the same README"
    )
    other = Telemetry(Clock())
    for site in (
        "telekom.de",
        "commerzbank.de",
        "allianz.de",
        "linkedin.com",
        "xing.com",
        "a.de",
        "b.de",
        "c.de",
        "d.de",
        "e.de",
    ):
        _call(other, "http_request", f'{{"url": "https://{site}"}}')
    facts = other.facts("e1")
    assert (facts["agent.repeat"], facts["agent.same_tool"]) == (1, 10), (
        "ten different websites: one tool, ten different calls"
    )


def test_a_streak_ends_with_another_tool_and_counts_from_the_end() -> None:
    tele = Telemetry(Clock())
    for _ in range(4):
        _call(tele, "list_issues", '{"state": "open"}')
    _call(tele, "get_issue", '{"n": 1}')
    for _ in range(2):
        _call(tele, "list_issues", '{"state": "open"}')
    assert (tele.facts("e1")["agent.repeat"], tele.facts("e1")["agent.same_tool"]) == (2, 2)


def test_the_telemetry_is_per_execution_and_bounded() -> None:
    tele = Telemetry(Clock())
    _call(tele, "t", "{}", execution="a")
    _call(tele, "t", "{}", execution="b")
    _call(tele, "t", "{}", execution="b")
    assert (tele.facts("a")["agent.tool_calls"], tele.facts("b")["agent.tool_calls"]) == (1, 2)
    for number in range(MAX_EXECUTIONS + 5):
        _call(tele, "t", "{}", execution=f"x{number}")
    assert tele.facts("a") == {}, "the oldest executions are forgotten"
    for _ in range(MAX_CALLS + 50):
        _call(tele, "t", "{}", execution="long")
    assert tele.facts("long")["agent.tool_calls"] == MAX_CALLS + 50, (
        "the count goes on, the list of calls that tell a streak is bounded"
    )
    tele.forget("long")
    assert tele.facts("long") == {}


def test_only_agent_events_of_an_execution_count() -> None:
    tele = Telemetry(Clock())
    tele.record("guard.fired", {"execution_id": "e1"})
    tele.record("agent.turn", {"state": "started"})  # no execution
    assert tele.facts("e1") == {}


# ── in the rule system ───────────────────────────────────────────────


def _group(mode: str, *items: dict[str, Any]) -> GuardGroup:
    return GuardGroup.model_validate({"type": "group", "mode": mode, "items": list(items)})


def _c(field: str, op: str, value: Any) -> dict[str, Any]:
    return {"type": "condition", "field": field, "op": op, "value": value}


def test_the_new_fields_are_in_the_schema_with_labels_and_a_lane_is_named_like_a_result_field() -> (
    None
):
    keys = {f.key for f in catalog.GUARD.fields}
    assert {
        "agent.turns",
        "agent.tool_calls",
        "agent.tool_errors",
        "agent.repeat",
        "agent.same_tool",
        "agent.tokens",
        "agent.idle",
        "agent.since_tool_call",
        "lane.",
    } <= keys
    assert catalog.GUARD.field_for("lane.in_progress") is not None
    for field, op, value in (
        ("agent.repeat", "at_least", 10),
        ("agent.idle", "at_least", 300),
        ("lane.backlog", "equals", 0),
    ):
        catalog.GUARD.check(
            GuardCondition.model_validate(_c(field, op, value))
        )  # a valid condition raises nothing
    with pytest.raises(ValueError, match=r"name a result field|unknown field"):
        catalog.GUARD.check(GuardCondition.model_validate(_c("lane.Backlog Lane", "equals", 0)))


def test_combined_conditions_say_unhealthy_for_a_storm_or_quiet_or_an_empty_backlog() -> None:
    unhealthy = _group(
        "any",
        _c("agent.repeat", "at_least", 10),
        _c("agent.idle", "at_least", 300),
        _c("lane.backlog", "equals", 0),
    )
    assert not tree.evaluate(unhealthy, {"agent.repeat": 3, "agent.idle": 20, "lane.backlog": 4})
    assert tree.evaluate(unhealthy, {"agent.repeat": 10, "agent.idle": 20, "lane.backlog": 4})
    assert tree.evaluate(unhealthy, {"agent.repeat": 1, "agent.idle": 301, "lane.backlog": 4})
    assert tree.evaluate(unhealthy, {"agent.repeat": 1, "agent.idle": 20, "lane.backlog": 0}), (
        "the pipeline runs but the backlog is empty"
    )
    both = _group(
        "all", _c("agent.tool_calls", "at_least", 20), _c("agent.tool_errors", "at_least", 5)
    )
    assert not tree.evaluate(both, {"agent.tool_calls": 30, "agent.tool_errors": 1})
    assert tree.evaluate(both, {"agent.tool_calls": 30, "agent.tool_errors": 6})


# ── in the monitor of an execution ───────────────────────────────────


def _watching(
    agent_facts: dict[str, Any], lanes: dict[str, int] | None = None, **when: Any
) -> tuple[Monitor, Hooks, list[int]]:
    asked: list[int] = []

    async def board() -> dict[str, int]:
        asked.append(1)
        return {f"lane.{k}": v for k, v in (lanes or {}).items()}

    hooks = Hooks()
    guard = _guard(
        events=["enter"], when=when.get("items"), consequence="continue", scope=("stage", "S")
    )
    return Monitor([guard], hooks, agent=lambda: agent_facts, board=board), hooks, asked


def test_a_guard_fires_on_what_the_agent_does_and_says_so_in_its_reason() -> None:
    monitor, _hooks, _ = _watching(
        {"agent.repeat": 10, "agent.idle": 400, "agent.tool_errors": 2},
        items=[_c("agent.repeat", "at_least", 10)],
    )
    asyncio.run(monitor.enter("stage", "S", "Stage"))
    (firing,) = monitor.firings
    assert firing["facts"]["agent.repeat"] == 10
    assert (
        "the same tool call 10 times in a row" in firing["summary"]
        and "agent quiet for 7 min" in firing["summary"]
    )
    assert "2 failed tool calls" in firing["summary"]
    quiet, _, _ = _watching({"agent.repeat": 2}, items=[_c("agent.repeat", "at_least", 10)])
    asyncio.run(quiet.enter("stage", "S", "Stage"))
    assert quiet.firings == []


def test_the_board_is_looked_up_only_when_a_condition_names_a_lane() -> None:
    monitor, _, asked = _watching({}, {"backlog": 0}, items=[_c("runs", "at_least", 1)])
    asyncio.run(monitor.enter("stage", "S", "Stage"))
    assert asked == [], "no lane in the condition: no look at the board"
    monitor, _, asked = _watching(
        {}, {"backlog": 0, "in_progress": 3}, items=[_c("lane.backlog", "equals", 0)]
    )
    asyncio.run(monitor.enter("stage", "S", "Stage"))
    assert (
        asked == [1]
        and len(monitor.firings) == 1
        and monitor.firings[0]["facts"]["lane.backlog"] == 0
    )
    full, _, _ = _watching({}, {"backlog": 5}, items=[_c("lane.backlog", "equals", 0)])
    asyncio.run(full.enter("stage", "S", "Stage"))
    assert full.firings == [], "a pipeline with something in its backlog is healthy"


# ── a guard on the facts of an agent ────────────────────────────


def test_a_guard_on_the_quiet_and_storm_facts_is_rules_only(client: Any) -> None:
    """The facts of an agent (idle, repeat) are usable in a definition made directly: the conditions of the removed 'Agent quiet and
    storm' template, five minutes of quiet or the same call ten times."""
    from tests.helpers import post

    quiet = post(
        client,
        "/api/guards",
        name="Agent quiet and storm guard",
        scope_types=["action", "stage", "pipeline", "definition", "node"],
        trigger={
            "type": "interval",
            "every_seconds": 60,
            "for_seconds": 0,
            "cooldown_seconds": 600,
        },
        when={
            "type": "group",
            "mode": "any",
            "items": [
                {"type": "condition", "field": "agent.idle", "op": "at_least", "value": 300},
                {"type": "condition", "field": "agent.repeat", "op": "at_least", "value": 10},
            ],
        },
        consequence="pause",
        fallback="pause",
        escalation=[],
    )
    assert quiet["consequence"] == "pause" and quiet["action_id"] is None
    fields = {i["field"] for i in quiet["when"]["items"]}
    assert quiet["when"]["mode"] == "any" and fields == {"agent.idle", "agent.repeat"}
    idle = next(i for i in quiet["when"]["items"] if i["field"] == "agent.idle")
    assert idle["value"] == 300, "five minutes"
