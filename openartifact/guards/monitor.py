"""The guards of one running execution (ADR-060): counters per scope, watches, verdicts.

The engine tells the monitor where the flow is: a scope is *entered* (a pipeline after its trigger, a stage before its
entry action, again every time a loop brings the flow back to that action, an action before it runs, the definition
of that action and each execution node inside it before it runs), an action or a node *ends* (On Pass or On Error), a
scope is *left*, the run *fails*. Every step the engine records and every heartbeat
is *progress*. From that the monitor keeps, per scope instance and per run, the counters (``runs``: entries,
``passes``, ``errors``, the last action's status, when it was entered) and per guard on it its own (``guard.runs``:
times it fired, when and at which round it fired last). The counters are never reset within a run; a called
pipeline counts per call (its scopes are keyed by the path of pipeline nodes that leads to it); the scopes of an action
definition (``definition``, ``node``) are keyed by the path *and* the action node that runs it, so the same definition
in two stages, and the same node in two executions of a loop, count apart.

Two kinds of trigger:

- **event**: evaluated in the flow, which waits for the verdict (``continue``, ``pause`` or ``abort``);
- **interval**: a watch (an ``asyncio`` task) registered when the scope is entered and cancelled when it is left;
  it checks every ``every_seconds`` (at least the minimum interval of the settings) while the action keeps running,
  fires once the condition has held for ``for_seconds`` and not within ``cooldown_seconds`` of its last firing, and
  interrupts the run through the engine for ``pause`` and ``abort``.

A guard fires only when its condition holds, its escalation step says it is due, it is enabled and it has not reached
the cap of firings per scope and run. A guard that raises or does not answer in time is recorded as failed and the
flow goes on (fail open). The guard's own action runs as a child of the run: it is not watched by any guard, its
steps are not progress of the run and not steps of the execution.

The engine provides the effects through :class:`Hooks`; the monitor holds no database session.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from openartifact.guards.schemas import EscalationStep, GuardGroup
from openartifact.rules import tree

logger = logging.getLogger(__name__)

#: Firings kept in the run's guard state (the activity keeps them too).
MAX_FIRINGS_KEPT = 100
#: Characters of a reason kept with a firing.
SHORT_REASON = 300


def now() -> datetime:
    """The monitor's clock (one place, so a test can move it)."""
    return datetime.now(UTC)


async def sleep(seconds: float) -> None:
    """How a watch waits between its checks (one place, so a test can make it short)."""
    await asyncio.sleep(seconds)


@dataclass(frozen=True)
class GuardSettings:
    """Limits of the guards (``OPENARTIFACT_GUARD_*``)."""

    min_interval_seconds: float = 30
    max_firings: int = 20
    timeout_seconds: float = 600
    heartbeat_spacing_seconds: float = 1.0


@dataclass(frozen=True)
class Verdict:
    """What the flow does after the guards of an event: ``continue``, ``pause`` or ``abort`` (with the reason)."""

    kind: str = "continue"
    note: str = ""

    @property
    def stops(self) -> bool:
        return self.kind in ("pause", "abort")


CONTINUE = Verdict()


class Hooks(Protocol):
    """What the engine does for the monitor."""

    async def run_body(
        self, guard: Mapping[str, Any], facts: Mapping[str, Any]
    ) -> tuple[bool, str]:
        """Run the guard's own action with the facts as inputs: (passed, reason)."""
        ...

    async def interrupt(self, verdict: Verdict) -> None:
        """Stop the run from outside the flow (an interval guard paused or aborted it)."""
        ...

    async def fired(self, firing: Mapping[str, Any], state: str) -> None:
        """Record a firing (activity entry, the run's guard state) and publish it."""
        ...

    async def persist(self, state: str) -> None:
        """Store the guard state of the run (counters) with the execution."""
        ...


