"""The shapes of an activity entry on its way out."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from openartifact.schemas_common import UtcDateTime

#: What can be recorded: a change of the artifact, the trace of a delete action on executions (``run``), a comment
#: (``comment``: its id, never its text) and the trace of a deleted comment (``comment_deleted``).
KINDS = (
    "created",
    "lane",
    "title",
    "description",
    "parent",
    "field",
    "pipeline",
    "stage",
    "action",
    "run",
    "comment",
    "comment_deleted",
)
PAGE_DEFAULT = 50
PAGE_MAX = 200


class ActivityRead(BaseModel):
    """One entry of the activity of an artifact (``data`` depends on ``kind``, see ADR-058)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    kind: str
    actor_kind: str
    actor_name: str
    execution_id: str | None
    data: dict[str, Any]
    created_at: UtcDateTime

    @field_validator("data", mode="before")
    @classmethod
    def _parsed(cls, value: object) -> object:
        """The row keeps ``data`` as JSON text."""
        if isinstance(value, str):
            try:
                loaded = json.loads(value)
            except ValueError:
                return {}
            return loaded if isinstance(loaded, dict) else {}
        return value


class ActivityPage(BaseModel):
    """One page of the activity, newest first; ``next`` is the cursor of the next (older) page or ``None``."""

    items: list[ActivityRead]
    next: str | None
