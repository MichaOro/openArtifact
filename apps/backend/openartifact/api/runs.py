"""Processing of artifacts in a pipeline: start, stop and list runs."""

from __future__ import annotations

from fastapi import APIRouter

from openartifact.api.deps import EngineDep, ServiceDep, SessionDep
from openartifact.engine.schemas import RunRead
from openartifact.tasks.schemas import RunStart

router = APIRouter(prefix="/api", tags=["runs"])


@router.get("/runs", response_model=list[RunRead])
async def list_runs(session: SessionDep, engine: EngineDep) -> list[RunRead]:
    """Every run: the state of the artifacts that were processed."""
    return await engine.list_all(session)


@router.post("/tasks/{task_id}/run", status_code=201, response_model=RunRead)
async def start_run(task_id: str, service: ServiceDep, payload: RunStart | None = None) -> RunRead:
    """Start processing an artifact (``stage_id``/``action_id`` default to the first ones).

    Stages before the starting stage count as done. Publishes ``run.updated`` on every step.
    """
    body = payload or RunStart()
    return await service.start(task_id, body.pipeline_id, body.stage_id, body.action_id)


@router.post("/tasks/{task_id}/run/stop", response_model=RunRead)
async def stop_run(task_id: str, service: ServiceDep) -> RunRead:
    """Stop the processing of an artifact; it keeps its stage and action."""
    return await service.stop(task_id)