@dataclass
class Scope:
    key: str
    type: str
    id: str
    name: str
    entered_at: datetime
    #: For a node: the name of the action it is in (a firing says "node X of action Y").
    parent: str = ""
    runs: int = 0
    passes: int = 0
    errors: int = 0
    last_status: str = "none"
    cost: float = 0.0
    active: bool = True

    @property
    def label(self) -> str:
        """How a firing names the scope."""
        if self.type == "node":
            return (
                f"node '{self.name}' of action '{self.parent}'"
                if self.parent
                else f"node '{self.name}'"
            )
        return self.name

    def dump(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "name": self.name,
            "parent": self.parent,
            "runs": self.runs,
            "passes": self.passes,
            "errors": self.errors,
            "last_status": self.last_status,
            "entered_at": self.entered_at.isoformat(),
            "active": self.active,
        }


@dataclass
class Count:
    """A guard's own counter on one scope instance."""

    runs: int = 0
    last_fired_runs: int = 0
    last_fired_at: datetime | None = None
    holding_since: datetime | None = None
    capped: bool = False

    def dump(self) -> dict[str, Any]:
        return {
            "runs": self.runs,
            "last_fired_runs": self.last_fired_runs,
            "last_fired_at": self.last_fired_at.isoformat() if self.last_fired_at else None,
            "capped": self.capped,
        }


def due(
    steps: list[EscalationStep], count: Count, runs: int, at: datetime, entered: datetime
) -> bool:
    """Whether the escalation table lets the guard fire now: the step that applies to its next firing (the last
    whose ``from_firing`` it has reached) says every N rounds or every N seconds, counted from its last firing (or
    from the entry of the scope before the first). No step: whenever the condition holds."""
    firing = count.runs + 1
    step = next((s for s in reversed(steps) if s.from_firing <= firing), None)
    if step is None:
        return True
    if step.every_runs is not None:
        return runs - count.last_fired_runs >= step.every_runs
    since = count.last_fired_at or entered
    return (at - since).total_seconds() >= (step.every_seconds or 0)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def describe_facts(facts: Mapping[str, Any]) -> str:
    """The facts a firing is explained by, in a few words ("round 10, 14 min without progress")."""
    parts = [f"round {facts.get('runs', 0)}"]
    for key, words in (("idle", "without progress"), ("elapsed", "in the scope")):
        seconds = facts.get(key)
        if isinstance(seconds, int | float) and seconds >= 1:
            amount = f"{round(seconds / 60)} min" if seconds >= 120 else f"{int(seconds)} s"
            parts.append(f"{amount} {words}")
    if facts.get("errors"):
        parts.append(f"{facts['errors']} errors")
    return ", ".join(parts)


@dataclass
class _Guard:
    data: dict[str, Any]
    when: GuardGroup
    steps: list[EscalationStep]

    @property
    def id(self) -> str:
        return str(self.data["id"])

    @property
    def name(self) -> str:
        return str(self.data["name"])

    @property
    def trigger(self) -> dict[str, Any]:
        return dict(self.data["trigger"])


