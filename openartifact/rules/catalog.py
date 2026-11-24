"""The schemas of the rule system: per purpose, what a condition may test and what a rule may do.

A schema lists its *fields* (key, value kind, operators, the values a choice offers, bounds), its *consequences*
(what a rule does when its tree holds; one that is not built yet is ``available: False`` and refused) and says
what *triggers* a rule. The browser reads them from ``GET /api/rules/schemas`` and gives the rule builder its
labels from the dictionary (``rules.<purpose>.<field>``); the server checks every condition against them.

- ``retention``: the rules over finished executions (ADR-052). Triggered when an execution is added or finishes and
  when the rules are saved; consequence ``delete``. Its checks keep their own wording (``_check_retention``).
- ``guard``: the condition of a guard (ADR-060) over the facts of a running scope.
- ``lane``: planned (lane rules: hide after N days, colour by time in the lane); documented here so the format is
  settled, not used by anything yet.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from openartifact.models.enums import RunStatus, StartedBy

#: Value kinds a condition may have (the rule builder draws one control per kind).
KINDS = ("choice", "text", "duration", "count", "number")
#: Operators and what they mean (``rules/tree.py`` evaluates them, ``engine/retention.py`` compiles some to SQL).
OPERATORS = {
    "is": "is one of / equals (text ignoring case)",
    "is_not": "is none of / differs from",
    "contains": "contains (ignoring case)",
    "older_than": "more than N seconds",
    "beyond": "at least N newer ones",
    "at_least": "at least",
    "below": "less than",
    "equals": "exactly",
}


@dataclass(frozen=True)
class FieldSpec:
    key: str
    kind: str
    operators: tuple[str, ...]
    label: str
    options: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    #: A field that stands for many (``var.NAME``): conditions name it as ``prefix + name``.
    prefix: str | None = None
    #: Units the rule builder offers for a duration (largest first).
    units: tuple[str, ...] = ()

    def to_data(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "operators": list(self.operators),
            "label": self.label,
            "options": list(self.options),
            "minimum": self.minimum,
            "maximum": self.maximum,
            "prefix": self.prefix,
            "units": list(self.units),
        }


@dataclass(frozen=True)
class ConsequenceSpec:
    key: str
    label: str
    available: bool = True
    #: Why it is not available yet (shown next to the disabled choice, sent with the 422).
    needs: str | None = None

    def to_data(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "available": self.available,
            "needs": self.needs,
        }


@dataclass(frozen=True)
class RuleSchema:
    purpose: str
    fields: tuple[FieldSpec, ...]
    consequences: tuple[ConsequenceSpec, ...]
    triggers: str
    planned: bool = False
    custom_check: Callable[[Any], None] | None = field(default=None, compare=False)

    def field_for(self, key: str) -> FieldSpec | None:
        for spec in self.fields:
            if spec.key == key or (spec.prefix and key.startswith(spec.prefix)):
                return spec
        return None

    def consequence(self, key: str) -> ConsequenceSpec | None:
        return next((c for c in self.consequences if c.key == key), None)

    def check(self, condition: Any) -> None:
        """Raise :class:`ValueError` (with the reason) unless the condition fits this schema."""
        if self.custom_check is not None:
            self.custom_check(condition)
            return
        _check_generic(self, condition)

    def to_data(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "fields": [f.to_data() for f in self.fields],
            "consequences": [c.to_data() for c in self.consequences],
            "triggers": self.triggers,
            "planned": self.planned,
        }


VAR_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")


def _check_generic(schema: RuleSchema, c: Any) -> None:
    spec = schema.field_for(c.field)
    if spec is None:
        names = ", ".join(f.prefix + "NAME" if f.prefix else f.key for f in schema.fields)
        raise ValueError(f"unknown field {c.field[:40]!r}: use {names}")
    if spec.prefix and not VAR_NAME.fullmatch(c.field[len(spec.prefix) :]):
        raise ValueError(
            f"{c.field[:40]!r}: name a result field as {spec.prefix}NAME "
            "(lower case letters, digits and _, starting with a letter)"
        )
    if c.op not in spec.operators:
        raise ValueError(
            f"{spec.key}: the operator {c.op!r} does not fit; use {', '.join(spec.operators)}"
        )
    value = c.value
    if spec.kind == "choice":
        if not isinstance(value, list) or not value:
            raise ValueError(f"{spec.key}: name at least one of {', '.join(spec.options)}")
        bad = [v for v in value if v not in spec.options]
        if bad:
            raise ValueError(
                f"{spec.key}: {str(bad[0])[:40]!r} is not one of {', '.join(spec.options)}"
            )
        return
    if spec.kind == "text":
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 120:
            raise ValueError(f"{spec.key}: give a text of 1 to 120 characters")
        return
    whole = spec.kind in ("duration", "count")
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or (whole and not isinstance(value, int))
    ):
        what = "seconds" if spec.kind == "duration" else "a whole number" if whole else "a number"
        raise ValueError(f"{spec.key}: give {what}")
    low, high = spec.minimum, spec.maximum
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValueError(f"{spec.key}: give a value from {low:g} to {high:g}")


# ── retention (ADR-052) ───────────────────────────────────────────────

MIN_AGE_SECONDS, MAX_AGE_SECONDS = 60, 10 * 365 * 24 * 3600
MAX_POSITION = 100_000
#: What a status condition may name: a running execution is never deleted, so it cannot be a target.
RETENTION_STATUSES = (RunStatus.DONE, RunStatus.FAILED, RunStatus.STOPPED)


def _check_retention(c: Any) -> None:
    """The checks of the retention rules, worded as they always were."""
    fields = {f.key: f.operators for f in RETENTION.fields}
    if c.field not in fields:
        raise ValueError(f"unknown field {c.field[:40]!r}: use {', '.join(fields)}")
    if c.op not in fields[c.field]:
        raise ValueError(
            f"{c.field}: the operator {c.op!r} does not fit; use {', '.join(fields[c.field])}"
        )
    if c.field in ("status", "started_by"):
        allowed = (
            [str(s) for s in RETENTION_STATUSES]
            if c.field == "status"
            else [str(s) for s in StartedBy]
        )
        if not isinstance(c.value, list) or not c.value:
            raise ValueError(f"{c.field}: name at least one of {', '.join(allowed)}")
        bad = [v for v in c.value if v not in allowed]
        if bad:
            note = " (a running execution is never deleted)" if bad[0] == "running" else ""
            raise ValueError(
                f"{c.field}: {str(bad[0])[:40]!r} is not one of {', '.join(allowed)}{note}"
            )
    elif c.field == "pipeline":
        if not isinstance(c.value, str) or not 1 <= len(c.value.strip()) <= 120:
            raise ValueError("pipeline: give a name of 1 to 120 characters")
    elif c.field == "position":
        if (
            isinstance(c.value, bool)
            or not isinstance(c.value, int)
            or not 1 <= c.value <= MAX_POSITION
        ):
            raise ValueError(f"position: give how many of the newest to keep, 1 to {MAX_POSITION}")
    elif (
        isinstance(c.value, bool)
        or not isinstance(c.value, int)
        or not MIN_AGE_SECONDS <= c.value <= MAX_AGE_SECONDS
    ):
        raise ValueError(f"age: give seconds, {MIN_AGE_SECONDS} (a minute) or more")


RETENTION = RuleSchema(
    purpose="retention",
    fields=(
        FieldSpec(
            "status",
            "choice",
            ("is", "is_not"),
            "Status",
            tuple(str(s) for s in RETENTION_STATUSES),
        ),
        FieldSpec(
            "started_by", "choice", ("is", "is_not"), "Started by", tuple(str(s) for s in StartedBy)
        ),
        FieldSpec("pipeline", "text", ("is", "is_not", "contains"), "Pipeline"),
        FieldSpec(
            "age",
            "duration",
            ("older_than",),
            "Age",
            minimum=MIN_AGE_SECONDS,
            maximum=MAX_AGE_SECONDS,
            units=("days", "hours", "minutes"),
        ),
        FieldSpec("position", "count", ("beyond",), "Position", minimum=1, maximum=MAX_POSITION),
    ),
    consequences=(ConsequenceSpec("delete", "Delete the execution"),),
    triggers="An execution is added or finishes, or the rules are saved (no timer).",
    custom_check=_check_retention,
)

# ── guards (ADR-060) ──────────────────────────────────────────────────

DAY = 24 * 3600
_NUMERIC = ("at_least", "below", "equals")
_DURATION = ("at_least", "below")
_SHORT_UNITS = ("hours", "minutes", "seconds")
LAST_STATUSES = ("pass", "error", "none")

GUARD = RuleSchema(
    purpose="guard",
    fields=(
        FieldSpec("runs", "count", _NUMERIC, "Rounds of the scope", minimum=0, maximum=1_000_000),
        FieldSpec(
            "elapsed",
            "duration",
            _DURATION,
            "Time in the scope",
            minimum=0,
            maximum=30 * DAY,
            units=_SHORT_UNITS,
        ),
        FieldSpec(
            "idle",
            "duration",
            _DURATION,
            "Time without progress",
            minimum=0,
            maximum=30 * DAY,
            units=_SHORT_UNITS,
        ),
        FieldSpec("errors", "count", _NUMERIC, "Errors (On Error)", minimum=0, maximum=1_000_000),
        FieldSpec("passes", "count", _NUMERIC, "Passes (On Pass)", minimum=0, maximum=1_000_000),
        FieldSpec(
            "guard.runs", "count", _NUMERIC, "Times this guard fired", minimum=0, maximum=1_000_000
        ),
        FieldSpec("last_status", "choice", ("is", "is_not"), "Last action", LAST_STATUSES),
        FieldSpec("cost", "number", ("at_least", "below"), "Cost", minimum=0, maximum=1e9),
        FieldSpec(
            "var.",
            "number",
            _NUMERIC,
            "Result field",
            minimum=-1e12,
            maximum=1e12,
            prefix="var.",
        ),
    ),
    consequences=(
        ConsequenceSpec("pause", "Pause the run"),
        ConsequenceSpec("abort", "Abort the run"),
        ConsequenceSpec("continue", "Continue (record only)"),
        ConsequenceSpec("run_action", "Run the guard's action"),
        ConsequenceSpec(
            "notify", "Notify", available=False, needs="needs notifications (MVP 25, card #93)"
        ),
        ConsequenceSpec(
            "handover", "Hand over", available=False, needs="needs handover (MVP 27, card #95)"
        ),
    ),
    triggers=(
        "An event of the scope (enter, pass, error, leave, fail; blocking: the flow waits for the verdict) "
        "or an interval while the scope runs (with for and cooldown)."
    ),
)

# ── lanes (planned) ───────────────────────────────────────────────────

LANE = RuleSchema(
    purpose="lane",
    fields=(
        FieldSpec(
            "time_in_lane",
            "duration",
            _DURATION,
            "Time in the lane",
            minimum=60,
            maximum=3650 * DAY,
            units=("days", "hours", "minutes"),
        ),
        FieldSpec("lane", "text", ("is", "is_not", "contains"), "Lane"),
    ),
    consequences=(
        ConsequenceSpec("hide", "Hide the card", available=False, needs="lane rules (planned)"),
        ConsequenceSpec("colour", "Colour the card", available=False, needs="lane rules (planned)"),
    ),
    triggers="Planned: a card enters a lane, or time passes (needs the lane-since date).",
    planned=True,
)

SCHEMAS: dict[str, RuleSchema] = {s.purpose: s for s in (RETENTION, GUARD, LANE)}
