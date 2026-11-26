"""Writing the activity of an artifact: one row per real change, at most ``MAX_PER_TASK`` rows per artifact."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.activity.schemas import ActivityRead
from openartifact.comments.schemas import AUTHOR_MAX_LENGTH, Author
from openartifact.models import TaskActivity

#: The oldest entries beyond this many per artifact are removed when a new one is written.
MAX_PER_TASK = 500
#: A value that is shown in an entry (a field's new value, a title) is cut to this many characters.
SHORT = 80

SYSTEM = Author("system", "system")


def short(value: object) -> str | None:
    """A value as short text for an entry: ``None`` stays ``None``, lists and objects as JSON, long text cut."""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= SHORT else text[: SHORT - 1] + "…"


async def record(
    session: AsyncSession,
    task_id: str,
    kind: str,
    actor: Author,
    data: dict[str, Any] | None = None,
    *,
    execution_id: str | None = None,
    at: datetime | None = None,
) -> ActivityRead:
    """Add an entry in the caller's transaction (not committed) and keep the artifact within its cap.

    The caller publishes ``activity.created`` with the returned entry after its commit.
    """
    row = TaskActivity(
        id=str(uuid.uuid4()),
        task_id=task_id,
        kind=kind,
        actor_kind=actor.kind,
        actor_name=actor.name[:AUTHOR_MAX_LENGTH],
        execution_id=execution_id if execution_id is not None else actor.execution_id,
        data=json.dumps(data or {}, ensure_ascii=False),
        created_at=at or datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    await _prune(session, task_id)
    return ActivityRead.model_validate(row)


async def _prune(session: AsyncSession, task_id: str) -> None:
    """Delete the oldest entries beyond ``MAX_PER_TASK``."""
    total = await session.scalar(
        select(func.count()).select_from(TaskActivity).where(TaskActivity.task_id == task_id)
    )
    excess = (total or 0) - MAX_PER_TASK
    if excess <= 0:
        return
    oldest = (
        select(TaskActivity.id)
        .where(TaskActivity.task_id == task_id)
        .order_by(TaskActivity.created_at, TaskActivity.id)
        .limit(excess)
    )
    await session.execute(delete(TaskActivity).where(TaskActivity.id.in_(oldest)))