@dataclass
class Monitor:
    """The guards of one execution."""

    guards: list[dict[str, Any]]
    hooks: Hooks
    settings: GuardSettings = field(default_factory=GuardSettings)
    #: The variables of the run (``var.NAME`` facts), read when a guard evaluates.
    variables: Callable[[], Mapping[str, Any]] = dict
    #: Whether a guard is still enabled (checked live, so switching one off acts on running executions).
    enabled: Callable[[str], Awaitable[bool]] | None = None

    def __post_init__(self) -> None:
        self._guards: list[_Guard] = []
        for data in self.guards:
            try:
                self._guards.append(
                    _Guard(
                        data,
                        GuardGroup.model_validate(data["when"]),
                        [EscalationStep.model_validate(s) for s in data.get("escalation", [])],
                    )
                )
            except (ValueError, KeyError):
                logger.warning("Guard %s is not valid and does not watch", data.get("id"))
        self.scopes: dict[str, Scope] = {}
        self.counts: dict[str, Count] = {}
        self.firings: list[dict[str, Any]] = []
        self.progress_at = now()
        self.heartbeat: dict[str, Any] | None = None
        self._watches: dict[str, list[asyncio.Task[None]]] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def watching(self) -> bool:
        return bool(self._guards)

    # ── state ────────────────────────────────────────────────────────

    def dump(self) -> str:
        return json.dumps(
            {
                "scopes": {k: s.dump() for k, s in self.scopes.items()},
                "guards": {k: c.dump() for k, c in self.counts.items()},
                "progress_at": self.progress_at.isoformat(),
                "heartbeat": self.heartbeat,
                "firings": self.firings[-MAX_FIRINGS_KEPT:],
            }
        )

    async def _persist(self) -> None:
        if self.watching or self.heartbeat:
            await self.hooks.persist(self.dump())

    def facts(
        self, scope: Scope, guard: _Guard | None = None, at: datetime | None = None
    ) -> dict[str, Any]:
        """What a condition of a guard on ``scope`` can test, now."""
        at = at or now()
        since = max(self.progress_at, scope.entered_at)
        facts: dict[str, Any] = {
            "runs": scope.runs,
            "elapsed": int((at - scope.entered_at).total_seconds()),
            "idle": int((at - since).total_seconds()),
            "errors": scope.errors,
            "passes": scope.passes,
            "last_status": scope.last_status,
            "guard.runs": self.counts.get(self._count_key(guard, scope), Count()).runs
            if guard
            else 0,
        }
        if scope.cost:
            facts["cost"] = scope.cost
        for name, value in self.variables().items():
            number = _number(value)
            if number is not None:
                facts[f"var.{name}"] = number
        return facts

    @staticmethod
    def _count_key(guard: _Guard | None, scope: Scope) -> str:
        return f"{guard.id if guard else ''}|{scope.key}"

    def _on(self, scope: Scope) -> list[_Guard]:
        return [
            g
            for g in self._guards
            if g.data["scope_type"] == scope.type and g.data.get("scope_id") == scope.id
        ]

    def watches(self, kind: str, ident: str) -> bool:
        """Whether any guard is attached to this scope (the engine asks before it enters one of the scopes that only
        exist for their guards, so a node without a guard costs nothing)."""
        return any(
            g.data["scope_type"] == kind and g.data.get("scope_id") == ident for g in self._guards
        )

    def active(self) -> list[Scope]:
        return [s for s in self.scopes.values() if s.active]

    # ── what the engine reports ──────────────────────────────────────

    def progress(self, note: str | None = None, *, heartbeat: bool = False) -> None:
        """Something happened that counts as progress (a step, a heartbeat): the stall clock starts again."""
        self.progress_at = now()
        if heartbeat:
            count = (self.heartbeat or {}).get("count", 0) + 1
            self.heartbeat = {"at": self.progress_at.isoformat(), "note": note, "count": count}

    async def enter(
        self, kind: str, ident: str, name: str, path: str = "", parent: str = ""
    ) -> Verdict:
        """The flow enters a scope (again, for a loop back to a stage's entry action)."""
        key = f"{path}|{kind}:{ident}"
        scope = self.scopes.get(key)
        at = now()
        if scope is None or not scope.active:
            if scope is None:
                scope = self.scopes[key] = Scope(key, kind, ident, name, at, parent)
            scope.active, scope.entered_at = True, at
            self._watch(scope)
        scope.runs += 1
        verdict = await self._event(scope, "enter")
        await self._persist()
        return verdict

    async def ended(
        self, action_id: str, passed: bool, definition_id: str | None = None
    ) -> Verdict:
        """An action ended by On Pass or On Error: it, its definition and every scope around it count it; then their
        guards (the innermost first). The nodes inside it count themselves (:meth:`node_ended`)."""
        status = "pass" if passed else "error"
        touched = [
            s
            for s in self.active()
            if s.type in ("pipeline", "stage")
            or (s.type == "action" and s.id == action_id)
            or (s.type == "definition" and s.id == definition_id)
        ]
        for scope in touched:
            if passed:
                scope.passes += 1
            else:
                scope.errors += 1
            scope.last_status = status
        verdict = CONTINUE
        for scope in reversed(touched):  # the innermost first
            verdict = await self._event(scope, status)
            if verdict.stops:
                break
        await self._persist()
        return verdict

    async def node_ended(self, node_id: str, path: str, passed: bool) -> Verdict:
        """A node of an action definition ended (it passed, or it failed whatever its failure setting does with that):
        it counts it, then its guards hear it."""
        scope = self.scopes.get(f"{path}|node:{node_id}")
        if scope is None or not scope.active:
            return CONTINUE
        status = "pass" if passed else "error"
        if passed:
            scope.passes += 1
        else:
            scope.errors += 1
        scope.last_status = status
        verdict = await self._event(scope, status)
        await self._persist()
        return verdict

    def add_cost(self, cost: float) -> None:
        for scope in self.active():
            scope.cost += cost

    async def leave(self, kind: str, ident: str, path: str = "") -> Verdict:
        """The flow leaves a scope: its leave guards, then its watches end."""
        scope = self.scopes.get(f"{path}|{kind}:{ident}")
        if scope is None or not scope.active:
            return CONTINUE
        verdict = await self._event(scope, "leave")
        scope.active = False
        self._unwatch(scope)
        await self._persist()
        return verdict

    async def fail(self) -> None:
        """The run fails: the fail guards of every scope that is active (innermost first) are told; the run fails
        whatever they say."""
        for scope in reversed(self.active()):
            await self._event(scope, "fail")
        await self._persist()

    async def close(self) -> None:
        """The run is over: every watch ends."""
        self._closed = True
        for key in list(self._watches):
            for task in self._watches.pop(key):
                if task is not asyncio.current_task():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task

    # ── events ───────────────────────────────────────────────────────

    async def _event(self, scope: Scope, event: str) -> Verdict:
        for guard in self._on(scope):
            trigger = guard.trigger
            if trigger.get("type") != "event" or event not in trigger.get("events", []):
                continue
            verdict = await self._consider(guard, scope, event)
            if verdict.stops:
                return verdict
        return CONTINUE

    async def _consider(self, guard: _Guard, scope: Scope, event: str) -> Verdict:
        """Fire the guard if its condition holds and it is due; fail open. The counters are decided under a lock,
        the consequence runs outside it (an interval guard's action does not hold up the flow's events)."""
        async with self._lock:
            facts = await self._decide(guard, scope, event)
        if facts is None:
            return CONTINUE
        return await self._dispatch(guard, scope, event, facts)

    async def _decide(self, guard: _Guard, scope: Scope, event: str) -> dict[str, Any] | None:
        """The facts if the guard fires now (its counter already counts it), else ``None``."""
        at = now()
        count = self.counts.setdefault(self._count_key(guard, scope), Count())
        try:
            facts = self.facts(scope, guard, at)
            if not tree.evaluate(guard.when, facts):
                count.holding_since = None
                return None
            trigger = guard.trigger
            if trigger.get("type") == "interval":
                count.holding_since = count.holding_since or at
                if (at - count.holding_since).total_seconds() < trigger.get("for_seconds", 0):
                    return None
                cooldown = trigger.get("cooldown_seconds", 0)
                if count.last_fired_at and (at - count.last_fired_at).total_seconds() < cooldown:
                    return None
            if not due(guard.steps, count, scope.runs, at, scope.entered_at):
                return None
            if self.enabled is not None and not await self.enabled(guard.id):
                return None
            if count.runs >= self.settings.max_firings:
                if not count.capped:
                    count.capped = True
                    cap = f"the cap of {self.settings.max_firings} firings per scope and run is reached"
                    await self._record(guard, scope, event, facts, "capped", cap)
                return None
        except Exception as error:  # a guard that cannot be evaluated never stops the run
            logger.exception("Guard %s could not be evaluated", guard.id)
            await self._record(
                guard, scope, event, {}, "failed", f"{type(error).__name__}: {error}"
            )
            return None
        count.runs += 1
        count.last_fired_runs, count.last_fired_at = scope.runs, at
        facts["guard.runs"] = count.runs
        return facts

    async def _dispatch(
        self, guard: _Guard, scope: Scope, event: str, facts: dict[str, Any]
    ) -> Verdict:
        """Carry out the consequence: the one place they are dispatched (``CONSEQUENCES``)."""
        consequence = str(guard.data["consequence"])
        reason = f"{guard.name} fired at {scope.label}: {describe_facts(facts)}"
        handler = CONSEQUENCES.get(consequence)
        if handler is None:  # declared but not built (notify, handover): never stops the run
            await self._record(guard, scope, event, facts, "unavailable", consequence)
            return CONTINUE
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                verdict, body = await handler(self, guard, facts, reason)
        except TimeoutError:
            await self._record(
                guard,
                scope,
                event,
                facts,
                "failed",
                f"no answer within {self.settings.timeout_seconds:g} s; the flow went on",
            )
            return CONTINUE
        except Exception as error:
            logger.exception("Guard %s failed", guard.id)
            await self._record(
                guard, scope, event, facts, "failed", f"{type(error).__name__}: {error}"
            )
            return CONTINUE
        await self._record(guard, scope, event, facts, verdict.kind, body, verdict=verdict)
        return verdict

    async def _record(
        self,
        guard: _Guard,
        scope: Scope,
        event: str,
        facts: Mapping[str, Any],
        outcome: str,
        detail: str | None,
        *,
        verdict: Verdict | None = None,
    ) -> None:
        firing = {
            "at": now().isoformat(),
            "guard_id": guard.id,
            "guard": guard.name,
            "scope_type": scope.type,
            "scope_id": scope.id,
            "scope_name": scope.name,
            "scope_label": scope.label,
            "trigger": guard.trigger.get("type"),
            "event": event,
            "consequence": guard.data["consequence"],
            "outcome": outcome,
            "facts": dict(facts),
            "summary": describe_facts(facts) if facts else "",
            "detail": (detail or "")[:SHORT_REASON] or None,
        }
        self.firings.append(firing)
        try:
            await self.hooks.fired(firing, self.dump())
        except Exception:  # recording must not stop the run either
            logger.exception("Guard firing of %s could not be recorded", guard.id)

    # ── interval watches ─────────────────────────────────────────────

    def _watch(self, scope: Scope) -> None:
        tasks = []
        for guard in self._on(scope):
            if guard.trigger.get("type") == "interval":
                tasks.append(asyncio.create_task(self._poll(guard, scope)))
        if tasks:
            self._watches[scope.key] = tasks

    def _unwatch(self, scope: Scope) -> None:
        for task in self._watches.pop(scope.key, []):
            if task is not asyncio.current_task():
                task.cancel()

    async def _poll(self, guard: _Guard, scope: Scope) -> None:
        every = max(
            float(guard.trigger.get("every_seconds", 0)), self.settings.min_interval_seconds
        )
        while scope.active and not self._closed:
            await sleep(every)
            if not scope.active or self._closed:
                return
            verdict = await self._consider(guard, scope, "interval")
            if verdict.stops:
                await self.hooks.interrupt(verdict)
                return


