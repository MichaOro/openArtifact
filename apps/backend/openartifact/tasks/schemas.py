"""Request and response schemas for board tasks and for starting their processing."""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from openartifact.models import TaskStatus
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
    status: TaskStatus = TaskStatus.BACKLOG
    #: Parent artifact (the new one becomes its child).
    parent_id: str | None = None
    #: Pipeline to start with; the stage and action default to the first ones of the pipeline.
    pipeline_id: str | None = None
    stage_id: str | None = None
    action_id: str | None = None


class TaskUpdate(BaseModel):
    """Partial update: only the fields that are sent are changed.

    ``status`` moves the task to another lane, ``title``/``body`` edit its content.
    ``body: null`` (or blank) clears the description; ``title`` and ``status`` cannot be null.
    """

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    body: Body = None
    status: TaskStatus | None = None
    #: Position inside the (target) lane: put the task before this task. ``null`` = at the end.
    before_id: str | None = None
    #: Parent artifact. ``null`` removes the parent.
    parent_id: str | None = None
    #: Pipeline, stage and action to start with (``pipeline_id: null`` clears all three).
    pipeline_id: str | None = None
    stage_id: str | None = None
    action_id: str | None = None

    @model_validator(mode="after")
    def _check_fields(self) -> TaskUpdate:
        sent = self.model_fields_set
        if not sent:
            raise ValueError("At least one field to change is required")
        for name in ("title", "status"):
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
    status: TaskStatus
    position: float
    parent_id: str | None
    pipeline_id: str | None
    stage_id: str | None
    action_id: str | None
    created_by: str
    created_at: UtcDateTime
    updated_at: UtcDateTime


class LaneRead(BaseModel):
    """A board lane as shown: ``status`` is the code the artifact API uses, ``title`` what the user sees."""

    status: TaskStatus
    #: DOM-friendly form of ``status`` (``in-progress``).
    key: str
    title: str
    default_title: str
    #: Palette index of the lane's colour (1 to 8).
    hue: int


class LaneRename(BaseModel):
    """Payload for renaming a lane: ``title: null`` (or empty, or the default text) restores the default."""

    model_config = ConfigDict(extra="forbid")

    title: str | None
