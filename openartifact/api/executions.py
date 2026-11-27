"""The global execution list (``GET /api/executions``), the browser's view over all artifacts.

Deleting one stays with the artifact (``DELETE /api/tasks/{id}/executions/{execution_id}``); ``POST /api/executions/delete``
deletes several, of any artifacts, at once (the list page's bulk action). The same list
is offered to scripts as ``GET /api/v1/executions`` and to agents as the MCP tool ``list_all_executions``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from openartifact.api.contract import GATED, errors
from openartifact.api.deps import ServiceDep
from openartifact.api.schemas import ExecutionsDelete, ExecutionsDeleted
from openartifact.comments.service import author_of
from openartifact.engine.history_query import DEFAULT_LIMIT, MAX_LIMIT
from openartifact.engine.schemas import ExecutionsPage

router = APIRouter(prefix="/api/executions", tags=["executions"], responses=GATED)

LIST_DESCRIPTION = """The executions of all artifacts, newest first (by start time, then id), without steps.

Filters (all optional, combined with AND): ``status`` and ``started_by`` are comma separated lists
(``running,done,failed,stopped`` / ``user,api,mcp,system``); ``pipeline`` matches the pipeline id exactly
or the stored pipeline name as a case-insensitive substring; ``q`` is a case-insensitive substring of the
artifact title, pipeline name or note, or an artifact number (``12``, ``#12``); ``since`` / ``until`` are
ISO 8601 times (UTC when no offset is given), both inclusive, on the start time; ``dry_run`` is ``only`` (the dry runs) or
``exclude`` (the real runs), both when left out; ``observed`` is ``only`` (the runs of an observed pipeline, ADR-088, which are dry runs
too) or ``exclude`` (leave them out), both when left out. An invalid value is 422.

``limit`` is 1 to 200 (default 50). ``next_cursor`` goes into ``cursor`` for the next page and is ``null`` on
the last; paging is stable while executions are added or deleted. ``total`` counts everything the filters
match, ``summary`` is unfiltered (``failed_24h`` / ``done_24h``: real runs started in the last 24 hours, dry runs are left out).
Each item has its ``task`` (id, number, title) and ``pipeline_exists`` (the pipeline still exists)."""


@router.get(
    "",
    response_model=ExecutionsPage,
    description=LIST_DESCRIPTION,
    summary="List the executions of all artifacts",
    responses=errors(422),
)
async def list_all_executions(
    service: ServiceDep,
    status: str | None = None,
    started_by: str | None = None,
    pipeline: str | None = None,
    q: str | None = None,
    since: str | None = None,
    until: str | None = None,
    dry_run: str | None = None,
    observed: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> ExecutionsPage:
    return await service.all_executions(
        status=status,
        started_by=started_by,
        pipeline=pipeline,
        q=q,
        since=since,
        until=until,
        dry_run=dry_run,
        observed=observed,
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "/delete",
    response_model=ExecutionsDeleted,
    summary="Delete several executions",
    responses=errors(422, write=True, body=True),
)
async def delete_executions(payload: ExecutionsDelete, service: ServiceDep) -> ExecutionsDeleted:
    """Delete the finished executions among ``ids`` (1 to 500, of any artifacts) with their steps. A running
    execution is not deleted and counted in ``skipped_running``; an id that does not exist is already gone."""
    deleted, skipped = await service.delete_executions(payload.ids, author_of("user"))
    return ExecutionsDeleted(deleted=deleted, skipped_running=skipped)
