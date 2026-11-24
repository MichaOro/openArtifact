"""The guards of one execution (ADR-060), without an engine: counters, escalation, for/cooldown, the cap, fail open."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from openartifact.guards import monitor as monitor_module
from openartifact.guards.monitor import Count, GuardSettings, Monitor, Verdict, due
from openartifact.guards.schemas import EscalationStep


def _guard(
    *,
    events: list[str] | None = None,
    interval: dict[str, Any] | None = None,
    when: list[dict[str, Any]] | None = None,
    consequence: str = "continue",
    escalation: list[dict[str, Any]] | None = None,
    scope: tuple[str, str] = ("stage", "S"),
    fallback: str = "pause",
    ident: str = "g1",
) -> dict[str, Any]:
    trigger = {"type": "interval", **interval} if interval else {"type": "event", "events": events}
    return {
        "id": ident,
        "name": "Round guard",
        "scope_type": scope[0],
        "scope_id": scope[1],
        "trigger": trigger,
        "when": {"type": "group", "mode": "all", "items": when or [_at_least("runs", 1)]},
        "consequence": consequence,
        "fallback": fallback,
        "escalation": escalation or [],
        "definition_id": "body",
    }


def _at_least(field: str, value: int) -> dict[str, Any]:
    return {"type": "condition", "field": field, "op": "at_least", "value": value}


class Hooks:
    def __init__(self, body: Any = None) -> None:
        self.firings: list[dict[str, Any]] = []
        self.states: list[str] = []
        self.interrupted: list[Verdict] = []
        self.body = body

    async def run_body(
        self, guard: Mapping[str, Any], facts: Mapping[str, Any]
    ) -> tuple[bool, str]:
        return await self.body(facts)

    async def interrupt(self, verdict: Verdict) -> None:
        self.interrupted.append(verdict)

    async def fired(self, firing: Mapping[str, Any], state: str) -> None:
        self.firings.append(dict(firing))

    async def persist(self, state: str) -> None:
        self.states.append(state)


class Clock:
    def __init__(self) -> None:
        self.at = datetime(2026, 11, 24, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.at

    def tick(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(monitor_module, "now", fake)
    return fake


async def _rounds(monitor: Monitor, n: int) -> list[int]:
    """Enter stage S n times (a loop back to its entry action); the rounds a guard fired at."""
    fired_at = []
    for round_ in range(1, n + 1):
        before = len(monitor.firings)
        await monitor.enter("stage", "S", "Stage")
        if len(monitor.firings) > before:
            fired_at.append(round_)
    return fired_at


def test_the_escalation_table_fires_at_round_5_and_then_every_3_rounds() -> None:
    steps = [
        {"from_firing": 1, "every_runs": 5},
        {"from_firing": 2, "every_runs": 3},
    ]
    monitor = Monitor([_guard(events=["enter"], escalation=steps)], Hooks())
    assert asyncio.run(_rounds(monitor, 12)) == [5, 8, 11]
    assert [f["facts"]["guard.runs"] for f in monitor.firings] == [1, 2, 3]
    assert monitor.firings[0]["summary"].startswith("round 5")


def test_a_step_in_seconds_counts_from_the_last_firing(clock: Clock) -> None:
    steps = [EscalationStep(from_firing=1, every_seconds=60)]
    entered = clock()
    count = Count()
    assert not due(steps, count, 1, entered + timedelta(seconds=59), entered)
    assert due(steps, count, 1, entered + timedelta(seconds=60), entered)
    count.runs, count.last_fired_at = 1, entered + timedelta(seconds=60)
    assert not due(steps, count, 9, entered + timedelta(seconds=100), entered)


def test_counters_are_never_reset_and_are_persisted_per_scope_and_guard() -> None:
    hooks = Hooks()
    monitor = Monitor([_guard(events=["error"])], hooks)

    async def go() -> None:
        await monitor.enter("pipeline", "P", "Pipeline")
        for passed in (True, False, False):
            await monitor.enter("stage", "S", "Stage")
            await monitor.enter("action", "A", "Action")
            await monitor.ended("A", passed)
            await monitor.leave("action", "A")
        await monitor.leave("stage", "S")

    asyncio.run(go())
    state = json.loads(hooks.states[-1])
    stage = state["scopes"]["|stage:S"]
    assert (stage["runs"], stage["passes"], stage["errors"], stage["active"]) == (3, 1, 2, False)
    assert state["scopes"]["|pipeline:P"]["errors"] == 2  # the pipeline counts what its actions did
    assert state["scopes"]["|action:A"]["runs"] == 3
    assert state["guards"]["g1||stage:S"]["runs"] == 2  # fired on each error


def test_pause_and_abort_are_verdicts_with_the_reason_and_continue_is_none() -> None:
    for consequence, kind in (("pause", "pause"), ("abort", "abort"), ("continue", "continue")):
        monitor = Monitor([_guard(events=["enter"], consequence=consequence)], Hooks())
        verdict = asyncio.run(monitor.enter("stage", "S", "Stage"))
        assert verdict.kind == kind
        if kind != "continue":
            assert "Round guard fired at Stage: round 1" in verdict.note


def test_the_guards_action_continues_on_pass_and_does_the_fallback_on_error() -> None:
    async def body(facts: Mapping[str, Any]) -> tuple[bool, str]:
        return facts["guard.runs"] < 2, "judged"

    monitor = Monitor(
        [_guard(events=["enter"], consequence="run_action", fallback="abort")], Hooks(body)
    )
    first = asyncio.run(monitor.enter("stage", "S", "Stage"))
    second = asyncio.run(monitor.enter("stage", "S", "Stage"))
    assert (first.kind, second.kind) == ("continue", "abort")
    assert monitor.firings[1]["detail"] == "its action failed: judged; abort"


def test_a_guard_that_raises_or_does_not_answer_fails_open_and_is_recorded() -> None:
    async def broken(facts: Mapping[str, Any]) -> tuple[bool, str]:
        raise RuntimeError("the body blew up")

    async def slow(facts: Mapping[str, Any]) -> tuple[bool, str]:
        await asyncio.sleep(5)
        return False, ""

    for body, reason in (
        (broken, "RuntimeError: the body blew up"),
        (slow, "no answer within 0.05 s"),
    ):
        settings = GuardSettings(timeout_seconds=0.05)
        monitor = Monitor(
            [_guard(events=["enter"], consequence="run_action")], Hooks(body), settings
        )
        verdict = asyncio.run(monitor.enter("stage", "S", "Stage"))
        assert verdict.kind == "continue"  # the flow goes on
        assert monitor.firings[-1]["outcome"] == "failed"
        assert reason in monitor.firings[-1]["detail"]


def test_the_cap_stops_a_guard_from_firing_and_says_so_once() -> None:
    monitor = Monitor([_guard(events=["enter"])], Hooks(), GuardSettings(max_firings=3))
    assert asyncio.run(_rounds(monitor, 10)) == [1, 2, 3, 4]  # the 4th round records the cap, once
    assert [f["outcome"] for f in monitor.firings] == ["continue"] * 3 + ["capped"]
    assert "cap of 3 firings" in monitor.firings[-1]["detail"]


def test_a_switched_off_guard_does_not_fire_and_an_unavailable_consequence_never_stops() -> None:
    async def off(guard_id: str) -> bool:
        return False

    monitor = Monitor([_guard(events=["enter"], consequence="pause")], Hooks(), enabled=off)
    assert asyncio.run(_rounds(monitor, 3)) == []
    notify = Monitor([_guard(events=["enter"], consequence="notify")], Hooks())
    assert asyncio.run(notify.enter("stage", "S", "Stage")).kind == "continue"
    assert notify.firings[0]["outcome"] == "unavailable"


def test_facts_include_numeric_result_fields_and_a_missing_one_never_fires() -> None:
    when = [{"type": "condition", "field": "var.gain", "op": "below", "value": 0.05}]
    variables = {"gain": "0.01", "label": "text"}
    monitor = Monitor([_guard(events=["enter"], when=when)], Hooks(), variables=lambda: variables)
    asyncio.run(monitor.enter("stage", "S", "Stage"))
    assert monitor.firings[0]["facts"]["var.gain"] == 0.01
    assert "var.label" not in monitor.firings[0]["facts"]
    variables.clear()
    assert asyncio.run(_rounds(monitor, 2)) == []


def test_an_interval_guard_fires_after_for_respects_cooldown_and_interrupts(
    clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_sleep = asyncio.sleep
    monkeypatch.setattr(monitor_module, "sleep", lambda seconds: real_sleep(0.01))

    async def watch(consequence: str) -> Hooks:
        trigger = {"every_seconds": 1, "for_seconds": 2, "cooldown_seconds": 100}
        guard = _guard(interval=trigger, when=[_at_least("idle", 1)], consequence=consequence)
        hooks = Hooks()
        monitor = Monitor([guard], hooks, GuardSettings(min_interval_seconds=1))
        await monitor.enter("stage", "S", "Stage")
        for _ in range(8):  # each check sees one more second without progress
            clock.tick(1)
            await real_sleep(0.04)
        await monitor.close()
        return hooks

    recorded = asyncio.run(watch("continue"))
    assert len(recorded.firings) == 1  # held for 2 s, then the cooldown keeps it quiet
    assert recorded.firings[0]["facts"]["idle"] >= 3  # first held at 1 s, fired 2 s later
    assert recorded.interrupted == []
    aborted = asyncio.run(watch("abort"))
    assert [v.kind for v in aborted.interrupted] == ["abort"]


def test_progress_and_a_heartbeat_restart_the_stall_clock(clock: Clock) -> None:
    monitor = Monitor([], Hooks())
    asyncio.run(monitor.enter("stage", "S", "Stage"))
    clock.tick(50)
    scope = monitor.scopes["|stage:S"]
    assert monitor.facts(scope)["idle"] == 50
    monitor.progress("still thinking", heartbeat=True)
    clock.tick(5)
    assert monitor.facts(scope)["idle"] == 5
    assert monitor.heartbeat == {
        "at": (clock() - timedelta(seconds=5)).isoformat(),
        "note": "still thinking",
        "count": 1,
    }
