"""Task API routes (prefix ``/api/tasks``)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.database import get_db_session
from openartifact.tasks.repository import TaskRepository
from openartifact.tasks.schemas import TaskCreate, TaskRead

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("", response_model=list[TaskRead])
async def list_tasks(session: SessionDep) -> list[TaskRead]:
    """List all tasks, newest first."""
    tasks = await TaskRepository(session).list_all()
    return [TaskRead.model_validate(t) for t in tasks]


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreate, session: SessionDep) -> TaskRead:
    """Create a task in the given lane.

    Validation: ``title`` is required (1-255 chars after trimming), ``body`` is
    optional, ``status`` must be ``backlog``, ``in_progress`` or ``done``.
    """
    task = await TaskRepository(session).create(payload)
    # Commit before responding so a reload right after the response sees the row.
    await session.commit()
    return TaskRead.model_validate(task)
