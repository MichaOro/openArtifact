"""Persistence for board tasks. Receives an ``AsyncSession``; never creates its own."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models import Task, TaskStatus
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

    async def get(self, task_id: str) -> Task | None:
        """Return the task or ``None``."""
        return await self._session.get(Task, task_id)

    async def set_status(self, task: Task, status: TaskStatus) -> Task:
        """Move a task to another lane; ``updated_at`` is refreshed automatically."""
        task.status = status.value
        await self._session.flush()
        return task

    async def delete(self, task: Task) -> None:
        """Delete a task."""
        await self._session.delete(task)
        await self._session.flush()
