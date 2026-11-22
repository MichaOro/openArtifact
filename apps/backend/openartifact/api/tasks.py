"""Task API routes (prefix ``/api/tasks``), the browser's way in.

A thin layer over :class:`~openartifact.tasks.service.ArtifactService`, which holds the rules and
publishes the events (see ``GET /api/events``) so that all connected browsers update without polling.
A refused request is an ``ArtifactError``; the application answers it (see ``app.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from openartifact.api.deps import ServiceDep
from openartifact.models import CreatedBy
from openartifact.tasks.schemas import TaskCreate, TaskRead, TaskUpdate

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskRead])
async def list_tasks(service: ServiceDep) -> list[TaskRead]:
    """List all tasks in board order (lane, then position)."""
    return await service.list_all()


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_id: str, service: ServiceDep) -> TaskRead:
    """One task by id."""
    return await service.get(task_id)


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreate, service: ServiceDep) -> TaskRead:
    """Create a task in the given lane.

    ``title`` is required (1-255 chars after trimming), ``body`` is optional, ``status`` must be
    ``backlog``, ``in_progress`` or ``done``; ``parent_id`` makes it a child; ``pipeline_id`` (with
    ``stage_id`` and ``action_id``, default the first ones) says where it starts. Publishes
    ``task.created``.
    """
    return await service.create(payload, created_by=CreatedBy.USER)


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(task_id: str, payload: TaskUpdate, service: ServiceDep) -> TaskRead:
    """Edit a task, move it to another lane, reorder it, give it a parent or a pipeline.

    ``before_id`` places the task before another task of the target lane (``null``: at the end); a
    lane change without ``before_id`` puts it at the top. ``parent_id: null`` removes the parent,
    cycles are rejected with 422. Lane, order, parent and pipeline are locked (409) while the artifact
    is processed. Publishes ``task.moved`` when only lane/order changed, ``task.updated`` for any
    other change (and ``board.resync`` if neighbours had to be renumbered).
    """
    return await service.update(task_id, payload)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: str, service: ServiceDep) -> Response:
    """Delete a task (not while it is processed). Publishes ``task.deleted``; its children become
    parentless (resync)."""
    await service.delete(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
