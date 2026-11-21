"""Which pipeline, stage and action an artifact starts with."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.engine.chain import pipeline_chain
from openartifact.engine.snapshot import graph_of
from openartifact.models import Graph


class TargetError(ValueError):
    """The chosen pipeline, stage or action does not exist or does not fit together."""


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
    pipeline = await session.get(Graph, pipeline_id)
    if pipeline is None or pipeline.kind != "pipeline":
        raise TargetError("That pipeline does not exist")
    graph = await graph_of(session, pipeline_id)
    chain = pipeline_chain(graph["nodes"], graph["edges"])
    if not chain:
        raise TargetError("The pipeline has no stages from its trigger on")
    stage = chain[0] if stage_id is None else next((s for s in chain if s["id"] == stage_id), None)
    if stage is None:
        raise TargetError("That stage is not part of the pipeline")
    if action_id is None:
        return pipeline_id, stage["id"], stage["first_action_id"]
    if action_id not in {a["id"] for a in stage["actions"]}:
        raise TargetError("That action is not in the stage")
    return pipeline_id, stage["id"], action_id
