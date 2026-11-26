"""Processing of artifacts in a pipeline: start, stop and list runs."""

from __future__ import annotations

from fastapi import APIRouter

from openartifact.api.contract import GATED, errors
from openartifact.api.deps import EngineDep, ServiceDep, SessionDep
from openartifact.engine import dry_run
from openartifact.engine.schemas import NodeResultRead, RunRead
from openartifact.exceptions import ArtifactError
from openartifact.tasks.schemas import DryRunCheck, DryRunProblems, DryRunTarget, RunStart

router = APIRouter(prefix="/api", tags=["runs"], responses=GATED)


@router.get("/runs", response_model=list[RunRead], summary="List runs")
async def list_runs(session: SessionDep, engine: EngineDep) -> list[RunRead]:
    """Every run: the state of the artifacts that were processed."""
    return await engine.list_all(session)


@router.get(
    "/runs/{task_id}/results",
    response_model=list[NodeResultRead],
    summary="List the results of a run",
    responses=errors(404, 422),
)
async def list_results(task_id: str, service: ServiceDep) -> list[NodeResultRead]:
    """Every step of the artifact's run inside action definitions, in order, with complete outputs."""
    results = await service.run_results(task_id)
    if results is None:
        raise ArtifactError(404, "The artifact was never processed")
    return results


@router.post(
    "/tasks/{task_id}/run",
    status_code=201,
    response_model=RunRead,
    summary="Start a run",
    responses=errors(404, 409, 422, 429, write=True, body=True),
)
async def start_run(task_id: str, service: ServiceDep, payload: RunStart | None = None) -> RunRead:
    """Start processing an artifact (``stage_id``/``action_id`` default to the first ones).

    Stages before the starting stage count as done. Publishes ``run.updated`` on every step.
    """
    body = payload or RunStart()
    return await service.start(
        task_id,
        body.pipeline_id,
        body.stage_id,
        body.action_id,
        dry_run=body.dry_run,
        inputs=body.inputs,
        # from the editor a dry run tests what is being edited unless it says otherwise
        version=body.version or ("draft" if body.dry_run else None),
    )


@router.post(
    "/tasks/{task_id}/dry-run/check",
    response_model=DryRunProblems,
    summary="Check a dry run before it is started",
    responses=errors(404, 422, write=True, body=True),
)
async def check_dry_run(task_id: str, body: DryRunCheck, engine: EngineDep) -> DryRunProblems:
    """What would refuse a dry run started with these values, in plain words (ADR-086): the start that does not exist, an input that is
    missing or does not fit, a reference of the draft that names something that is not there. Reads only, starts nothing."""
    return DryRunProblems(
        problems=await engine.check_start(
            task_id,
            body.pipeline_id,
            body.stage_id,
            body.action_id,
            body.inputs,
            body.version or "draft",
        )
    )


@router.get(
    "/actions/{action_id}/placements",
    response_model=list[DryRunTarget],
    summary="Where an action definition is placed in a pipeline",
    responses=errors(404, 422),
)
async def action_placements(action_id: str, session: SessionDep) -> list[DryRunTarget]:
    """The pipelines, stages and actions that run this action definition (by the version that runs): where a dry run of the action starts.
    Empty when no pipeline places it."""
    return [DryRunTarget(**p) for p in await dry_run.placements_of_action(session, action_id)]


@router.post(
    "/tasks/{task_id}/run/stop",
    response_model=RunRead,
    summary="Stop a run",
    responses=errors(404, 422, 409, write=True),
)
async def stop_run(task_id: str, service: ServiceDep) -> RunRead:
    """Stop the processing of an artifact; it keeps its stage and action."""
    return await service.stop(task_id)
