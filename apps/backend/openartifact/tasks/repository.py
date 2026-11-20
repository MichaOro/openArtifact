"""Persistence for board tasks. Receives an ``AsyncSession``; never creates its own."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models import Task
from openartifact.tasks.schemas import TaskCreate


class TaskRepository:
    """Database access for :class:`~openartifact.models.Task`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: TaskCreate) -> Task:
        """Insert a task and flush it so defaults (timestamps) are populated."""
        task = Task(
            id=str(uuid.uuid4()),
            title=data.title,
            body=data.body,
            status=data.status.value,
        )
        self._session.add(task)
        await self._session.flush()
        return task

    async def list_all(self) -> Sequence[Task]:
        """Return all tasks, newest first."""
        result = await self._session.execute(select(Task).order_by(Task.created_at.desc(), Task.id))
        return result.scalars().all()
