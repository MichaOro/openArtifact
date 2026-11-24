"""The shapes of a guard (ADR-060): where it is attached, what fires it, its condition and its consequence."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from openartifact.rules import tree
from openartifact.rules.catalog import GUARD, RuleSchema
from openartifact.schemas_common import UtcDateTime

#: What a guard can watch. A guard on a guard does not exist in this version.
SCOPES = ("pipeline", "stage", "action")
#: Events of a scope: ``enter`` (before its first execution and every time a loop brings the flow back to its
#: entry), ``pass`` / ``error`` (an action in it left by On Pass / On Error), ``leave`` (the flow left it) and
#: ``fail`` (the run fails inside it).
EVENTS = ("enter", "pass", "error", "leave", "fail")
#: What may follow when a guard's own action fails (``run_action``) or when a consequence cannot be carried out.
FALLBACKS = ("pause", "abort", "continue")
MAX_ESCALATION_STEPS = 10
MAX_INTERVAL_SECONDS = 7 * 24 * 3600
NO_GUARDS_ON_GUARDS = "A guard cannot watch a guard (no guards on guards)"


class GuardCondition(tree.ConditionBase):
    """A condition of a guard (checked against the ``guard`` schema)."""

    SCHEMA: ClassVar[RuleSchema] = GUARD

    #: strict: ``true`` is not the number 1 here
    value: list[str] | StrictStr | StrictInt | StrictFloat


class GuardGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["group"] = "group"
    mode: Literal["all", "any"] = "all"
    items: list[Annotated[GuardCondition | GuardGroup, Field(discriminator="type")]] = Field(
        default_factory=list
    )


GuardGroup.model_rebuild()


class EventTrigger(BaseModel):
    """Fired by events of the scope, in the flow: the flow waits for the guard's verdict."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["event"] = "event"
    events: list[Literal["enter", "pass", "error", "leave", "fail"]] = Field(
        min_length=1, max_length=len(EVENTS)
    )


class IntervalTrigger(BaseModel):
    """Checked every ``every_seconds`` while the scope runs; the running action keeps running meanwhile.

    ``for_seconds``: the condition must have held at every check for that long before the guard fires (the ``for``
    of alerting rules). ``cooldown_seconds``: after firing, the guard does not fire again for that long.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["interval"] = "interval"
    every_seconds: int = Field(ge=1, le=MAX_INTERVAL_SECONDS)
    for_seconds: int = Field(default=0, ge=0, le=MAX_INTERVAL_SECONDS)
    cooldown_seconds: int = Field(default=0, ge=0, le=MAX_INTERVAL_SECONDS)


Trigger = Annotated[EventTrigger | IntervalTrigger, Field(discriminator="type")]


class EscalationStep(BaseModel):
    """From the guard's ``from_firing``-th firing on, it fires only every ``every_runs`` rounds of the scope (or
    every ``every_seconds``), counted from its last firing."""

    model_config = ConfigDict(extra="forbid")

    from_firing: int = Field(ge=1, le=1_000_000)
    every_runs: int | None = Field(default=None, ge=1, le=1_000_000)
    every_seconds: int | None = Field(default=None, ge=1, le=MAX_INTERVAL_SECONDS)

    @model_validator(mode="after")
    def _one(self) -> EscalationStep:
        if (self.every_runs is None) == (self.every_seconds is None):
            raise ValueError(
                "an escalation step says every N runs or every N seconds (one of them)"
            )
        return self


def _consequence(value: str) -> str:
    spec = GUARD.consequence(value)
    if spec is None:
        keys = ", ".join(c.key for c in GUARD.consequences)
        raise ValueError(f"unknown consequence {value[:40]!r}: use {keys}")
    if not spec.available:
        raise ValueError(f"the consequence {value!r} is not available yet: {spec.needs}")
    return value


def _scope(value: str) -> str:
    if value == "guard":
        raise ValueError(NO_GUARDS_ON_GUARDS)
    if value not in SCOPES:
        raise ValueError(f"unknown scope {value[:40]!r}: use {', '.join(SCOPES)}")
    return value


def _steps(steps: list[EscalationStep]) -> list[EscalationStep]:
    firsts = [s.from_firing for s in steps]
    if firsts != sorted(set(firsts)):
        raise ValueError("escalation steps go up by their first firing, each once")
    return steps


class GuardWrite(BaseModel):
    """Everything of a guard that can be set (a field left out of an update keeps its value)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    scope_type: str | None = None
    scope_id: str | None = Field(default=None, min_length=1, max_length=36)
    trigger: Trigger | None = None
    when: GuardGroup | None = None
    consequence: str | None = None
    fallback: Literal["pause", "abort", "continue"] | None = None
    escalation: list[EscalationStep] | None = Field(default=None, max_length=MAX_ESCALATION_STEPS)
    definition_id: str | None = None
    enabled: bool | None = None

    @field_validator("consequence")
    @classmethod
    def _known_consequence(cls, value: str | None) -> str | None:
        return None if value is None else _consequence(value)

    @field_validator("scope_type")
    @classmethod
    def _known_scope(cls, value: str | None) -> str | None:
        return None if value is None else _scope(value)

    @field_validator("escalation")
    @classmethod
    def _ordered(cls, value: list[EscalationStep] | None) -> list[EscalationStep] | None:
        return None if value is None else _steps(value)

    @field_validator("when")
    @classmethod
    def _bounded(cls, when: GuardGroup | None) -> GuardGroup | None:
        if when is not None:
            tree.check_bounds(when)
        return when


class GuardCreate(GuardWrite):
    pipeline_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=120)
    scope_type: str
    trigger: Trigger
    consequence: str = "pause"


class GuardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pipeline_id: str
    name: str
    scope_type: str
    scope_id: str | None
    trigger: dict[str, Any]
    when: dict[str, Any]
    consequence: str
    fallback: str
    escalation: list[dict[str, Any]]
    definition_id: str | None
    enabled: bool
    created_at: UtcDateTime
    updated_at: UtcDateTime


class GuardEnabled(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class HeartbeatWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=200)


class HeartbeatRead(BaseModel):
    execution_id: str
    at: datetime
    count: int


class GuardPreview(BaseModel):
    """What a guard would do on the scopes that run now: how many it would fire on and with which facts."""

    running_scopes: int
    matching: int
    matches: list[dict[str, Any]]
