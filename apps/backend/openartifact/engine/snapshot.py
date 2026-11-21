"""A frozen copy of a pipeline and the action definitions it uses."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models import Workflow, WorkflowEdge, WorkflowNode
from openartifact.workflow.repository import WorkflowRepository


def _node(node: WorkflowNode, label: str) -> dict[str, Any]:
    return {
        "id": node.id,
        "kind": node.kind,
        "stage_id": node.stage_id,
        "name": node.name,
        "label": label,
        "definition_id": node.definition_id,
        "seconds": node.seconds,
        "x": node.x,
        "y": node.y,
    }


def _edge(edge: WorkflowEdge) -> dict[str, Any]:
    return {
        "source_id": edge.source_id,
        "source_port": edge.source_port,
        "target_id": edge.target_id,
        "target_port": edge.target_port,
    }


async def graph_of(session: AsyncSession, workflow_id: str) -> dict[str, Any]:
    """Nodes (an action labelled with its definition's name) and edges of a workflow as dicts."""
    repo = WorkflowRepository(session)
    nodes, edges = await repo.graph(workflow_id)
    described = await repo.describe(nodes)
    return {
        "nodes": [_node(n, described[n.id][0] if n.id in described else n.name) for n in nodes],
        "edges": [_edge(e) for e in edges],
    }


MAX_NESTING = 5  # pipelines calling pipelines calling ...


class NestingError(ValueError):
    """The pipeline calls itself or nests too deeply to be frozen."""


async def _collect(
    session: AsyncSession, root: dict[str, Any], graph: dict[str, Any], path: tuple[str, ...]
) -> None:
    """Add the action definitions and the called pipelines (recursively) of ``graph`` to ``root``."""
    for node in graph["nodes"]:
        target = node["definition_id"]
        if not target:
            continue
        if node["kind"] == "action" and target not in root["definitions"]:
            root["definitions"][target] = await graph_of(session, target)
        elif node["kind"] == "pipeline":
            if target in path:
                raise NestingError("The pipeline calls itself")
            if len(path) >= MAX_NESTING:
                raise NestingError("Pipelines are nested too deeply")
            if target not in root["pipelines"]:
                called = await graph_of(session, target)
                workflow = await session.get(Workflow, target)
                called["name"] = workflow.name if workflow else ""
                root["pipelines"][target] = called
                await _collect(session, root, called, (*path, target))


async def build_snapshot(session: AsyncSession, workflow: Workflow) -> dict[str, Any]:
    """The pipeline's graph plus the called pipelines and action definitions it uses, frozen."""
    snapshot = await graph_of(session, workflow.id)
    snapshot["name"] = workflow.name
    snapshot["definitions"] = {}
    snapshot["pipelines"] = {}
    await _collect(session, snapshot, snapshot, (workflow.id,))
    return snapshot
