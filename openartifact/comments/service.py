"""What can be done with comments, once, for every way in (browser, ``/api/v1``, MCP, the artifact node)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.activity.recorder import SYSTEM, record
from openartifact.comments.schemas import AUTHOR_MAX_LENGTH, Author, CommentRead
from openartifact.database import SessionOpener
from openartifact.events import EventBus
from openartifact.exceptions import ArtifactError
from openartifact.models import Task, TaskActivity, TaskComment
from openartifact.security import ADMIN, principal
from openartifact.tasks.service import ArtifactService

NOT_FOUND = "Comment not found"


def author_of(channel: str, requested: str | None = None) -> Author:
    """Who the current request is, by what authenticated it (never by what the caller claims).

    ``channel`` is how the request came in: ``user`` (the browser's API), ``api`` or ``mcp``. A managed token writes under
    its own name; the administrative token may name an author (``requested``); a request without a bearer token is the
    browser ("You") on the browser's API and the channel's own name elsewhere.
    """
    who = principal.get()
    if who is None:
        return Author(channel, "You" if channel == "user" else channel)
    if who == ADMIN:
        name = (requested or "").strip()[:AUTHOR_MAX_LENGTH]
        return Author("api" if channel == "user" else channel, name or channel)
    return Author("api" if channel == "user" else channel, who[:AUTHOR_MAX_LENGTH])


class CommentService:
    """Comments of artifacts; publishes ``comment.created``, ``comment.updated`` and ``comment.deleted``."""

    def __init__(self, session: SessionOpener, bus: EventBus) -> None:
        self._session = session
        self._bus = bus

    async def comments(self, ref: str, newest: int | None = None) -> list[CommentRead]:
        """The comments of an artifact, oldest first; with ``newest`` only that many of the newest ones (still oldest first)."""
        async with self._session() as session:
            task = await ArtifactService._task(session, ref)
            query = select(TaskComment).where(TaskComment.task_id == task.id)
            if newest is not None:
                rows = (
                    await session.scalars(
                        query.order_by(TaskComment.created_at.desc(), TaskComment.id.desc()).limit(
                            newest
                        )
                    )
                ).all()
                rows = list(reversed(rows))
            else:
                rows = list(
                    await session.scalars(query.order_by(TaskComment.created_at, TaskComment.id))
                )
            return [CommentRead.model_validate(r) for r in rows]

    async def add(self, ref: str, body: str, author: Author) -> CommentRead:
        """Add a comment to the artifact."""
        async with self._session() as session:
            task = await ArtifactService._task(session, ref)
            now = datetime.now(UTC)
            row = TaskComment(
                id=str(uuid.uuid4()),
                task_id=task.id,
                body=body,
                author_kind=author.kind,
                author=author.name[:AUTHOR_MAX_LENGTH],
                execution_id=author.execution_id,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.flush()
            entry = await record(
                session, task.id, "comment", author, {"comment_id": row.id}, at=now
            )
            await session.commit()
            read = CommentRead.model_validate(row)
        self._bus.publish("comment.created", read.model_dump(mode="json"))
        self._bus.publish("activity.created", entry.model_dump(mode="json"))
        return read

    async def update(self, ref: str, comment_id: str, body: str) -> CommentRead:
        """Change the text of a comment (the owner may change any); ``updated_at`` marks it as edited."""
        async with self._session() as session:
            row = await self._row(session, ref, comment_id)
            row.body = body
            row.updated_at = datetime.now(UTC)
            await session.commit()
            read = CommentRead.model_validate(row)
        self._bus.publish("comment.updated", read.model_dump(mode="json"))
        return read

    async def delete(self, ref: str, comment_id: str, actor: Author = SYSTEM) -> None:
        """Delete a comment. Its ``comment`` entry in the activity is replaced by one ``comment_deleted`` entry (who, when);
        the text is gone from everywhere (ADR-058)."""
        async with self._session() as session:
            row = await self._row(session, ref, comment_id)
            task_id = row.task_id
            await session.delete(row)
            await session.execute(
                delete(TaskActivity).where(
                    TaskActivity.task_id == task_id,
                    TaskActivity.kind == "comment",
                    func.json_extract(TaskActivity.data, "$.comment_id") == comment_id,
                )
            )
            entry = await record(session, task_id, "comment_deleted", actor)
            await session.commit()
        self._bus.publish("comment.deleted", {"id": comment_id, "task_id": task_id})
        self._bus.publish("activity.created", entry.model_dump(mode="json"))

    @staticmethod
    async def _row(session: AsyncSession, ref: str, comment_id: str) -> TaskComment:
        task: Task = await ArtifactService._task(session, ref)
        row = await session.get(TaskComment, comment_id)
        if row is None or row.task_id != task.id:
            raise ArtifactError(404, NOT_FOUND)
        return row
