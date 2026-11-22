"""Pipeline and action definition API (``/api/pipelines``, ``/api/actions``, ``/api/node-types``).

Both are stored as graphs and share one set of sub-resources; the path picks the kind. Every
change is saved at once (there is no separate "save"): the editor sends what the user did.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status

from openartifact.api.deps import SessionDep
from openartifact.engine.chain import pipeline_chain
from openartifact.engine.snapshot import graph_of
from openartifact.graph.node_types import NODE_TYPES, node_type
from openartifact.graph.repository import GraphRepository, NodeError
from openartifact.graph.rules import EdgeError
from openartifact.graph.schemas import (
    EdgeCreate,
    EdgeRead,
    EdgeUpdate,
    GraphCreate,
    GraphDetail,
    GraphRead,
    GraphUpdate,
    NodeCreate,
    NodeRead,
    NodeUpdate,
)
from openartifact.models import Graph, GraphKind, GraphNode

_LABELS: dict[GraphKind, str] = {GraphKind.PIPELINE: "Pipeline", GraphKind.ACTION: "Action"}


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


def _invalid(error: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))


async def _node_reads(repo: GraphRepository, nodes: Sequence[GraphNode]) -> list[NodeRead]:
    """Nodes as the API returns them, linked actions with their definition's name and On Fail."""
    described = await repo.describe(nodes)
    reads = [NodeRead.model_validate(n) for n in nodes]
    for read, node in zip(reads, nodes, strict=True):
        read.config = node_type(node.kind).effective_config(node.config)
        if read.id in described:
            link = described[read.id]
            read.definition_name = link.name
            read.definition_fail_enabled = link.fail_enabled
            read.definition_slug = link.slug
    return reads


