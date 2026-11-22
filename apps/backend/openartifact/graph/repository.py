"""Persistence for graph definitions. Receives an ``AsyncSession``; never creates its own."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, NamedTuple

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.engine.context import NodeIndex, node_key, problems
from openartifact.graph.node_types import (
    NODE_TYPES,
    NodeType,
    Ports,
    SettingError,
    fixed_in,
    kinds_in,
    node_type,
)
from openartifact.graph.rules import Endpoint, validate_edge
from openartifact.graph.schemas import EdgeCreate, EdgeUpdate, NodeCreate, NodeUpdate
from openartifact.graph.slug import slugify
from openartifact.models import Graph, GraphEdge, GraphKind, GraphNode, NodeKind


class NodeError(ValueError):
    """The requested node (or change of it) is not valid."""


class LinkInfo(NamedTuple):
    """What a linked node shows of the graph it links to."""

    name: str
    fail_enabled: bool  # the definition has an On Fail output
    slug: str


def _setting_keys() -> set[str]:
    """The settings any kind of node has as a column of the node (the others are in ``config``)."""
    return {s.key for t in NODE_TYPES.values() for s in t.settings if s.stored_in == "column"}


def _merged_config(
    kind_type: NodeType, stored: dict[str, Any] | None, changes: dict[str, Any]
) -> dict[str, Any]:
    try:
        return kind_type.merge_config(stored, changes)
    except SettingError as error:
        raise NodeError(str(error)) from error


class GraphRepository:
    """Database access for graphs, their nodes and edges."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── graphs ─────────────────────────────────────────────────────

    async def create(self, name: str, kind: GraphKind = GraphKind.PIPELINE) -> Graph:
        """Create a graph with its fixed nodes, connected with each other.

        A pipeline gets a trigger and a complete, an action definition a trigger and an output.
        """
        graph = Graph(id=str(uuid.uuid4()), name=name, kind=kind)
        graph.slug = await self._unique_slug(name, kind, None)
        self._session.add(graph)
        fixed = fixed_in(kind)
        start = next(t for t in fixed if t.chain)
        end = next(t for t in fixed if t.ending)
        ids = {}
        for fixed_type, x in ((start, 60.0), (end, 316.0 if kind == GraphKind.PIPELINE else 460.0)):
            ids[fixed_type.kind] = str(uuid.uuid4())
            self._session.add(
                GraphNode(
                    id=ids[fixed_type.kind],
                    graph_id=graph.id,
                    kind=fixed_type.kind.value,
                    name=fixed_type.default_name,
                    x=x,
                    y=164.0,
                )
            )
        await self._session.flush()  # the nodes must exist before the edge refers to them
        self._session.add(
            GraphEdge(
                id=str(uuid.uuid4()),
                graph_id=graph.id,
                source_id=ids[start.kind],
                source_port=start.outputs[0].name,
                target_id=ids[end.kind],
                target_port=end.inputs[0].name,
            )
        )
        await self._session.flush()
        return graph

    async def list_all(self, kind: GraphKind = GraphKind.PIPELINE) -> Sequence[Graph]:
        """All graphs (or action definitions), most recently changed first."""
        result = await self._session.execute(
            select(Graph).where(Graph.kind == kind).order_by(Graph.updated_at.desc(), Graph.id)
        )
        return result.scalars().all()

    async def get(self, graph_id: str) -> Graph | None:
        """The graph or ``None``."""
        return await self._session.get(Graph, graph_id)

    async def rename(self, graph: Graph, name: str) -> None:
        """Change the name; the URL name follows it."""
        graph.name = name
        graph.slug = await self._unique_slug(name, graph.kind, graph.id)
        await self._session.flush()

    async def _unique_slug(self, name: str, kind: str, own_id: str | None) -> str:
        """The URL name for ``name``, with -2, -3 ... when another graph of the kind has it."""
        base = slugify(name, GraphKind(kind).value)
        slug, n = base, 2
        while await self._session.scalar(
            select(Graph.id).where(
                Graph.kind == kind, Graph.slug == slug, Graph.id != (own_id or "")
            )
        ):
            slug, n = f"{base}-{n}", n + 1
        return slug

    async def find(self, kind: GraphKind, slug: str) -> Graph | None:
        """A graph of the kind by its URL name."""
        return await self._session.scalar(
            select(Graph).where(Graph.kind == kind, Graph.slug == slug)
        )

    async def delete(self, graph: Graph) -> None:
        """Delete the graph; its nodes and edges go with it (foreign key cascade)."""
        await self._session.delete(graph)
        await self._session.flush()

    async def graph(self, graph_id: str) -> tuple[Sequence[GraphNode], Sequence[GraphEdge]]:
        """All nodes and edges of a graph."""
        nodes = await self._session.execute(
            select(GraphNode)
            .where(GraphNode.graph_id == graph_id)
            .order_by(GraphNode.created_at, GraphNode.id)
        )
        edges = await self._session.execute(
            select(GraphEdge).where(GraphEdge.graph_id == graph_id).order_by(GraphEdge.id)
        )
        return nodes.scalars().all(), edges.scalars().all()

    async def reference_hints(self, node: GraphNode) -> list[str]:
        """Problems with the ``${node...}`` references of an HTTP node's URL, headers and body.

        Only hints (the node is saved anyway): names that two nodes of the same action share, names
        no node of any action has, malformed references. Which pipeline runs the action, and so which
        nodes are around it, is only known at run time, where such a reference fails the node.
        """
        if node.kind != NodeKind.HTTP:
            return []
        config = node_type(node.kind).effective_config(node.config)
        text = "\n".join(str(config.get(k) or "") for k in ("url", "headers", "body"))
        if "${" not in text:
            return []
        graph = await self._session.get(Graph, node.graph_id)
        siblings, _ = await self.graph(node.graph_id)
        local = NodeIndex.of_graphs(
            [
                {
                    "name": graph.name if graph else "",
                    "nodes": [{"id": n.id, "name": n.name, "kind": n.kind} for n in siblings],
                }
            ]
        )
        others = await self._session.execute(
            select(GraphNode.name).where(
                GraphNode.graph_id != node.graph_id,
                GraphNode.kind.in_([NodeKind.CODE, NodeKind.HTTP, NodeKind.TIMER]),
            )
        )
        keys = {node_key(name) for (name,) in others}
        return problems(text, local, lambda key: key in keys)

    async def touch(self, graph: Graph) -> None:
        """Mark the graph as changed (its nodes or edges changed)."""
        graph.updated_at = datetime.now(UTC)
        await self._session.flush()

    # ── nodes ─────────────────────────────────────────────────────────

    async def get_node(self, graph_id: str, node_id: str) -> GraphNode | None:
        """The node if it belongs to the graph."""
        node = await self._session.get(GraphNode, node_id)
        return node if node is not None and node.graph_id == graph_id else None

    async def add_node(self, graph: Graph, data: NodeCreate) -> GraphNode:
        """Add a node. Actions must name a stage of the same graph."""
        kind_type = node_type(data.kind)
        if data.kind not in kinds_in(GraphKind(graph.kind)):
            raise NodeError(f"A {graph.kind} cannot contain a {data.kind.value}")
        if kind_type.fixed:
            raise NodeError(f"A {graph.kind} comes with its {data.kind.value}; it cannot be added")
        if data.kind is NodeKind.ACTION:
            stage = data.stage_id and await self.get_node(graph.id, data.stage_id)
            if not stage or stage.kind != NodeKind.STAGE.value:
                raise NodeError("An action needs a stage of this graph")
        elif data.stage_id is not None:
            raise NodeError("Only actions belong to a stage")
        config = _merged_config(kind_type, None, data.config or {})
        node = GraphNode(
            id=str(uuid.uuid4()),
            graph_id=graph.id,
            kind=data.kind.value,
            config=config,
            stage_id=data.stage_id,
            name=data.name or kind_type.default_name,
            x=data.x,
            y=data.y,
            width=kind_type.size[0] if kind_type.size else None,
            height=kind_type.size[1] if kind_type.size else None,
            **{
                s.key: getattr(data, s.key, None) or s.default
                for s in kind_type.settings
                if s.type == "integer" and s.stored_in == "column"
            },
        )
        self._session.add(node)
        await self._session.flush()
        return node

    async def update_node(self, node: GraphNode, data: NodeUpdate) -> None:
        """Rename, move or (stages) resize a node."""
        sent = data.model_fields_set
        kind_type = node_type(node.kind)
        if {"width", "height"} & sent and kind_type.size is None:
            raise NodeError("Only stages have a size")
        own = {s.key for s in kind_type.settings}
        settings = _setting_keys()
        for key in settings & sent - own:
            raise NodeError(f"A {node.kind} has no setting '{key}'")
        if data.config is not None:
            node.config = _merged_config(kind_type, node.config, data.config)
        if "definition_id" in sent:
            await self._link(node, data.definition_id)
        for field in ("name", "x", "y", "width", "height", *sorted(settings)):
            value = getattr(data, field)
            if field in sent and value is not None:
                setattr(node, field, value)
        await self._session.flush()
        if data.fail_enabled is False:
            # the On Fail connector is gone, and so is the Error output of actions linked to this definition
            await self._session.execute(
                delete(GraphEdge).where(
                    GraphEdge.target_id == node.id, GraphEdge.target_port == Ports.FAIL
                )
            )
            await self._drop_error_edges(GraphNode.definition_id == node.graph_id)

    async def _link(self, node: GraphNode, definition_id: str | None) -> None:
        """Link an action to an action definition, or a pipeline node to the pipeline it calls.

        ``None`` turns an action back into an empty shell and a pipeline node into an unset one.
        """
        graph = await self._session.get(Graph, node.graph_id)
        links_to = node_type(node.kind).links_to
        if links_to is None or graph is None:
            raise NodeError(f"A {node.kind} does not link to anything")
        calls = links_to == GraphKind.PIPELINE
        if definition_id is not None:
            target = await self._session.get(Graph, definition_id)
            if target is None or target.kind != links_to:
                raise NodeError(
                    "That pipeline does not exist" if calls else "That action does not exist"
                )
            if calls and await self._calls(definition_id, graph.id):
                raise NodeError("A pipeline cannot call itself, not even through other pipelines")
        node.definition_id = definition_id
        await self._session.flush()
        if (
            not calls
            and definition_id is not None
            and not (await self.describe([node]))[node.id].fail_enabled
        ):
            await self._drop_error_edges(GraphNode.id == node.id)

    async def _calls(self, start_id: str, wanted_id: str) -> bool:
        """Whether the pipeline ``start_id`` is, or (through its pipeline nodes) calls, ``wanted_id``."""
        seen: set[str] = set()
        queue = [start_id]
        while queue:
            current = queue.pop()
            if current == wanted_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            rows = await self._session.execute(
                select(GraphNode.definition_id).where(
                    GraphNode.graph_id == current,
                    GraphNode.kind == NodeKind.PIPELINE.value,
                    GraphNode.definition_id.is_not(None),
                )
            )
            queue.extend(row[0] for row in rows if row[0])
        return False

    async def _drop_error_edges(self, which: ColumnElement[bool]) -> None:
        """Remove the Error connections of the actions matching ``which`` (they have no On Fail)."""
        ids = select(GraphNode.id).where(which)
        await self._session.execute(
            delete(GraphEdge).where(
                GraphEdge.source_port == Ports.ERROR, GraphEdge.source_id.in_(ids)
            )
        )

    async def describe(self, nodes: Sequence[GraphNode]) -> dict[str, LinkInfo]:
        """For linked nodes: the definition's name, whether it has On Fail and its URL name."""
        wanted = {n.definition_id for n in nodes if n.definition_id}
        if not wanted:
            return {}
        rows = await self._session.execute(
            select(Graph.id, Graph.name, GraphNode.fail_enabled, Graph.slug)
            .join(
                GraphNode,
                (GraphNode.graph_id == Graph.id) & (GraphNode.kind == NodeKind.OUTPUT.value),
                isouter=True,  # a called pipeline has no output node
            )
            .where(Graph.id.in_(wanted))
        )
        by_definition = {row[0]: LinkInfo(row[1], bool(row[2]), row[3]) for row in rows}
        return {
            n.id: by_definition[n.definition_id] for n in nodes if n.definition_id in by_definition
        }

    async def delete_node(self, graph: Graph, node: GraphNode) -> None:
        """Delete a node; its actions (for a stage) and edges go with it (cascade)."""
        kind = NodeKind(node.kind)
        if node_type(kind).fixed:
            same = await self._session.scalar(
                select(func.count())
                .select_from(GraphNode)
                .where(GraphNode.graph_id == graph.id, GraphNode.kind == kind.value)
            )
            if same == 1:  # older graphs may hold several; the last one stays
                raise NodeError(f"The {kind.value} of a {graph.kind} stays")
        await self._session.delete(node)
        await self._session.flush()

    # ── edges ─────────────────────────────────────────────────────────

    async def connect(self, graph: Graph, data: EdgeCreate) -> GraphEdge:
        """Connect two ports; an existing edge on the same output is replaced."""
        source = await self.get_node(graph.id, data.source_id)
        target = await self.get_node(graph.id, data.target_id)
        if source is None or target is None:
            raise NodeError("Both ends of an edge must be nodes of this graph")
        validate_edge(_endpoint(source), data.source_port, _endpoint(target), data.target_port)
        if data.target_port == Ports.FAIL and not target.fail_enabled:
            raise NodeError("That action definition has no On Fail")
        if (
            data.source_port == Ports.ERROR
            and source.definition_id
            and not (await self.describe([source]))[source.id].fail_enabled
        ):
            raise NodeError("That action has no On Fail")
        if (data.source_slot and source.kind != NodeKind.STAGE.value) or (
            data.target_slot and target.kind != NodeKind.STAGE.value
        ):
            raise NodeError("Only stages have more than one attachment point")
        await self._session.execute(
            delete(GraphEdge).where(
                GraphEdge.source_id == source.id, GraphEdge.source_port == data.source_port
            )
        )
        edge = GraphEdge(
            id=str(uuid.uuid4()),
            graph_id=graph.id,
            source_id=source.id,
            source_port=data.source_port,
            target_id=target.id,
            target_port=data.target_port,
            style=data.style,
            source_slot=data.source_slot,
            target_slot=data.target_slot,
        )
        self._session.add(edge)
        await self._session.flush()
        return edge

    async def get_edge(self, graph_id: str, edge_id: str) -> GraphEdge | None:
        """The edge if it belongs to the graph."""
        edge = await self._session.get(GraphEdge, edge_id)
        return edge if edge is not None and edge.graph_id == graph_id else None

    async def restyle(self, edge: GraphEdge, data: EdgeUpdate) -> None:
        """Change how an edge is drawn."""
        edge.style = data.style
        await self._session.flush()

    async def disconnect(self, edge: GraphEdge) -> None:
        """Remove an edge."""
        await self._session.delete(edge)
        await self._session.flush()


def _endpoint(node: GraphNode) -> Endpoint:
    return Endpoint(id=node.id, kind=NodeKind(node.kind), stage_id=node.stage_id)
