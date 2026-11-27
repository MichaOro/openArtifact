"""The observe mode of a pipeline over HTTP (ADR-088): ``/api/pipelines/{ref}/observe`` for the editor and the same under ``/api/v1`` for
integrations and remote maintenance. The mode is set in the draft and goes live with a publication; release and observe-again are immediate."""

from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import APIRouter

from openartifact.api.contract import GATED, errors
from openartifact.api.deps import ObserveDep
from openartifact.graph.observe_schemas import ObserveAgain, ObserveRead, ObserveSet

DESCRIPTION = (
    "The observe mode makes every run of a pipeline, from any start, a dry run that changes nothing (flag ``observed``). It is set in "
    "the draft and goes live with a publication (``publish`` in the same call publishes it when nothing else in the draft is "
    "unpublished). After its ``days`` or ``runs`` every start is refused (409, ``observation_ended``) until ``release`` (the pipeline "
    "runs for real) or ``again`` (a new observation), both immediate and recorded in ``state.events``. ``ref``: the pipeline's id, "
    "slug or name."
)


def build_observe_router(
    prefix: str, tags: list[str | Enum], by: str, gated: bool = False
) -> APIRouter:
    """The four routes under ``{prefix}/pipelines/{ref}/observe``; ``by`` names the door in the record of a decision; ``gated``: the
    router answers 401 itself (the editor's; the integration router inherits it)."""
    router = APIRouter(prefix=prefix, tags=tags, responses=GATED if gated else None)
    where = "/pipelines/{ref}/observe"

    @router.get(
        where,
        response_model=ObserveRead,
        summary="The observe mode of a pipeline",
        description=DESCRIPTION,
        responses=errors(404, 409, 422),
    )
    async def get_observe(ref: str, observe: ObserveDep) -> dict[str, Any]:
        return await observe.read(ref)

    @router.put(
        where,
        response_model=ObserveRead,
        summary="Set the observe mode in the draft of a pipeline",
        description="Sets ``enabled``, ``days`` and ``runs`` in the draft. It changes nothing that runs until the pipeline is published "
        "(``publish: true`` does it, refused with 409 ``draft_has_other_changes`` when the draft holds other unpublished changes). "
        + DESCRIPTION,
        responses=errors(404, 409, 422, write=True, body=True),
    )
    async def set_observe(ref: str, body: ObserveSet, observe: ObserveDep) -> dict[str, Any]:
        return await observe.set_draft(
            ref,
            {"enabled": body.enabled, "days": body.days, "runs": body.runs},
            publish=body.publish,
            by=by,
        )

    @router.post(
        where + "/release",
        response_model=ObserveRead,
        summary="Release a pipeline: it runs for real again",
        description="Immediate and recorded; no publication needed. Works while the observation is under way and after it ended. 409 when "
        "the published version has no observe mode. A publication that changes the mode starts a new observation.",
        responses=errors(404, 409, 422, write=True),
    )
    async def release_observe(ref: str, observe: ObserveDep) -> dict[str, Any]:
        return await observe.release(ref, by)

    @router.post(
        where + "/again",
        response_model=ObserveRead,
        summary="Observe a pipeline again from now",
        description="Immediate and recorded: counters from zero, with the ``days`` and ``runs`` given (none: the published setting's). 409 "
        "when the published version has no observe mode (switch it on in the draft and publish).",
        responses=errors(404, 409, 422, write=True, body=True),
    )
    async def observe_again(
        ref: str, observe: ObserveDep, body: ObserveAgain | None = None
    ) -> dict[str, Any]:
        given = body or ObserveAgain()
        return await observe.again(ref, by, given.days, given.runs)

    return router
