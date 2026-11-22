"""A frozen copy of a pipeline and the action definitions it uses.

Every graph in it carries its ``id``, ``name`` and ``kind``; nodes carry their size and ``fail_enabled``,
edges their ``id``, style and slots, so the execution flow can draw it like the editor does. Snapshots
frozen before those fields existed lack them; :mod:`openartifact.engine.flow` fills them in.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.graph.node_types import node_type
from openartifact.graph.repository import GraphRepository
from openartifact.models import Graph, GraphEdge, GraphNode, NodeKind


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
        if node["kind"] == NodeKind.ACTION and target not in root["definitions"]:
            root["definitions"][target] = await graph_of(session, target)
        elif node["kind"] == NodeKind.PIPELINE:
            if target in path:
                raise NestingError("The pipeline calls itself")
            if len(path) >= MAX_NESTING:
                raise NestingError("Pipelines are nested too deeply")
            if target not in root["pipelines"]:
                called = await graph_of(session, target)
                root["pipelines"][target] = called
                await _collect(session, root, called, (*path, target))


async def build_snapshot(session: AsyncSession, graph: Graph) -> dict[str, Any]:
    """The pipeline's graph plus the called pipelines and action definitions it uses, frozen."""
    snapshot = await graph_of(session, graph.id)
    snapshot["definitions"] = {}
    snapshot["pipelines"] = {}
    await _collect(session, snapshot, snapshot, (graph.id,))
    return snapshot
