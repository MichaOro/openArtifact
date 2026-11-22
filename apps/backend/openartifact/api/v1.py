"""The integration API (``/api/v1``): for scripts, agents and other systems, not for the browser.

Same operations as the browser's API (they all go through
:class:`~openartifact.tasks.service.ArtifactService`), under the name the user sees ("artifacts"),
with a stable path, and protected by the API token. An artifact can be addressed by its id or its
number (``12``). Creating and starting are separate calls on purpose.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status

from openartifact.api.deps import ServiceDep
from openartifact.engine.schemas import RunRead
from openartifact.exceptions import ArtifactError
from openartifact.models import CreatedBy, StartedBy
from openartifact.security import require_api_token
from openartifact.tasks.schemas import RunStart, TaskCreate, TaskRead, TaskUpdate

router = APIRouter(
    prefix="/api/v1",
    tags=["integration API"],
    dependencies=[Depends(require_api_token)],
)


@router.get("/pipelines")
async def list_pipelines(service: ServiceDep) -> list[dict[str, Any]]:
    """The pipelines with their stages in running order and the actions of each stage (the ids to start with)."""
    return await service.pipelines()


@router.get("/artifacts", response_model=list[TaskRead])
async def list_artifacts(service: ServiceDep) -> list[TaskRead]:
    """All artifacts in board order."""
    return await service.list_all()


@router.post("/artifacts", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_artifact(payload: TaskCreate, service: ServiceDep) -> TaskRead:
    """Create an artifact: title, body, lane, parent and the pipeline it starts with (its first stage and
    action unless chosen). It is not started; call ``POST /artifacts/{ref}/run`` for that."""
    return await service.create(payload, created_by=CreatedBy.API)


@router.get("/artifacts/{ref}", response_model=TaskRead)
async def get_artifact(ref: str, service: ServiceDep) -> TaskRead:
    """One artifact by id or number."""
    return await service.get(ref)


@router.patch("/artifacts/{ref}", response_model=TaskRead)
async def update_artifact(ref: str, payload: TaskUpdate, service: ServiceDep) -> TaskRead:
    """Change an artifact (lane, order, parent and pipeline are locked with 409 while it is processed)."""
    return await service.update(ref, payload)


@router.delete("/artifacts/{ref}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_artifact(ref: str, service: ServiceDep) -> Response:
    """Delete an artifact (not while it is processed)."""
    await service.delete(ref)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/artifacts/{ref}/run", response_model=RunRead)
async def get_run(ref: str, service: ServiceDep) -> RunRead:
    """How the processing of the artifact stands: status, where it is, the status of every stage."""
    run = await service.run(ref)
    if run is None:
        raise ArtifactError(404, "The artifact was never processed")
    return run


@router.post("/artifacts/{ref}/run", status_code=status.HTTP_201_CREATED, response_model=RunRead)
async def start_run(ref: str, service: ServiceDep, payload: RunStart | None = None) -> RunRead:
    """Start processing. Without a body it starts with the pipeline, stage and action the artifact has."""
    body = payload or RunStart()
    return await service.start(
        ref, body.pipeline_id, body.stage_id, body.action_id, started_by=StartedBy.SYSTEM
    )


@router.post("/artifacts/{ref}/run/stop", response_model=RunRead)
async def stop_run(ref: str, service: ServiceDep) -> RunRead:
    """Stop processing; the artifact keeps its stage and action."""
    return await service.stop(ref)
