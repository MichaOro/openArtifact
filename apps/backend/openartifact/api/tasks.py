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
from openartifact.tasks.repository import ParentError, PlacementError, TaskRepository
from openartifact.tasks.schemas import TaskCreate, TaskRead, TaskUpdate

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
async def update_task(
    task_id: str, payload: TaskUpdate, session: SessionDep, bus: EventBusDep
) -> TaskRead:
    """Edit a task, move it to another lane and/or reorder it inside a lane.

    ``before_id`` places the task before another task of the target lane (``null``: at the
    end); a lane change without ``before_id`` puts it at the top. ``parent_id`` sets or (``null``)
    removes the parent artifact; cycles are rejected with 422. Publishes ``task.moved``
    when only lane/order changed, ``task.updated`` for any other change (and ``board.resync``
    if neighbours had to be renumbered); nothing when the request changes nothing.
    """
    repo = TaskRepository(session)
    task = await repo.get(task_id)
    if task is None:
        raise _NOT_FOUND
    try:
        result = await repo.update(task, payload)
    except (PlacementError, ParentError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if not result.changed and not result.renumbered:
        return TaskRead.model_validate(task)
    await session.commit()
    updated = TaskRead.model_validate(task)
    # lane/position only -> "moved"; anything touching the content -> "updated"
    moved_only = result.changed <= {"status", "position"}
    bus.publish("task.moved" if moved_only else "task.updated", updated.model_dump(mode="json"))
    if result.renumbered:
        bus.publish("board.resync", {})  # other tasks of the lane got new positions
    return updated


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: str, session: SessionDep, bus: EventBusDep) -> Response:
    """Delete a task. Publishes ``task.deleted``; its children become parentless (resync)."""
    repo = TaskRepository(session)
    task = await repo.get(task_id)
    if task is None:
        raise _NOT_FOUND
    detached = await repo.delete(task)
    await session.commit()
    bus.publish("task.deleted", {"id": task_id})
    if detached:
        bus.publish("board.resync", {})  # the children lost their parent
    return Response(status_code=status.HTTP_204_NO_CONTENT)
