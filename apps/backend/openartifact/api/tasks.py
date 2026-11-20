"""Task API routes (prefix ``/api/tasks``).

Every successful change is published on the event bus so that all connected
browsers (see ``GET /api/events``) update without polling.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.api.events import EventBusDep
from openartifact.database import get_db_session
from openartifact.tasks.repository import TaskRepository
from openartifact.tasks.schemas import TaskCreate, TaskMove, TaskRead

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")


@router.get("", response_model=list[TaskRead])
async def list_tasks(session: SessionDep) -> list[TaskRead]:
    """List all tasks, newest first."""
    tasks = await TaskRepository(session).list_all()
    return [TaskRead.model_validate(t) for t in tasks]


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreate, session: SessionDep, bus: EventBusDep) -> TaskRead:
    """Create a task in the given lane.

    Validation: ``title`` is required (1-255 chars after trimming), ``body`` is
    optional, ``status`` must be ``backlog``, ``in_progress`` or ``done``.
    Publishes ``task.created``.
    """
    task = await TaskRepository(session).create(payload)
    # Commit before responding/publishing so a reload right after sees the row.
    await session.commit()
    created = TaskRead.model_validate(task)
    bus.publish("task.created", created.model_dump(mode="json"))
    return created


@router.patch("/{task_id}", response_model=TaskRead)
async def move_task(
    task_id: str, payload: TaskMove, session: SessionDep, bus: EventBusDep
) -> TaskRead:
    """Move a task to another lane. Publishes ``task.moved`` (not for a no-op)."""
    repo = TaskRepository(session)
    task = await repo.get(task_id)
    if task is None:
        raise _NOT_FOUND
    if task.status == payload.status.value:
        return TaskRead.model_validate(task)
    await repo.set_status(task, payload.status)
    await session.commit()
    moved = TaskRead.model_validate(task)
    bus.publish("task.moved", moved.model_dump(mode="json"))
    return moved


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: str, session: SessionDep, bus: EventBusDep) -> Response:
    """Delete a task. Publishes ``task.deleted``."""
    repo = TaskRepository(session)
    task = await repo.get(task_id)
    if task is None:
        raise _NOT_FOUND
    await repo.delete(task)
    await session.commit()
    bus.publish("task.deleted", {"id": task_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
