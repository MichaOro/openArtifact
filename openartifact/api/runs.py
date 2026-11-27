"""Processing of artifacts in a pipeline: start, stop and list runs."""

from __future__ import annotations

from fastapi import APIRouter

from openartifact.api.contract import GATED, errors
from openartifact.api.deps import EngineDep, ServiceDep, SessionDep
from openartifact.engine import dry_run
from openartifact.engine.schemas import NodeResultRead, RunRead
from openartifact.exceptions import ArtifactError
from openartifact.tasks.schemas import (
    DryRunCard,
    DryRunCheck,
    DryRunProblems,
    DryRunStart,
    DryRunTarget,
    RunStart,
)

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
        definition_id=body.definition_id,
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
    if body.pipeline_id is None and body.definition_id is None:
        raise ArtifactError(422, "pipeline_id or definition_id is needed")
    return DryRunProblems(
        problems=await engine.check_start(
            task_id,
            body.pipeline_id or body.definition_id or "",
            body.stage_id,
            body.action_id,
            body.inputs,
            body.version or "draft",
            definition_id=body.definition_id,
        )
    )


@router.post(
    "/graphs/{ref}/dry-run",
    status_code=201,
    response_model=RunRead,
    summary="Start a dry run of a pipeline or an action, with or without a card",
    responses=errors(404, 409, 422, 429, write=True, body=True),
)
async def start_dry_run(
    ref: str, service: ServiceDep, payload: DryRunStart | None = None
) -> RunRead:
    """A dry run (ADR-086) of the pipeline, or of the action definition by itself, from its Trigger to its Output (ADR-089). ``task_id``
    names a card (id or number) to run it on; without one the run belongs to the hidden card of this graph, made when it is first needed
    (the answer's ``task_id`` and the executions of that card are how it is followed). ``version`` is ``draft`` (default: what is being
    edited) or ``published``."""
    body = payload or DryRunStart()
    return await service.start_dry_run(
        ref,
        task_ref=body.task_id,
        stage_id=body.stage_id,
        action_id=body.action_id,
        inputs=body.inputs,
        version=body.version or "draft",
    )


@router.post(
    "/graphs/{ref}/dry-run/check",
    response_model=DryRunProblems,
    summary="Check a dry run of a pipeline or an action before it is started",
    responses=errors(404, 422, write=True, body=True),
)
async def check_graph_dry_run(
    ref: str, service: ServiceDep, payload: DryRunStart | None = None
) -> DryRunProblems:
    """What would refuse the dry run started like this (``DryRunStart``), in plain words; reads only and starts nothing."""
    body = payload or DryRunStart()
    return DryRunProblems(
        problems=await service.check_dry_run(
            ref,
            task_ref=body.task_id,
            stage_id=body.stage_id,
            action_id=body.action_id,
            inputs=body.inputs,
            version=body.version or "draft",
        )
    )


@router.get(
    "/graphs/{ref}/dry-run-card",
    response_model=DryRunCard,
    summary="The hidden card the card-less dry runs of a graph belong to",
    responses=errors(404),
)
async def graph_dry_run_card(ref: str, service: ServiceDep) -> DryRunCard:
    """Where the executions of the dry runs started without a card are listed (``/api/tasks/{task_id}/executions``); ``null`` while no
    such dry run was made."""
    task_id, number = await service.dry_run_card(ref)
    return DryRunCard(task_id=task_id, number=number)


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
