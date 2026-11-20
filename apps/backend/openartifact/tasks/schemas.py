"""Request and response schemas for board tasks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from openartifact.models import TaskStatus

TITLE_MAX_LENGTH = 255
BODY_MAX_LENGTH = 10_000


class TaskCreate(BaseModel):
    """Payload for creating a task."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=TITLE_MAX_LENGTH),
    ]
    body: Annotated[str | None, Field(max_length=BODY_MAX_LENGTH)] = None
    status: TaskStatus = TaskStatus.BACKLOG

    @field_validator("body")
    @classmethod
    def _blank_body_is_none(cls, value: str | None) -> str | None:
        """Store an empty or whitespace-only body as NULL."""
        if value is None or not value.strip():
            return None
        return value.strip()


class TaskUpdate(BaseModel):
    """Partial update: only the fields that are sent are changed.

    ``status`` moves the task to another lane, ``title``/``body`` edit its content.
    ``body: null`` (or blank) clears the description; ``title`` and ``status`` cannot be null.
    """

    model_config = ConfigDict(extra="forbid")

    title: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=TITLE_MAX_LENGTH),
        ]
        | None
    ) = None
    body: Annotated[str | None, Field(max_length=BODY_MAX_LENGTH)] = None
    status: TaskStatus | None = None
    #: Position inside the (target) lane: put the task before this task. ``null`` = at the end.
    before_id: str | None = None

    @field_validator("body")
    @classmethod
    def _blank_body_is_none(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return value.strip()

    @model_validator(mode="after")
    def _check_fields(self) -> TaskUpdate:
        sent = self.model_fields_set
        if not sent:
            raise ValueError("At least one of title, body, status or before_id is required")
        for name in ("title", "status"):
            if name in sent and getattr(self, name) is None:
                raise ValueError(f"{name} must not be null")
        return self


class TaskRead(BaseModel):
    """A task as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    body: str | None
    status: TaskStatus
    position: float
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _serialize_utc(self, value: datetime) -> str:
        """SQLite returns naive datetimes; they are always UTC."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat().replace("+00:00", "Z")
