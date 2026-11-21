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


async def build_snapshot(session: AsyncSession, workflow: Workflow) -> dict[str, Any]:
    """The pipeline's graph plus the graph of every action definition it links to."""
    snapshot = await graph_of(session, workflow.id)
    snapshot["name"] = workflow.name
    snapshot["definitions"] = {
        definition_id: await graph_of(session, definition_id)
        for definition_id in {n["definition_id"] for n in snapshot["nodes"] if n["definition_id"]}
    }
    return snapshot
