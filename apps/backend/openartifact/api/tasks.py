"""Task API routes (prefix ``/api/tasks``), the browser's way in.

A thin layer over :class:`~openartifact.tasks.service.ArtifactService`, which holds the rules and
publishes the events (see ``GET /api/events``) so that all connected browsers update without polling.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from openartifact.tasks.schemas import TaskCreate, TaskRead, TaskUpdate
from openartifact.tasks.service import ArtifactError, ArtifactService

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def get_artifacts(request: Request) -> ArtifactService:
    """The application's artifact service."""
    service: ArtifactService = request.app.state.artifacts
    return service


ServiceDep = Annotated[ArtifactService, Depends(get_artifacts)]


def to_http(error: ArtifactError) -> HTTPException:
    """The HTTP form of a refused request."""
    return HTTPException(status_code=error.status, detail=error.message)


@router.get("", response_model=list[TaskRead])
async def list_tasks(service: ServiceDep) -> list[TaskRead]:
    """List all tasks in board order (lane, then position)."""
    return await service.list_all()


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_id: str, service: ServiceDep) -> TaskRead:
    """One task by id."""
    try:
        return await service.get(task_id)
    except ArtifactError as error:
        raise to_http(error) from error


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreate, service: ServiceDep) -> TaskRead:
    """Create a task in the given lane.

    ``title`` is required (1-255 chars after trimming), ``body`` is optional, ``status`` must be
    ``backlog``, ``in_progress`` or ``done``; ``parent_id`` makes it a child; ``pipeline_id`` (with
    ``stage_id`` and ``action_id``, default the first ones) says where it starts. Publishes
    ``task.created``.
    """
    try:
        return await service.create(payload, created_by="user")
    except ArtifactError as error:
        raise to_http(error) from error


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(task_id: str, payload: TaskUpdate, service: ServiceDep) -> TaskRead:
    """Edit a task, move it to another lane, reorder it, give it a parent or a pipeline.

    ``before_id`` places the task before another task of the target lane (``null``: at the end); a
    lane change without ``before_id`` puts it at the top. ``parent_id: null`` removes the parent,
    cycles are rejected with 422. Lane, order, parent and pipeline are locked (409) while the artifact
    is processed. Publishes ``task.moved`` when only lane/order changed, ``task.updated`` for any
    other change (and ``board.resync`` if neighbours had to be renumbered).
    """
    try:
        return await service.update(task_id, payload)
    except ArtifactError as error:
        raise to_http(error) from error


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: str, service: ServiceDep) -> Response:
    """Delete a task (not while it is processed). Publishes ``task.deleted``; its children become
    parentless (resync)."""
    try:
        await service.delete(task_id)
    except ArtifactError as error:
        raise to_http(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
