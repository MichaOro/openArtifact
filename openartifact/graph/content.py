"""A graph as plain data: id, name, kind, its nodes and its edges (what a snapshot, a published version and the API's *Show* use)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.graph.node_types import node_type
from openartifact.graph.placements import KEY
from openartifact.graph.repository import GraphRepository
from openartifact.models import Graph, GraphEdge, GraphNode


def _node(node: GraphNode, label: str) -> dict[str, Any]:
    return {
        "id": node.id,
        "kind": node.kind,
        "stage_id": node.stage_id,
        "name": node.name,
        "label": label,
        "definition_id": node.definition_id,
        "seconds": node.seconds,
        "config": node_type(node.kind).effective_config(node.config),
        "number": (node.config or {}).get(KEY),
        "x": node.x,
        "y": node.y,
        "width": node.width,
        "height": node.height,
        "fail_enabled": node.fail_enabled,
    }


def _edge(edge: GraphEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "style": edge.style,
        "source_slot": edge.source_slot,
        "target_slot": edge.target_slot,
        "source_id": edge.source_id,
        "source_port": edge.source_port,
        "target_id": edge.target_id,
        "target_port": edge.target_port,
    }


async def graph_of(session: AsyncSession, graph_id: str) -> dict[str, Any]:
    """Id, name, kind, nodes (an action labelled with its definition's name) and edges of a graph as dicts."""
    repo = GraphRepository(session)
    nodes, edges = await repo.graph(graph_id)
    described = await repo.describe(nodes)
    graph = await session.get(Graph, graph_id)
    return {
        "id": graph_id,
        "name": graph.name if graph else "",
        "kind": graph.kind if graph else "",
        "nodes": [_node(n, described[n.id].name if n.id in described else n.name) for n in nodes],
        "edges": [_edge(e) for e in edges],
    }
