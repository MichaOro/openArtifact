"""The activity route (ADR-058): what changed on an artifact and who did it, the same for the browser
(``/api/tasks/{ref}/activity``) and the integration API (``/api/v1/artifacts/{ref}/activity``). Read only."""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Query

from openartifact.activity.schemas import PAGE_DEFAULT, PAGE_MAX, ActivityPage
from openartifact.api.contract import errors
from openartifact.api.deps import ActivityDep

DESCRIPTION = (
    "What changed on the artifact, newest first, in pages: ``created``, ``lane`` (``from``, ``to``: lane titles), "
    "``title``, ``description`` (no text), ``parent``, ``field`` (``field``, ``label``, ``from``, ``to``), ``pipeline``, "
    "``stage``, ``action``, ``run``: ONE entry per delete action on executions (``number`` and ``started_at``, or "
    "``numbers`` and ``count`` for several; ``created_at`` is the deletion time and the actor is who deleted), "
    "``comment`` (``comment_id``; never the text) and ``comment_deleted``. ``actor_kind`` and "
    "``actor_name`` say who did it, as for comments. Executions that still exist are not repeated here: read them "
    "with the executions endpoints. At most 500 entries are kept per artifact. ``next`` is the ``before`` cursor of the "
    "next, older page."
)


def build_activity_router(prefix: str, tags: list[str | Enum]) -> APIRouter:
    """The activity route under ``prefix`` (``{ref}``: the id or the number of the artifact)."""
    router = APIRouter(prefix=prefix, tags=tags)

    @router.get(
        "/{ref}/activity",
        response_model=ActivityPage,
        summary="List the activity of an artifact",
        description=DESCRIPTION,
        responses=errors(404, 422),
    )
    async def list_activity(
        ref: str,
        service: ActivityDep,
        limit: Annotated[int, Query(ge=1, le=PAGE_MAX)] = PAGE_DEFAULT,
        before: Annotated[str | None, Query(max_length=200)] = None,
    ) -> ActivityPage:
        return await service.activity(ref, limit, before)

    return router
