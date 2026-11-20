"""Persistence for board tasks. Receives an ``AsyncSession``; never creates its own."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models import Task
from openartifact.tasks.schemas import TaskCreate, TaskUpdate


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

    async def update(self, task: Task, data: TaskUpdate) -> set[str]:
        """Apply the sent fields; return the names that actually changed.

        ``updated_at`` is only refreshed when something changed.
        """
        sent = data.model_fields_set
        new_values: dict[str, str | None] = {}
        if "title" in sent and data.title is not None:
            new_values["title"] = data.title
        if "body" in sent:
            new_values["body"] = data.body
        if "status" in sent and data.status is not None:
            new_values["status"] = data.status.value
        changed = {name for name, value in new_values.items() if getattr(task, name) != value}
        for name in changed:
            setattr(task, name, new_values[name])
        if changed:
            await self._session.flush()
        return changed

    async def delete(self, task: Task) -> None:
        """Delete a task."""
        await self._session.delete(task)
        await self._session.flush()
