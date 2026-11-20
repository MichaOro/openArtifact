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


class TaskRead(BaseModel):
    """A task as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    body: str | None
    status: TaskStatus
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _serialize_utc(self, value: datetime) -> str:
        """SQLite returns naive datetimes; they are always UTC."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat().replace("+00:00", "Z")
