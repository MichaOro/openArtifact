"""What a running agent does, as numbers a guard can test (ADR-060 addendum, card #103).

The agent loop tells the application what happens while it runs (``agent.turn``: a request started or ended, ``agent.tool_call``: a
call of a tool node started or ended, with a short fingerprint of its arguments, never the arguments). :class:`Telemetry` keeps from
that, per execution and in memory, what a guard needs to judge whether an agent is healthy: how many rounds and tool calls, how
many failed, how often the same call was made in a row (the same tool with the same arguments is a storm, the same tool with other
arguments is work), the tokens, and how long ago the last thing happened.

This is the application's *runtime* telemetry. It sits behind :class:`TelemetrySource`, the one thing the guards read, so the event log
that is written during the run (card #100) can take its place without a change in the guards.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

#: Calls kept per execution to see a streak (older ones cannot be part of one that matters).
MAX_CALLS = 200
#: Executions kept in memory (the oldest are dropped first).
MAX_EXECUTIONS = 100


def _now() -> datetime:
    return datetime.now(UTC)


class TelemetrySource(Protocol):
    """What the guards read: the agent facts of one execution (``agent.*``), as numbers."""

    def facts(self, execution_id: str | None, at: datetime | None = None) -> dict[str, Any]: ...


@dataclass
class RunTelemetry:
    """The agent activity of one execution."""

    turns: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    tokens: int = 0
    last_event_at: datetime | None = None
    last_tool_call_at: datetime | None = None
    #: The finished calls in order: ``(tool, fingerprint, ok)``.
    calls: list[tuple[str, str, bool]] = field(default_factory=list)

    def record(self, event: str, data: dict[str, Any], at: datetime) -> None:
        """One event of an agent (``turn`` or ``tool_call``)."""
        self.last_event_at = at
        if event == "turn":
            if data.get("state") == "finished":
                self.turns += 1
                running = data.get("total_tokens")  # the step's total so far
                if isinstance(running, int | float):
                    self.tokens = max(self.tokens, int(running))
                elif isinstance(data.get("tokens"), int | float):
                    self.tokens += int(data["tokens"])
        elif event == "tool_call":
            self.last_tool_call_at = at
            if data.get("state") == "finished":
                self.tool_calls += 1
                ok = bool(data.get("ok", True))
                if not ok:
                    self.tool_errors += 1
                self.calls.append(
                    (str(data.get("tool") or ""), str(data.get("args_key") or ""), ok)
                )
                del self.calls[:-MAX_CALLS]

    def streaks(self) -> tuple[int, int]:
        """The length of the streak at the end of the calls of the same tool with the same arguments, and of the same tool."""
        same_call = same_tool = 0
        if not self.calls:
            return 0, 0
        last_tool, last_key, _ = self.calls[-1]
        for tool, _key, _ok in reversed(self.calls):
            if tool != last_tool:
                break
            same_tool += 1
        for tool, key, _ok in reversed(self.calls):
            if tool != last_tool or key != last_key:
                break
            same_call += 1
        return same_call, same_tool

    def facts(self, at: datetime) -> dict[str, Any]:
        """The facts ``agent.*``: only what has happened (an execution without an agent has none, and a condition on a fact that is
        not there never holds)."""
        if self.last_event_at is None:
            return {}
        same_call, same_tool = self.streaks()
        facts: dict[str, Any] = {
            "agent.turns": self.turns,
            "agent.tool_calls": self.tool_calls,
            "agent.tool_errors": self.tool_errors,
            "agent.tokens": self.tokens,
            "agent.repeat": same_call,
            "agent.same_tool": same_tool,
            "agent.idle": max(0, int((at - self.last_event_at).total_seconds())),
        }
        if self.last_tool_call_at is not None:
            facts["agent.since_tool_call"] = max(
                0, int((at - self.last_tool_call_at).total_seconds())
            )
        return facts


class Telemetry:
    """The runtime telemetry of the executions that run (and the last ones): :class:`TelemetrySource` for the guards."""

    def __init__(self, clock: Callable[[], datetime] = _now) -> None:
        self._runs: OrderedDict[str, RunTelemetry] = OrderedDict()
        self._clock = clock

    def record(self, event_type: str, data: dict[str, Any]) -> None:
        """An application event: only ``agent.*`` of an execution counts."""
        execution_id = data.get("execution_id")
        if not execution_id or not event_type.startswith("agent."):
            return
        run = self._runs.get(str(execution_id))
        if run is None:
            run = self._runs[str(execution_id)] = RunTelemetry()
            while len(self._runs) > MAX_EXECUTIONS:
                self._runs.popitem(last=False)
        self._runs.move_to_end(str(execution_id))
        run.record(event_type.removeprefix("agent."), data, self._clock())

    def facts(self, execution_id: str | None, at: datetime | None = None) -> dict[str, Any]:
        run = self._runs.get(execution_id or "")
        return run.facts(at or self._clock()) if run else {}

    def forget(self, execution_id: str) -> None:
        self._runs.pop(execution_id, None)
