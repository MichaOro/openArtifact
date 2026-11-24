"""A resolved preview of a text with references (``/api/previews/references`` and the same under ``/api/v1``, ADR-064).

An editor shows under a field with ``${...}`` what the text becomes for a given artifact: ``${card...}`` is resolved
against the artifact (what a run would start with), a node or a variable stays a readable placeholder, a secret is never
resolved or shown. Read only: nothing is stored and the artifact is not changed."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from openartifact.api.contract import GATED, errors
from openartifact.api.deps import SessionDep
from openartifact.artifact_fields.service import card_of
from openartifact.engine.context import PREVIEW_LIMIT, preview_references
from openartifact.exceptions import ArtifactError
from openartifact.models import Task

DESCRIPTION = (
    "``text`` (at most 20000 characters) as it would be with the artifact ``card`` (its number or id): "
    "``${card.title}``, ``${card.body}``, ``${card.text}``, ``${card.number}``, ``${card.id}`` and the artifact's own "
    "fields are resolved; ``${(Node).output}`` and ``${var.x}`` stay as placeholders in single angle quotes (output of Node), a secret is "
    "the placeholder secret and never resolved. ``resolved`` holds at most 2000 characters (``truncated``); ``unresolved`` names "
    "the references that could not be resolved. A convenience: a run uses the card as it is when the run starts."
)


class ReferencePreviewWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=20000)
    card: str = Field(min_length=1, max_length=36)


class ReferencePreviewRead(BaseModel):
    resolved: str
    unresolved: list[str]
    truncated: bool


def build_previews_router(
    prefix: str, tags: Sequence[str], dependencies: Sequence[Any] = ()
) -> APIRouter:
    router = APIRouter(
        prefix=f"{prefix}/previews",
        tags=list(tags),
        dependencies=list(dependencies),
        responses=GATED,
    )
    tag = "v1_" if "v1" in prefix else ""

    @router.post(
        "/references",
        response_model=ReferencePreviewRead,
        name=f"{tag}preview_references",
        summary="Resolve the card references of a text",
        description=DESCRIPTION,
        responses=errors(404, 422, write=True, body=True),
    )
    async def preview(
        payload: ReferencePreviewWrite, request: Request, session: SessionDep
    ) -> ReferencePreviewRead:
        found = await request.app.state.artifacts.get(payload.card)
        task = await session.get(Task, found.id)
        if task is None:  # gone between the two reads
            raise ArtifactError(404, "Artifact not found")
        resolved, unresolved = preview_references(payload.text, await card_of(session, task))
        truncated = len(resolved) > PREVIEW_LIMIT
        if truncated:
            resolved = resolved[:PREVIEW_LIMIT] + "…"
        return ReferencePreviewRead(
            resolved=resolved, unresolved=list(dict.fromkeys(unresolved)), truncated=truncated
        )

    return router
