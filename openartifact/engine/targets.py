"""Which pipeline, stage and action an artifact starts with."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.engine.chain import pipeline_chain
from openartifact.graph.publishing import graph_for_run
from openartifact.models import Graph, GraphKind


class TargetError(ValueError):
    """The chosen pipeline, stage or action does not exist or does not fit together."""


async def load_pipeline(session: AsyncSession, pipeline_id: str) -> Graph:
    """The pipeline with this id (an action definition is not one)."""
    pipeline = await session.get(Graph, pipeline_id)
    if pipeline is None or pipeline.kind != GraphKind.PIPELINE:
        raise TargetError("That pipeline does not exist")
    return pipeline


def pick_start(
    chain: list[dict[str, Any]], stage_id: str | None, action_id: str | None
) -> tuple[int, dict[str, Any], str | None]:
    """The entry of a pipeline's chain to start at, as (index, entry, action id).

    The first entry and, in a stage, that stage's first action are the defaults; a pipeline node
    has no action. Every check of "does this stage and action fit this pipeline" is here.
    """
    if not chain:
        raise TargetError("The pipeline has no stages from its trigger on")
    index = (
        0 if stage_id is None else next((i for i, s in enumerate(chain) if s["id"] == stage_id), -1)
    )
    if index < 0:
        raise TargetError("That stage is not part of the pipeline")
    entry = chain[index]
    if action_id is None:
        return index, entry, entry["first_action_id"]
    if action_id not in {a["id"] for a in entry["actions"]}:
        raise TargetError("That action is not in the stage")
    return index, entry, action_id


async def resolve_target(
    session: AsyncSession,
    pipeline_id: str | None,
    stage_id: str | None = None,
    action_id: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Complete a choice: the first stage of the pipeline and that stage's first action by default.

    No pipeline means no stage and no action either.
    """
    if pipeline_id is None:
        if stage_id or action_id:
            raise TargetError("A stage or an action needs a pipeline")
        return None, None, None
    await load_pipeline(session, pipeline_id)
    graph = await graph_for_run(
        session, pipeline_id
    )  # the place is chosen in what the run will read (ADR-070)
    _, entry, action = pick_start(
        pipeline_chain(graph["nodes"], graph["edges"]), stage_id, action_id
    )
    return pipeline_id, entry["id"], action
