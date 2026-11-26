"""The shapes of a guard (ADR-060): a definition of the library (what fires it, its condition and its consequence) and
its attachments (where it watches)."""

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

#: What a guard can watch. A guard on a guard does not exist in this version. ``pipeline``, ``stage`` and ``action``
#: (an action node of a pipeline) are scopes of a pipeline; ``definition`` (a whole action definition, wherever it is
#: used) and ``node`` (one execution node of an action definition) are scopes of an action definition.
SCOPES = ("pipeline", "stage", "action", "definition", "node")
#: The scopes a pipeline holds and the scopes an action definition holds.
PIPELINE_SCOPES = ("pipeline", "stage", "action")
DEFINITION_SCOPES = ("definition", "node")
#: Events of a scope: ``enter`` (before its first execution and every time a loop brings the flow back to its
#: entry), ``pass`` / ``error`` (an action in it left by On Pass / On Error), ``leave`` (the flow left it) and
#: ``fail`` (the run fails inside it).
EVENTS = ("enter", "pass", "error", "leave", "fail")
#: What may follow when a guard's own action fails (``run_action``) or when a consequence cannot be carried out.
FALLBACKS = ("pause", "abort", "continue")
MAX_ESCALATION_STEPS = 10
MAX_NAME = 120
MAX_DESCRIPTION = 500
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


def _scope_types(values: list[str]) -> list[str]:
    for value in values:
        _scope(value)
    if len(set(values)) != len(values):
        raise ValueError("each scope type once")
    return [s for s in SCOPES if s in values]


class GuardDefinitionWrite(BaseModel):
    """Everything of a guard definition that can be set (a field left out of an update keeps its value)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)
    scope_types: list[str] | None = Field(default=None, min_length=1, max_length=len(SCOPES))
    trigger: Trigger | None = None
    when: GuardGroup | None = None
    consequence: str | None = None
    fallback: Literal["pause", "abort", "continue"] | None = None
    escalation: list[EscalationStep] | None = Field(default=None, max_length=MAX_ESCALATION_STEPS)
    action_id: str | None = Field(default=None, max_length=36)

    @field_validator("name")
    @classmethod
    def _named(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("a guard needs a name")
        return None if value is None else value.strip()

    @field_validator("consequence")
    @classmethod
    def _known_consequence(cls, value: str | None) -> str | None:
        return None if value is None else _consequence(value)

    @field_validator("scope_types")
    @classmethod
    def _known_scopes(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _scope_types(value)

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


class GuardDefinitionCreate(GuardDefinitionWrite):
    name: str = Field(min_length=1, max_length=MAX_NAME)
    trigger: Trigger
    consequence: str = "pause"


class AttachmentRead(BaseModel):
    """A guard definition on a scope of a pipeline or of an action definition; ``name`` is the definition's.

    ``graph_id`` is the graph that holds the scope (``holder_kind``: ``pipeline`` or ``action``, ``holder_name`` its
    name); ``pipeline_id`` is the same id when the holder is a pipeline and ``None`` otherwise. ``scope_name`` is the
    name of the stage, action or node (or of the graph itself for ``pipeline`` and ``definition``)."""

    id: str
    guard_id: str
    name: str
    graph_id: str
    pipeline_id: str | None
    holder_kind: str
    holder_name: str = ""
    scope_type: str
    scope_id: str
    scope_name: str = ""
    enabled: bool
    created_at: UtcDateTime


class GuardDefinitionRead(BaseModel):
    id: str
    name: str
    description: str
    scope_types: list[str]
    trigger: dict[str, Any]
    when: dict[str, Any]
    consequence: str
    fallback: str
    escalation: list[dict[str, Any]]
    action_id: str | None
    #: How many places it is attached to (a change acts on all of them; it cannot be deleted while used)
    used_by: int
    attachments: list[AttachmentRead]
    created_at: UtcDateTime
    updated_at: UtcDateTime


class AttachmentCreate(BaseModel):
    """Attach a definition to a scope: the pipeline (or the action definition) itself (``scope_id`` may be left out), a
    stage or an action of a pipeline, a node of an action definition. The holder is ``graph_id``; ``pipeline_id`` is
    the same thing under its old name (one of the two is needed)."""

    model_config = ConfigDict(extra="forbid")

    guard_id: str = Field(min_length=1, max_length=36)
    graph_id: str | None = Field(default=None, min_length=1, max_length=36)
    pipeline_id: str | None = Field(default=None, min_length=1, max_length=36)
    scope_type: str
    scope_id: str | None = Field(default=None, min_length=1, max_length=36)
    enabled: bool = True

    @field_validator("scope_type")
    @classmethod
    def _known_scope(cls, value: str) -> str:
        return _scope(value)

    @model_validator(mode="after")
    def _holder(self) -> AttachmentCreate:
        if self.graph_id is None and self.pipeline_id is None:
            raise ValueError(
                "graph_id is needed (the pipeline or the action definition that holds the scope)"
            )
        if self.graph_id is not None and self.pipeline_id not in (None, self.graph_id):
            raise ValueError("graph_id and pipeline_id name different graphs: use graph_id")
        return self

    @property
    def holder(self) -> str:
        return str(self.graph_id or self.pipeline_id)


class FromTemplate(BaseModel):
    """A definition made from a shipped template (Stall, Runtime, Health guard)."""

    model_config = ConfigDict(extra="forbid")

    template: str = Field(min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME)
    #: the template's summary when left out (the editor sends it in the reader's language)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)


class PreviewRequest(BaseModel):
    """The condition being edited, evaluated over the running scopes of the definition's attachments."""

    model_config = ConfigDict(extra="forbid")

    guard_id: str | None = Field(default=None, max_length=36)
    when: GuardGroup

    @field_validator("when")
    @classmethod
    def _bounded(cls, when: GuardGroup) -> GuardGroup:
        tree.check_bounds(when)
        return when


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
