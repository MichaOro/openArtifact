"""Reading the activity of an artifact, for every way in (browser, ``/api/v1``, MCP)."""

from __future__ import annotations

import base64
import json
from datetime import datetime

from sqlalchemy import and_, or_, select

from openartifact.activity.schemas import PAGE_DEFAULT, PAGE_MAX, ActivityPage, ActivityRead
from openartifact.database import SessionOpener
from openartifact.exceptions import ArtifactError
from openartifact.models import TaskActivity
from openartifact.tasks.service import ArtifactService

BAD_CURSOR = "The cursor is not valid"


def encode_cursor(created_at: datetime, row_id: str) -> str:
    """A page position (the last entry's time and id) as an opaque string."""
    raw = json.dumps([created_at.isoformat(), row_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """The time and id a cursor stands for; 422 for anything else."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        stamp, row_id = json.loads(base64.urlsafe_b64decode(padded))
        return datetime.fromisoformat(stamp), str(row_id)
    except (ValueError, TypeError) as error:
        raise ArtifactError(422, BAD_CURSOR) from error


class ActivityService:
    """The activity of artifacts, newest first, in pages."""

    def __init__(self, session: SessionOpener) -> None:
        self._session = session

    async def activity(
        self, ref: str, limit: int = PAGE_DEFAULT, before: str | None = None
    ) -> ActivityPage:
        """One page of the artifact's activity: up to ``limit`` entries older than the ``before`` cursor."""
        limit = max(1, min(limit, PAGE_MAX))
        async with self._session() as session:
            task = await ArtifactService._task(session, ref)
            query = select(TaskActivity).where(TaskActivity.task_id == task.id)
            if before is not None:
                moment, row_id = decode_cursor(before)
                query = query.where(
                    or_(
                        TaskActivity.created_at < moment,
                        and_(TaskActivity.created_at == moment, TaskActivity.id < row_id),
                    )
                )
            rows = list(
                await session.scalars(
                    query.order_by(TaskActivity.created_at.desc(), TaskActivity.id.desc()).limit(
                        limit + 1
                    )
                )
            )
        more = len(rows) > limit
        rows = rows[:limit]
        return ActivityPage(
            items=[ActivityRead.model_validate(r) for r in rows],
            next=encode_cursor(rows[-1].created_at, rows[-1].id) if more else None,
        )
