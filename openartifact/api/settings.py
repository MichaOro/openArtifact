"""Settings users change at run time: ``/api/settings/run-limits`` for the browser and the same under
``/api/v1`` (ADR-039). A change publishes ``settings.changed`` and takes effect for executions that start
afterwards."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Request

from openartifact.api.contract import GATED, errors
from openartifact.api.deps import SessionDep
from openartifact.engine.limits import RunLimitsRead, RunLimitsWrite, load_limits, save_limits

DESCRIPTION = (
    "``max_steps`` (10 to 100000, default 1000): steps one execution may take, the actions and the nodes of "
    "their definitions together; a pipeline that loops fails at it. ``time_limit_minutes`` (0 to 10080, "
    "default 0 = none): how long one execution may run; the node that runs then is stopped and the "
    "execution fails. An execution keeps the limits it started with. ``max_concurrent_runs`` is the "
    "operator's ``OPENARTIFACT_MAX_CONCURRENT_RUNS`` and read-only."
)


def build_settings_router(
    prefix: str, tags: Sequence[str], dependencies: Sequence[Any] = ()
) -> APIRouter:
    router = APIRouter(
        prefix=f"{prefix}/settings",
        tags=list(tags),
        dependencies=list(dependencies),
        responses=GATED,
    )
    tag = "v1_" if "v1" in prefix else ""

    async def read(request: Request, session: SessionDep) -> RunLimitsRead:
        limits, changed = await load_limits(session)
        return RunLimitsRead(
            max_steps=limits.max_steps,
            time_limit_minutes=limits.time_limit_minutes,
            max_concurrent_runs=request.app.state.settings.max_concurrent_runs,
            updated_at=changed,
        )

    @router.get(
        "/run-limits",
        response_model=RunLimitsRead,
        name=f"{tag}get_run_limits",
        summary="Get the run limits",
        description=DESCRIPTION,
    )
    async def get_run_limits(request: Request, session: SessionDep) -> RunLimitsRead:
        return await read(request, session)

    @router.put(
        "/run-limits",
        response_model=RunLimitsRead,
        name=f"{tag}put_run_limits",
        summary="Change the run limits",
        description=DESCRIPTION
        + " A field that is left out keeps its value. Publishes ``settings.changed``.",
        responses=errors(422, write=True, body=True),
    )
    async def put_run_limits(
        payload: RunLimitsWrite, request: Request, session: SessionDep
    ) -> RunLimitsRead:
        await save_limits(session, payload)
        await session.commit()
        result = await read(request, session)
        request.app.state.event_bus.publish(
            "settings.changed", {"run_limits": result.model_dump(mode="json")}
        )
        return result

    return router
