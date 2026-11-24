"""Guards (ADR-060): ``/api/guards`` for the editor and ``/api/v1/guards`` for integrations, the same routes; the
editor also gets the templates and a preview, the integrations the heartbeat of a running execution."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from openartifact.api.contract import errors
from openartifact.api.deps import get_engine
from openartifact.engine.runner import RunEngine
from openartifact.guards.schemas import (
    GuardCreate,
    GuardEnabled,
    GuardPreview,
    GuardRead,
    GuardWrite,
    HeartbeatRead,
    HeartbeatWrite,
)
from openartifact.guards.service import GuardService, templates

DESCRIPTION = (
    "A guard watches a pipeline, a stage or an action (``scope_type``, ``scope_id``) of its pipeline while it runs. "
    "``trigger``: ``event`` (``events``: ``enter``, ``pass``, ``error``, ``leave``, ``fail``; the flow waits for the "
    "guard) or ``interval`` (``every_seconds`` at least the minimum interval, ``for_seconds``: the condition must hold "
    "that long, ``cooldown_seconds``: quiet after firing). ``when``: a condition tree of the ``guard`` schema "
    "(``GET /api/rules/schemas/guard``: ``runs``, ``elapsed``, ``idle``, ``errors``, ``passes``, ``guard.runs``, "
    "``last_status``, ``cost``, ``var.NAME``). ``consequence``: ``pause``, ``abort``, ``continue`` or ``run_action`` "
    "(the guard's own action, ``definition_id``; On Error does the ``fallback``); ``notify`` and ``handover`` are not "
    "available yet (422). ``escalation``: steps ``from_firing`` k on, every ``every_runs`` rounds or ``every_seconds``. "
    "A guard cannot watch a guard (422)."
)


def get_guards(request: Request) -> GuardService:
    service: GuardService = request.app.state.guards
    return service


GuardsDep = Annotated[GuardService, Depends(get_guards)]
EngineDep = Annotated[RunEngine, Depends(get_engine)]


class TemplateRead(BaseModel):
    key: str
    name: str
    summary: str
    scope_types: list[str]
    guard: dict[str, Any]
    has_action: bool


class FromTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str = Field(min_length=1, max_length=40)
    pipeline_id: str = Field(min_length=1, max_length=36)
    scope_type: str = Field(min_length=1, max_length=16)
    scope_id: str | None = Field(default=None, max_length=36)
    name: str | None = Field(default=None, min_length=1, max_length=120)


def build_guards_router(prefix: str, tags: list[str | Enum], *, editor: bool) -> APIRouter:
    """The guard routes under ``{prefix}/guards``; ``editor`` adds templates and the preview."""
    router = APIRouter(prefix=f"{prefix}/guards", tags=tags)
    name = "" if editor else "v1_"

    @router.get(
        "",
        response_model=list[GuardRead],
        name=f"{name}list_guards",
        summary="List guards",
        description=DESCRIPTION,
        responses=errors(422),
    )
    async def list_guards(
        service: GuardsDep, pipeline_id: Annotated[str | None, Query(max_length=36)] = None
    ) -> list[GuardRead]:
        return await service.list(pipeline_id)

    @router.post(
        "",
        response_model=GuardRead,
        status_code=status.HTTP_201_CREATED,
        name=f"{name}create_guard",
        summary="Create a guard",
        description=DESCRIPTION,
        responses=errors(404, 422, write=True, body=True),
    )
    async def create_guard(payload: GuardCreate, service: GuardsDep) -> GuardRead:
        return await service.create(payload)

    if editor:

        @router.get(
            "/templates",
            response_model=list[TemplateRead],
            summary="List the guard templates",
            description="The guards shipped as templates: Stall, Runtime and Health guard.",
        )
        async def list_templates() -> list[TemplateRead]:
            return [
                TemplateRead(
                    **{k: t[k] for k in ("key", "name", "summary", "scope_types", "guard")},
                    has_action="action" in t,
                )
                for t in templates().values()
            ]

        @router.post(
            "/from-template",
            response_model=GuardRead,
            status_code=status.HTTP_201_CREATED,
            summary="Create a guard from a template",
            description="The template's guard on the given scope, with its own action when the template has one.",
            responses=errors(404, 422, write=True, body=True),
        )
        async def create_from_template(payload: FromTemplate, service: GuardsDep) -> GuardRead:
            return await service.from_template(
                payload.template,
                payload.pipeline_id,
                payload.scope_type,
                payload.scope_id,
                payload.name,
            )

        @router.post(
            "/preview",
            response_model=GuardPreview,
            summary="Which running scopes a guard would fire on now",
            description=(
                "Evaluates the guard's condition over the facts of every scope it watches that runs now (no trigger, "
                "escalation or cap is applied and nothing is fired)."
            ),
            responses=errors(404, 422, write=True, body=True),
        )
        async def preview_guard(payload: GuardCreate, engine: EngineDep) -> GuardPreview:
            data = payload.model_dump(mode="json")
            if data["scope_type"] == "pipeline":
                data["scope_id"] = payload.pipeline_id
            running, matches = engine.preview_guard(data)
            return GuardPreview(running_scopes=running, matching=len(matches), matches=matches)

    @router.get(
        "/{guard_id}",
        response_model=GuardRead,
        name=f"{name}get_guard",
        summary="Get a guard",
        responses=errors(404, 422),
    )
    async def get_guard(guard_id: str, service: GuardsDep) -> GuardRead:
        return await service.get(guard_id)

    @router.patch(
        "/{guard_id}",
        response_model=GuardRead,
        name=f"{name}update_guard",
        summary="Change a guard",
        description=DESCRIPTION + " A field that is left out keeps its value.",
        responses=errors(404, 422, write=True, body=True),
    )
    async def update_guard(guard_id: str, payload: GuardWrite, service: GuardsDep) -> GuardRead:
        return await service.update(guard_id, payload)

    @router.put(
        "/{guard_id}/enabled",
        response_model=GuardRead,
        name=f"{name}set_guard_enabled",
        summary="Switch a guard on or off",
        description="Off acts on running executions at once (the guard no longer fires); on acts on the next start.",
        responses=errors(404, 422, write=True, body=True),
    )
    async def set_guard_enabled(
        guard_id: str, payload: GuardEnabled, service: GuardsDep
    ) -> GuardRead:
        return await service.set_enabled(guard_id, payload.enabled)

    @router.delete(
        "/{guard_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"{name}delete_guard",
        summary="Delete a guard",
        description="Its own action stays (an action definition like any other).",
        responses=errors(404, 422, write=True),
    )
    async def delete_guard(guard_id: str, service: GuardsDep) -> Response:
        await service.delete(guard_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


def build_heartbeat_router(prefix: str, tags: list[str | Enum]) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=tags)

    @router.post(
        "/executions/{execution_id}/heartbeat",
        response_model=HeartbeatRead,
        summary="Say that a running execution still makes progress",
        description=(
            "Restarts the stall clock of a running execution (the ``idle`` fact of its guards), with an optional short "
            "``note`` (200 characters). Recorded in the execution's guard state (the last one and a count), not in the "
            "activity. 404: no such execution; 409: it is not running; 429: closer than the minimum spacing."
        ),
        responses=errors(404, 409, 422, 429, write=True, body=True),
    )
    async def heartbeat(
        execution_id: str, payload: HeartbeatWrite, engine: EngineDep
    ) -> dict[str, Any]:
        return await engine.heartbeat(execution_id, payload.note)

    return router
