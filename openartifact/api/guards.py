"""Guards (ADR-060): ``/api/guards`` (the library of definitions) and ``/api/guard-attachments`` (where they watch)
for the editor, the same under ``/api/v1`` for integrations; the editor also gets a preview, the integrations the
heartbeat of a running execution."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel

from openartifact.api.contract import errors
from openartifact.api.deps import get_engine
from openartifact.engine.runner import RunEngine
from openartifact.guards.schemas import (
    AttachmentCreate,
    AttachmentRead,
    FromTemplate,
    GuardDefinitionCreate,
    GuardDefinitionRead,
    GuardDefinitionWrite,
    GuardEnabled,
    GuardPreview,
    HeartbeatRead,
    HeartbeatWrite,
    PreviewRequest,
)
from openartifact.guards.service import GuardService, templates

DESCRIPTION = (
    "A guard definition (the library) says what a guard is; it watches nothing until it is attached to a scope "
    "(``/guard-attachments``). ``scope_types``: the kinds of scope it may be attached to (``pipeline``, ``stage``, "
    "``action``). ``trigger``: ``event`` (``events``: ``enter``, ``pass``, ``error``, ``leave``, ``fail``; the flow "
    "waits for the guard) or ``interval`` (``every_seconds`` at least the minimum interval, ``for_seconds``: the "
    "condition must hold that long, ``cooldown_seconds``: quiet after firing). ``when``: a condition tree of the "
    "``guard`` schema (``GET /api/rules/schemas/guard``: ``runs``, ``elapsed``, ``idle``, ``errors``, ``passes``, "
    "``guard.runs``, ``last_status``, ``cost``, ``var.NAME``). ``consequence``: ``pause``, ``abort``, ``continue`` or "
    "``run_action`` (the guard's own action, ``action_id``; On Error does the ``fallback``); ``notify`` and "
    "``handover`` are not available yet (422). ``escalation``: steps ``from_firing`` k on, every ``every_runs`` rounds "
    "or ``every_seconds``. A guard cannot watch a guard (422). A change acts on every place it is attached to "
    "(``used_by``) at the next start of a run."
)
ATTACH_DESCRIPTION = (
    "An attachment puts a guard definition on a pipeline (``scope_type: pipeline``, ``scope_id`` may be left out), a "
    "stage or an action of it and switches it on or off there. 422 when the definition may not watch that kind of "
    "scope (its ``scope_types``) or the scope is not part of the pipeline; 409 when it is attached there already. An "
    "attachment goes with its pipeline and with its stage or action."
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


def build_guards_router(prefix: str, tags: list[str | Enum], *, editor: bool) -> APIRouter:
    """The guard routes under ``{prefix}/guards`` and ``{prefix}/guard-attachments``; ``editor`` adds the preview."""
    router = APIRouter(prefix=prefix, tags=tags)
    name = "" if editor else "v1_"

    @router.get(
        "/guards",
        response_model=list[GuardDefinitionRead],
        name=f"{name}list_guards",
        summary="List the guard library",
        description=DESCRIPTION
        + " With ``pipeline_id``: only the guards attached to that pipeline, with their attachments there.",
        responses=errors(422),
    )
    async def list_guards(
        service: GuardsDep, pipeline_id: Annotated[str | None, Query(max_length=36)] = None
    ) -> list[GuardDefinitionRead]:
        return await service.list(pipeline_id)

    @router.post(
        "/guards",
        response_model=GuardDefinitionRead,
        status_code=status.HTTP_201_CREATED,
        name=f"{name}create_guard",
        summary="Create a guard definition",
        description=DESCRIPTION,
        responses=errors(422, write=True, body=True),
    )
    async def create_guard(
        payload: GuardDefinitionCreate, service: GuardsDep
    ) -> GuardDefinitionRead:
        return await service.create(payload)

    @router.get(
        "/guards/templates",
        response_model=list[TemplateRead],
        name=f"{name}list_guard_templates",
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
        "/guards/from-template",
        response_model=GuardDefinitionRead,
        status_code=status.HTTP_201_CREATED,
        name=f"{name}create_guard_from_template",
        summary="Create a guard definition from a template",
        description="The template's guard in the library, with its own action when the template has one.",
        responses=errors(404, 422, write=True, body=True),
    )
    async def create_from_template(
        payload: FromTemplate, service: GuardsDep
    ) -> GuardDefinitionRead:
        return await service.from_template(payload.template, payload.name, payload.description)

    if editor:

        @router.post(
            "/guards/preview",
            response_model=GuardPreview,
            summary="Which running scopes a guard would fire on now",
            description=(
                "Evaluates a condition over the facts of every running scope the definition (``guard_id``) is "
                "attached to (no trigger, escalation or cap is applied and nothing is fired). Without ``guard_id`` "
                "nothing runs that it watches."
            ),
            responses=errors(422, write=True, body=True),
        )
        async def preview_guard(
            payload: PreviewRequest, service: GuardsDep, engine: EngineDep
        ) -> GuardPreview:
            running, matches = 0, []
            if payload.guard_id:
                when = payload.when.model_dump(mode="json")
                for place in await service.attachments_of(payload.guard_id):
                    count, found = engine.preview_guard(
                        {
                            "id": place.id,
                            "scope_type": place.scope_type,
                            "scope_id": place.scope_id,
                            "when": when,
                        }
                    )
                    running += count
                    matches += found
            return GuardPreview(running_scopes=running, matching=len(matches), matches=matches)

    @router.get(
        "/guards/{guard_id}",
        response_model=GuardDefinitionRead,
        name=f"{name}get_guard",
        summary="Get a guard definition",
        responses=errors(404, 422),
    )
    async def get_guard(guard_id: str, service: GuardsDep) -> GuardDefinitionRead:
        return await service.get(guard_id)

    @router.patch(
        "/guards/{guard_id}",
        response_model=GuardDefinitionRead,
        name=f"{name}update_guard",
        summary="Change a guard definition",
        description=DESCRIPTION
        + " A field that is left out keeps its value. Narrowing ``scope_types`` below where it is attached is "
        "refused (422).",
        responses=errors(404, 422, write=True, body=True),
    )
    async def update_guard(
        guard_id: str, payload: GuardDefinitionWrite, service: GuardsDep
    ) -> GuardDefinitionRead:
        return await service.update(guard_id, payload)

    @router.delete(
        "/guards/{guard_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"{name}delete_guard",
        summary="Delete a guard definition",
        description="Refused with 409 while it is attached anywhere. Its own action stays (an action definition).",
        responses=errors(404, 409, 422, write=True),
    )
    async def delete_guard(guard_id: str, service: GuardsDep) -> Response:
        await service.delete(guard_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get(
        "/guard-attachments",
        response_model=list[AttachmentRead],
        name=f"{name}list_guard_attachments",
        summary="List where guards are attached",
        description=ATTACH_DESCRIPTION,
        responses=errors(422),
    )
    async def list_attachments(
        service: GuardsDep, pipeline_id: Annotated[str | None, Query(max_length=36)] = None
    ) -> list[AttachmentRead]:
        return await service.attachments(pipeline_id)

    @router.post(
        "/guard-attachments",
        response_model=AttachmentRead,
        status_code=status.HTTP_201_CREATED,
        name=f"{name}attach_guard",
        summary="Attach a guard to a pipeline, a stage or an action",
        description=ATTACH_DESCRIPTION,
        responses=errors(404, 409, 422, write=True, body=True),
    )
    async def attach_guard(payload: AttachmentCreate, service: GuardsDep) -> AttachmentRead:
        return await service.attach(payload)

    @router.get(
        "/guard-attachments/{attachment_id}",
        response_model=AttachmentRead,
        name=f"{name}get_guard_attachment",
        summary="Get a guard attachment",
        responses=errors(404, 422),
    )
    async def get_attachment(attachment_id: str, service: GuardsDep) -> AttachmentRead:
        return await service.attachment(attachment_id)

    @router.put(
        "/guard-attachments/{attachment_id}/enabled",
        response_model=AttachmentRead,
        name=f"{name}set_guard_enabled",
        summary="Switch a guard on or off where it is attached",
        description="Off acts on running executions at once (the guard no longer fires there); on acts on the next start.",
        responses=errors(404, 422, write=True, body=True),
    )
    async def set_guard_enabled(
        attachment_id: str, payload: GuardEnabled, service: GuardsDep
    ) -> AttachmentRead:
        return await service.set_enabled(attachment_id, payload.enabled)

    @router.delete(
        "/guard-attachments/{attachment_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"{name}detach_guard",
        summary="Detach a guard",
        description="The guard no longer watches that scope; its definition stays in the library.",
        responses=errors(404, 422, write=True),
    )
    async def detach_guard(attachment_id: str, service: GuardsDep) -> Response:
        await service.detach(attachment_id)
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
