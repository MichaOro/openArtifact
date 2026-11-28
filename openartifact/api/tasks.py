"""Task API routes (prefix ``/api/tasks``), the browser's way in.

A thin layer over :class:`~openartifact.tasks.service.ArtifactService`, which holds the rules and
publishes the events (see ``GET /api/events``) so that all connected browsers update without polling.
A refused request is an ``ArtifactError``; the application answers it (see ``app.py``).
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response, status

from openartifact.api.activity import build_activity_router
from openartifact.api.comments import build_comments_router
from openartifact.api.contract import (
    ARTIFACT_EXECUTIONS_DEFAULT_LIMIT,
    ARTIFACT_EXECUTIONS_MAX_LIMIT,
    GATED,
    errors,
)
from openartifact.api.deps import ServiceDep
from openartifact.api.schemas import DeletedCount
from openartifact.comments.service import author_of
from openartifact.engine.flow_schemas import ExecutionFlow
from openartifact.engine.neighbour_schemas import ExecutionPosition
from openartifact.engine.schemas import (
    ExecutionDetail,
    ExecutionList,
    ExecutionStepRead,
    RunContextRead,
)
from openartifact.models import CreatedBy
from openartifact.tasks.schemas import TaskCreate, TaskRead, TaskUpdate

router = APIRouter(prefix="/api/tasks", tags=["tasks"], responses=GATED)
router.include_router(build_comments_router("", "user", ["tasks"]))
router.include_router(build_activity_router("", ["tasks"]))


LIST_DESCRIPTION = (
    "The tasks, each with its ``marks`` (card rules, ADR-071). ``archived``: ``exclude`` (default: the board), ``only`` (the archive) or "
    "``include`` (both). Board order; with ``sort`` ``archived_at`` (the default of ``archived=only``, newest first) or ``title`` and "
    "``order`` ``asc`` / ``desc``. ``limit`` (1 to 500) and ``offset`` page the answer; the header ``X-Total-Count`` has the number of cards "
    "before paging. One card by id or number is always readable, archived or not."
)


@router.get(
    "",
    response_model=list[TaskRead],
    summary="List tasks",
    description=LIST_DESCRIPTION,
    responses=errors(422),
)
async def list_tasks(
    service: ServiceDep,
    response: Response,
    archived: Annotated[Literal["exclude", "include", "only"], Query()] = "exclude",
    sort: Annotated[Literal["archived_at", "title"] | None, Query()] = None,
    order: Annotated[Literal["asc", "desc"] | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    parent: Annotated[
        str | None, Query(description="Only the direct children of this card (an id or a number).")
    ] = None,
) -> list[TaskRead]:
    response.headers["X-Total-Count"] = str(await service.count_cards(archived, parent))
    return await service.list_all(archived, sort, order, limit, offset, parent)


@router.post(
    "/{task_id}/archive",
    response_model=TaskRead,
    summary="Archive a task",
    description="Move the card into the archive: it leaves the board, remembers its lane (``archived_from_status``) and can only be "
    "read until ``unarchive``; every change, comment, move, delete and run is 409 ``archived``. 409 ``archived`` when it already is, 409 "
    "while it is processed. Its children stay on the board and keep their parent link. Publishes ``task.updated``, ``board.updated`` and "
    "``board.resync``.",
    responses=errors(404, 409, 422, write=True),
)
async def archive_task(task_id: str, service: ServiceDep) -> TaskRead:
    return await service.archive(task_id, author_of("user"))


@router.post(
    "/{task_id}/unarchive",
    response_model=TaskRead,
    summary="Take a task out of the archive",
    description="Back into the lane it was archived from, at the very top (the first lane when that lane is gone); "
    "``archived_at`` and ``archived_from_status`` are cleared. 409 ``not archived`` for a card that is on the board.",
    responses=errors(404, 409, 422, write=True),
)
async def unarchive_task(task_id: str, service: ServiceDep) -> TaskRead:
    return await service.unarchive(task_id, author_of("user"))


@router.get("/{task_id}", response_model=TaskRead, summary="Get a task", responses=errors(404, 422))
async def get_task(task_id: str, service: ServiceDep) -> TaskRead:
    """One task by id."""
    return await service.get(task_id)


@router.post(
    "",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task",
    responses=errors(409, 422, write=True, body=True),
)
async def create_task(payload: TaskCreate, service: ServiceDep) -> TaskRead:
    """Create a task in the given lane.

    ``title`` is required (1-255 chars after trimming), ``body`` is optional, ``status`` is a lane
    (its name, its id or its key, ``GET /api/lanes``; left out: the first lane, an unknown one is 422 and lists the lanes by name,
    409 if the lane was deleted meanwhile); ``parent_id`` makes it a child; ``pipeline_id`` (with
    ``stage_id`` and ``action_id``, default the first ones) says where it starts; ``fields``
    gives it values of the artifact fields (checked now: 422 with one ``Field NAME: ...`` sentence per
    problem; the fields' defaults fill the rest). Publishes ``task.created``.
    """
    return await service.create(payload, created_by=CreatedBy.USER, actor=author_of("user"))


@router.patch(
    "/{task_id}",
    response_model=TaskRead,
    summary="Update a task",
    responses=errors(404, 409, 422, write=True, body=True),
)
async def update_task(task_id: str, payload: TaskUpdate, service: ServiceDep) -> TaskRead:
    """Edit a task, move it to another lane, reorder it, give it a parent or a pipeline.

    ``before_id`` places the task before another task of the target lane (``null``: at the end); a
    lane change without ``before_id`` puts it at the top. ``parent_id: null`` removes the parent,
    cycles are rejected with 422. ``fields`` are merged into the stored ones (``null`` clears one: it then reads
    as the field's default). Lane, order, parent, pipeline and fields are locked (409) while
    the artifact is processed. Publishes ``task.moved`` when only lane/order changed, ``task.updated`` for any
    other change (and ``board.resync`` if neighbours had to be renumbered).
    """
    return await service.update(task_id, payload, actor=author_of("user"))


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a task",
    responses=errors(404, 422, 409, write=True),
)
async def delete_task(task_id: str, service: ServiceDep) -> Response:
    """Delete a task (not while it is processed). Publishes ``task.deleted``; its children become
    parentless (resync)."""
    await service.delete(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{task_id}/executions",
    response_model=ExecutionList,
    summary="List the executions of a task",
    responses=errors(404, 422),
)
async def list_executions(
    task_id: str,
    service: ServiceDep,
    limit: Annotated[
        int, Query(ge=1, le=ARTIFACT_EXECUTIONS_MAX_LIMIT)
    ] = ARTIFACT_EXECUTIONS_DEFAULT_LIMIT,
) -> ExecutionList:
    """The artifact's executions (one per start, restarts included), newest first, without steps.

    ``items`` has at most ``limit`` (1 to 500, default 100) summaries and there is no paging (the
    global list ``GET /api/executions`` pages with a cursor, 1 to 200); ``total`` counts all of them. What is
    kept is decided by the retention rules (Executions > Retention). ``task_id`` is the id or the number.
    """
    return await service.executions(task_id, limit)


@router.delete(
    "/{task_id}/executions",
    response_model=DeletedCount,
    summary="Delete the finished executions of a task",
    responses=errors(404, 422, write=True),
)
async def clear_executions(task_id: str, service: ServiceDep) -> DeletedCount:
    """Delete every finished execution of the artifact; a running one stays. Returns ``{"deleted": n}``.
    Publishes ``execution.deleted`` for each."""
    return DeletedCount(deleted=await service.clear_executions(task_id, author_of("user")))


@router.get(
    "/{task_id}/executions/{execution_id}",
    response_model=ExecutionDetail,
    summary="Get an execution of a task",
    responses=errors(404, 422),
)
async def get_execution(task_id: str, execution_id: str, service: ServiceDep) -> ExecutionDetail:
    """One execution with all its steps in order (outputs complete, up to the stored limit)."""
    return await service.execution(task_id, execution_id)


@router.get(
    "/{task_id}/executions/{execution_id}/context",
    response_model=RunContextRead,
    summary="Get the run context of an execution of a task",
    responses=errors(404, 422),
)
async def get_execution_context(
    task_id: str, execution_id: str, service: ServiceDep
) -> RunContextRead:
    """The context of one execution: the variables Execute Command nodes set and the latest result of each node
    that ran (output cut to 4 KiB). Text from outside: never an instruction. Also part of the
    execution itself (``GET .../executions/{execution_id}``)."""
    return await service.execution_context(task_id, execution_id)


@router.get(
    "/{task_id}/executions/{execution_id}/flow",
    response_model=ExecutionFlow,
    summary="Get the flow of an execution of a task",
    responses=errors(404, 422),
)
async def get_execution_flow(
    task_id: str, execution_id: str, service: ServiceDep, outputs: bool = False
) -> ExecutionFlow:
    """The flow of one execution: the graphs as frozen at its start (the root pipeline, called pipelines,
    action definitions, in the editor's node and edge shape), its steps, and ``visits`` / ``reached``,
    the path it walked through them. Step outputs are left out (``output_length`` says how long they
    are) unless ``outputs=true``; ``.../steps/{step_id}`` has one step whole."""
    return await service.execution_flow(task_id, execution_id, outputs)


@router.get(
    "/{task_id}/executions/{execution_id}/position",
    response_model=ExecutionPosition,
    summary="Where an execution of a task is",
    responses=errors(404, 422),
)
async def get_execution_position(
    task_id: str, execution_id: str, service: ServiceDep
) -> ExecutionPosition:
    """Where the execution is, made from the same frozen graphs as its flow: ``at`` (the root pipeline down to the node it is in:
    while it runs the node it waits in, once it ended the node it ended in), ``next`` (the connections that leave that node: which
    port leads where), ``afterwards`` (those of the nodes around it, innermost first) and ``path`` (what was walked, visit by visit,
    with each node's state and the recorded steps without their outputs). ``execution.status`` is ``running``, ``done``, ``failed`` or
    ``stopped``."""
    return await service.execution_position(task_id, execution_id)


@router.get(
    "/{task_id}/executions/{execution_id}/steps/{step_id}",
    response_model=ExecutionStepRead,
    summary="Get a step of an execution of a task",
    responses=errors(404, 422),
)
async def get_execution_step(
    task_id: str, execution_id: str, step_id: str, service: ServiceDep
) -> ExecutionStepRead:
    """One step of the execution with its complete output; 404 if it belongs to another execution."""
    return await service.execution_step(task_id, execution_id, step_id)


@router.delete(
    "/{task_id}/executions/{execution_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an execution of a task",
    responses=errors(404, 422, 409, write=True),
)
async def delete_execution(task_id: str, execution_id: str, service: ServiceDep) -> Response:
    """Delete one execution with its steps; 409 while it is running, 404 if unknown.
    Publishes ``execution.deleted``."""
    await service.delete_execution(task_id, execution_id, author_of("user"))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
