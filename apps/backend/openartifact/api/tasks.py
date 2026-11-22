"""Task API routes (prefix ``/api/tasks``), the browser's way in.

A thin layer over :class:`~openartifact.tasks.service.ArtifactService`, which holds the rules and
publishes the events (see ``GET /api/events``) so that all connected browsers update without polling.
A refused request is an ``ArtifactError``; the application answers it (see ``app.py``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from openartifact.api.deps import ServiceDep
from openartifact.engine.schemas import (
    ExecutionDetail,
    ExecutionList,
    HistoryPolicyResult,
    HistoryPolicyWrite,
)
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


@router.get("/{task_id}/executions", response_model=ExecutionList)
async def list_executions(
    task_id: str, service: ServiceDep, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> ExecutionList:
    """The artifact's executions (one per start, restarts included), newest first, without steps.

    ``items`` has at most ``limit`` (default 100, at most 500) summaries, ``total`` counts all of
    them, ``policy`` is the retention policy (``keep_last``, ``keep_hours``; ``effective_default_keep``
    is what applies when neither is set, ``0``: no limit). ``task_id`` is the id or the number.
    """
    return await service.executions(task_id, limit)


@router.delete("/{task_id}/executions")
async def clear_executions(task_id: str, service: ServiceDep) -> dict[str, int]:
    """Delete every finished execution of the artifact; a running one stays. Returns ``{"deleted": n}``.
    Publishes ``execution.deleted`` for each."""
    return {"deleted": await service.clear_executions(task_id)}


@router.get("/{task_id}/executions/{execution_id}", response_model=ExecutionDetail)
async def get_execution(task_id: str, execution_id: str, service: ServiceDep) -> ExecutionDetail:
    """One execution with all its steps in order (outputs complete, up to the stored limit)."""
    return await service.execution(task_id, execution_id)


@router.delete("/{task_id}/executions/{execution_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_execution(task_id: str, execution_id: str, service: ServiceDep) -> Response:
    """Delete one execution with its steps; 409 while it is running, 404 if unknown.
    Publishes ``execution.deleted``."""
    await service.delete_execution(task_id, execution_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{task_id}/history-policy", response_model=HistoryPolicyResult)
async def set_history_policy(
    task_id: str, payload: HistoryPolicyWrite, service: ServiceDep
) -> HistoryPolicyResult:
    """Set the retention policy of the artifact's execution history and apply it at once.

    ``keep_last`` (1-1000) and ``keep_hours`` (1-8760) are each ``null`` for no limit of that kind;
    when both are set an execution must satisfy both to be kept; when neither is set the application
    default applies. The newest and any running execution are never deleted by it. Returns the
    policy and how many executions were deleted.
    """
    return await service.set_history_policy(task_id, payload)