def build_graph_router(kind: GraphKind) -> APIRouter:
    """The router of one kind of graph: ``pipeline`` at ``/api/pipelines``, ``action`` at ``/api/actions``."""
    label = _LABELS[kind]
    router = APIRouter(prefix=f"/api/{kind}s", tags=[f"{kind}s"])

    async def _graph(repo: GraphRepository, graph_id: str) -> Graph:
        graph = await repo.get(graph_id)
        if graph is None or graph.kind != kind:  # a graph of the other kind is not found here
            raise _not_found(label)
        return graph

    @router.get("", response_model=list[GraphRead], name=f"list_{kind}s")
    async def list_graphs(session: SessionDep) -> list[GraphRead]:
        """List all of this kind, most recently changed first."""
        graphs = await GraphRepository(session).list_all(kind)
        return [GraphRead.model_validate(g) for g in graphs]

    @router.post(
        "",
        response_model=GraphRead,
        status_code=status.HTTP_201_CREATED,
        name=f"create_{kind}",
    )
    async def create_graph(payload: GraphCreate, session: SessionDep) -> GraphRead:
        """Create one; it starts with a trigger (an action definition also with its output)."""
        graph = await GraphRepository(session).create(payload.name, kind)
        await session.commit()
        return GraphRead.model_validate(graph)

    @router.get("/{graph_id}", response_model=GraphDetail, name=f"get_{kind}")
    async def get_graph(graph_id: str, session: SessionDep) -> GraphDetail:
        """One with all its nodes and edges."""
        repo = GraphRepository(session)
        graph = await _graph(repo, graph_id)
        nodes, edges = await repo.graph(graph_id)
        return GraphDetail(
            graph=GraphRead.model_validate(graph),
            nodes=await _node_reads(repo, nodes),
            edges=[EdgeRead.model_validate(e) for e in edges],
        )

    if kind == GraphKind.PIPELINE:

        @router.get("/{graph_id}/stages", name="get_stages")
        async def get_stages(graph_id: str, session: SessionDep) -> list[dict[str, Any]]:
            """The stages of a pipeline in the order it runs them, with their actions."""
            await _graph(GraphRepository(session), graph_id)
            graph = await graph_of(session, graph_id)
            return pipeline_chain(graph["nodes"], graph["edges"])

    @router.patch("/{graph_id}", response_model=GraphRead, name=f"rename_{kind}")
    async def rename_graph(graph_id: str, payload: GraphUpdate, session: SessionDep) -> GraphRead:
        """Rename it."""
        repo = GraphRepository(session)
        graph = await _graph(repo, graph_id)
        await repo.rename(graph, payload.name)
        await session.commit()
        return GraphRead.model_validate(graph)

    @router.delete("/{graph_id}", status_code=status.HTTP_204_NO_CONTENT, name=f"delete_{kind}")
    async def delete_graph(graph_id: str, session: SessionDep) -> Response:
        """Delete it with everything in it."""
        repo = GraphRepository(session)
        await repo.delete(await _graph(repo, graph_id))
        await session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/{graph_id}/nodes",
        response_model=NodeRead,
        status_code=status.HTTP_201_CREATED,
        name=f"add_{kind}_node",
    )
    async def add_node(graph_id: str, payload: NodeCreate, session: SessionDep) -> NodeRead:
        """Add a stage, an action (inside a stage), a complete node or an execution node."""
        repo = GraphRepository(session)
        graph = await _graph(repo, graph_id)
        try:
            node = await repo.add_node(graph, payload)
        except NodeError as error:
            raise _invalid(error) from error
        await repo.touch(graph)
        await session.commit()
        return (await _node_reads(repo, [node]))[0]

    @router.patch(
        "/{graph_id}/nodes/{node_id}", response_model=NodeRead, name=f"update_{kind}_node"
    )
    async def update_node(
        graph_id: str, node_id: str, payload: NodeUpdate, session: SessionDep
    ) -> NodeRead:
        """Rename, move or resize a node."""
        repo = GraphRepository(session)
        graph = await _graph(repo, graph_id)
        node = await repo.get_node(graph_id, node_id)
        if node is None:
            raise _not_found("Node")
        try:
            await repo.update_node(node, payload)
        except NodeError as error:
            raise _invalid(error) from error
        await repo.touch(graph)
        await session.commit()
        return (await _node_reads(repo, [node]))[0]

    @router.delete(
        "/{graph_id}/nodes/{node_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"delete_{kind}_node",
    )
    async def delete_node(graph_id: str, node_id: str, session: SessionDep) -> Response:
        """Delete a node with its edges (and, for a stage, its actions)."""
        repo = GraphRepository(session)
        graph = await _graph(repo, graph_id)
        node = await repo.get_node(graph_id, node_id)
        if node is None:
            raise _not_found("Node")
        try:
            await repo.delete_node(graph, node)
        except NodeError as error:
            raise _invalid(error) from error
        await repo.touch(graph)
        await session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/{graph_id}/edges",
        response_model=EdgeRead,
        status_code=status.HTTP_201_CREATED,
        name=f"connect_{kind}",
    )
    async def connect(graph_id: str, payload: EdgeCreate, session: SessionDep) -> EdgeRead:
        """Connect an output port to an input port; the output's previous edge is replaced."""
        repo = GraphRepository(session)
        graph = await _graph(repo, graph_id)
        try:
            edge = await repo.connect(graph, payload)
        except (NodeError, EdgeError) as error:
            raise _invalid(error) from error
        await repo.touch(graph)
        await session.commit()
        return EdgeRead.model_validate(edge)

    @router.patch(
        "/{graph_id}/edges/{edge_id}", response_model=EdgeRead, name=f"restyle_{kind}_edge"
    )
    async def restyle_edge(
        graph_id: str, edge_id: str, payload: EdgeUpdate, session: SessionDep
    ) -> EdgeRead:
        """Change how a connection is drawn (curved, straight or elbow)."""
        repo = GraphRepository(session)
        graph = await _graph(repo, graph_id)
        edge = await repo.get_edge(graph_id, edge_id)
        if edge is None:
            raise _not_found("Edge")
        await repo.restyle(edge, payload)
        await repo.touch(graph)
        await session.commit()
        return EdgeRead.model_validate(edge)

    @router.delete(
        "/{graph_id}/edges/{edge_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"disconnect_{kind}",
    )
    async def disconnect(graph_id: str, edge_id: str, session: SessionDep) -> Response:
        """Remove a connection."""
        repo = GraphRepository(session)
        graph = await _graph(repo, graph_id)
        edge = await repo.get_edge(graph_id, edge_id)
        if edge is None:
            raise _not_found("Edge")
        await repo.disconnect(edge)
        await repo.touch(graph)
        await session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


pipelines_router = build_graph_router(GraphKind.PIPELINE)
actions_router = build_graph_router(GraphKind.ACTION)

node_types_router = APIRouter(prefix="/api", tags=["node-types"])


@node_types_router.get("/node-types")
async def list_node_types() -> list[dict[str, Any]]:
    """The kinds of nodes: scope, ports, settings, what they link to (the editor draws from this)."""
    return [t.describe() for t in NODE_TYPES.values()]