async def _pause(
    monitor: Monitor, guard: _Guard, facts: Mapping[str, Any], reason: str
) -> tuple[Verdict, str | None]:
    return Verdict("pause", f"Paused by guard {reason}"), None


async def _abort(
    monitor: Monitor, guard: _Guard, facts: Mapping[str, Any], reason: str
) -> tuple[Verdict, str | None]:
    return Verdict("abort", f"Aborted by guard {reason}"), None


async def _continue(
    monitor: Monitor, guard: _Guard, facts: Mapping[str, Any], reason: str
) -> tuple[Verdict, str | None]:
    return CONTINUE, None


async def _run_action(
    monitor: Monitor, guard: _Guard, facts: Mapping[str, Any], reason: str
) -> tuple[Verdict, str | None]:
    """The guard's own action: On Pass continues, On Error does the fallback."""
    passed, detail = await monitor.hooks.run_body(guard.data, facts)
    if passed:
        return CONTINUE, f"its action passed{': ' + detail if detail else ''}"
    fallback = str(guard.data.get("fallback") or "pause")
    verdict, _ = await CONSEQUENCES[fallback](monitor, guard, facts, reason)
    return verdict, f"its action failed{': ' + detail if detail else ''}; {fallback}"


#: What a consequence does. ``notify`` and ``handover`` are declared in ``rules/catalog.py`` (``available: False``)
#: and get their entry here when they exist (cards #93 and #95).
CONSEQUENCES: dict[
    str,
    Callable[[Monitor, _Guard, Mapping[str, Any], str], Awaitable[tuple[Verdict, str | None]]],
] = {
    "pause": _pause,
    "abort": _abort,
    "continue": _continue,
    "run_action": _run_action,
}
