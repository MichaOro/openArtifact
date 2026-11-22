"""Request and response schemas for board tasks and for starting their processing."""

from __future__ import annotations

import json
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from openartifact.schemas_common import UtcDateTime

TITLE_MAX_LENGTH = 255
BODY_MAX_LENGTH = 10_000


def _blank_to_none(value: str | None) -> str | None:
    """Store an empty or whitespace-only body as NULL, any other trimmed."""
    if value is None or not value.strip():
        return None
    return value.strip()


Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TITLE_MAX_LENGTH)
]
Body = Annotated[str | None, Field(max_length=BODY_MAX_LENGTH), AfterValidator(_blank_to_none)]


class TaskCreate(BaseModel):
    """Payload for creating a task."""

    model_config = ConfigDict(extra="forbid")

    title: Title
    body: Body = None
    #: Lane key (the service checks it against the lanes); ``null`` or left out: the first lane.
    status: str | None = None
    #: Parent artifact (the new one becomes its child).
    parent_id: str | None = None
    #: Pipeline to start with; the stage and action default to the first ones of the pipeline.
    pipeline_id: str | None = None
    stage_id: str | None = None
    action_id: str | None = None
    #: Artifact type (``null``: none) and the values of its parameters, checked now (422 names the
    #: parameter); defaults of the type fill what is not given.
    type_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class TaskUpdate(BaseModel):
    """Partial update: only the fields that are sent are changed.

    ``status`` moves the task to another lane, ``title``/``body`` edit its content.
    ``body: null`` (or blank) clears the description; ``title`` and ``status`` cannot be null.
    """

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    body: Body = None
    status: str | None = None
    #: Position inside the (target) lane: put the task before this task. ``null`` = at the end.
    before_id: str | None = None
    #: Parent artifact. ``null`` removes the parent.
    parent_id: str | None = None
    #: Pipeline, stage and action to start with (``pipeline_id: null`` clears all three).
    pipeline_id: str | None = None
    stage_id: str | None = None
    action_id: str | None = None
    #: Artifact type (``null``: none). Its parameters must stay valid: see ``reset_parameters``.
    type_id: str | None = None
    #: Parameter values to set; the others stay (``null`` as a value clears one to its default).
    parameters: dict[str, Any] | None = None
    #: Drop the stored values first, so that a type can change although they do not fit the new one.
    reset_parameters: bool = False

    @model_validator(mode="after")
    def _check_fields(self) -> TaskUpdate:
        sent = self.model_fields_set
        if not sent:
            raise ValueError("At least one field to change is required")
        for name in ("title", "status", "parameters", "reset_parameters"):
            if name in sent and getattr(self, name) is None:
                raise ValueError(f"{name} must not be null")
        return self


class RunStart(BaseModel):
    """Body of ``POST /api/tasks/{id}/run``: the pipeline, and optionally where to start in it.

    Everything may be left out: the artifact then starts with the pipeline, stage and action it has.
    """

    model_config = ConfigDict(extra="forbid")

    pipeline_id: str | None = None
    stage_id: str | None = None
    action_id: str | None = None


class TaskRead(BaseModel):
    """A task as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    number: int
    title: str
    body: str | None
    status: str
    position: float
    parent_id: str | None
    pipeline_id: str | None
    stage_id: str | None
    action_id: str | None
    type_id: str | None
    #: The values of the type's parameters by name (only those that are set).
    parameters: dict[str, Any]
    created_by: str
    created_at: UtcDateTime
    updated_at: UtcDateTime

    @field_validator("parameters", mode="before")
    @classmethod
    def _from_json(cls, value: Any) -> Any:
        return json.loads(value) if isinstance(value, str) else value


class LaneRead(BaseModel):
    """A board lane: ``status`` is the key artifacts carry, ``title`` what the user sees."""

    status: str
    #: DOM-friendly form of ``status`` (``in-progress``).
    key: str
    title: str
    #: Order on the board, ascending (gaps are possible after a deletion).
    position: int
    #: Palette index of the lane's colour (1 to 8), by place on the board.
    hue: int
    #: How the lane draws its cards: ``normal``, or ``finished`` (titles struck through and dimmed).
    style: str
    artifact_count: int
    #: Whether the lane could be deleted now: it holds no artifacts and is not the last lane.
    deletable: bool


class LaneWrite(BaseModel):
    """Payload for creating a lane or changing a lane's title."""

    model_config = ConfigDict(extra="forbid")

    title: str


class LaneUpdate(BaseModel):
    """Payload for changing a lane: a new ``title``, a new ``style``, or both (at least one)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    style: str | None = None
