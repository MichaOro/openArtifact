"""Processing of artifacts in a pipeline: start, stop and list runs."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.api.tasks import ServiceDep, to_http
from openartifact.database import get_db_session
from openartifact.engine.runner import RunEngine
from openartifact.tasks.service import ArtifactError

router = APIRouter(prefix="/api", tags=["runs"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_engine(request: Request) -> RunEngine:
    """The application's execution engine."""
    engine: RunEngine = request.app.state.engine
    return engine


EngineDep = Annotated[RunEngine, Depends(get_engine)]


class RunStart(BaseModel):
    """Body of ``POST /api/tasks/{id}/run``: the pipeline, and optionally where to start in it.

    Everything may be left out: the artifact then starts with the pipeline, stage and action it has.
    """

    model_config = ConfigDict(extra="forbid")

    workflow_id: str | None = None
    stage_id: str | None = None
    action_id: str | None = None


@router.get("/runs")
async def list_runs(session: SessionDep, engine: EngineDep) -> list[dict[str, Any]]:
    """Every run: the state of the artifacts that were processed."""
    return await engine.list_all(session)


@router.post("/tasks/{task_id}/run", status_code=201)
async def start_run(
    task_id: str, service: ServiceDep, payload: RunStart | None = None
) -> dict[str, Any]:
    """Start processing an artifact (``stage_id``/``action_id`` default to the first ones).

    Stages before the starting stage count as done. Publishes ``run.updated`` on every step.
    """
    body = payload or RunStart()
    try:
        return await service.start(task_id, body.workflow_id, body.stage_id, body.action_id)
    except ArtifactError as error:
        raise to_http(error) from error


@router.post("/tasks/{task_id}/run/stop")
async def stop_run(task_id: str, service: ServiceDep) -> dict[str, Any]:
    """Stop the processing of an artifact; it keeps its stage and action."""
    try:
        return await service.stop(task_id)
    except ArtifactError as error:
        raise to_http(error) from error
