"""Pipeline and action definition API (``/api/pipelines``, ``/api/actions``, ``/api/node-types``).

Both are stored as graphs and share one set of sub-resources; the path picks the kind. Every
change is saved at once (there is no separate "save"): the editor sends what the user did.
"""

from __future__ import annotations

import asyncio
import json
import logging
import weakref
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.agents.service import artifact_inputs_mapped
from openartifact.agents.service import node_hints as agent_node_hints
from openartifact.api.contract import GATED, errors
from openartifact.api.deps import SessionDep
from openartifact.api.schemas import ChainEntryRead, NodeTypeRead
from openartifact.engine.chain import pipeline_chain
from openartifact.engine.executors import CODE_DISABLED_REASON
from openartifact.engine.neighbour_schemas import GraphNeighbours
from openartifact.engine.neighbours import graph_neighbours
from openartifact.exceptions import ArtifactError
from openartifact.graph import contract as graph_contract
from openartifact.graph import observe_state, preflight, publishing, versions
from openartifact.graph.content import graph_of
from openartifact.graph.localize import localize
from openartifact.graph.mock import CASES_KEY, MOCK_KEY
from openartifact.graph.node_types import NODE_TYPES, node_type
from openartifact.graph.repository import GraphRepository, NodeError, PurposeError
from openartifact.graph.rules import EdgeError
from openartifact.graph.schemas import (
    EdgeCreate,
    EdgeRead,
    EdgeUpdate,
    FindingRead,
    GraphContract,
    GraphCreate,
    GraphDetail,
    GraphListRead,
    GraphRead,
    GraphUpdate,
    GraphUses,
    GraphVersionDetail,
    GraphVersionRead,
    LastResult,
    NodeCreate,
    NodeRead,
    NodeUpdate,
    PublishCheck,
    PublishedGraph,
    PublishRequest,
)
from openartifact.i18n.web import language_for
from openartifact.models import (
    Execution,
    Graph,
    GraphKind,
    GraphNode,
    GraphVersion,
    NodeKind,
    RunNodeResult,
)
from openartifact.ui import layout as ui_layout

logger = logging.getLogger(__name__)

#: A lock per graph whose nodes are being changed, held only while a change runs (weak: an idle graph keeps none).
_writing: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


def _graph_writes(graph_id: str) -> asyncio.Lock:
    """The lock that makes changes to the nodes of one graph run one after the other."""
    lock = _writing.get(graph_id)
    if lock is None:
        lock = _writing[graph_id] = asyncio.Lock()
    return lock


_LABELS: dict[GraphKind, str] = {GraphKind.PIPELINE: "Pipeline", GraphKind.ACTION: "Action"}


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


async def _refuse_artifact_mapping(
    session: AsyncSession, kind: str, agent_id: Any, config: dict[str, Any] | None
) -> None:
    """An agent node cannot map an input that comes from the artifact: the agent's definition fixes it (ADR-064)."""
    if kind != NodeKind.AGENT or not config or not str(config.get("inputs") or "").strip():
        return
    if not isinstance(agent_id, str) or not agent_id:
        return
    for name in await artifact_inputs_mapped(session, agent_id, str(config["inputs"])):
        raise _invalid(
            ValueError(f"input '{name}' comes from the artifact and cannot be mapped in the action")
        )


def _invalid(error: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))


async def _node_reads(repo: GraphRepository, nodes: Sequence[GraphNode]) -> list[NodeRead]:
    """Nodes as the API returns them, linked actions with their definition's name and On Fail."""
    described = await repo.describe(nodes)
    numbers = await repo.placement_numbers(nodes)
    reads = [NodeRead.model_validate(n) for n in nodes]
    for read, node in zip(reads, nodes, strict=True):
        read.config = node_type(node.kind).effective_config(node.config)
        read.placement_number = numbers.get(node.id)
        read.mock = (node.config or {}).get(MOCK_KEY)
        read.cases = (node.config or {}).get(CASES_KEY)
        if read.id in described:
            link = described[read.id]
            read.definition_name = link.name
            read.definition_fail_enabled = link.fail_enabled
            read.definition_slug = link.slug
    return reads


async def _observe_mark(
    session: AsyncSession, graph: Graph
) -> Literal["observing", "ended"] | None:
    """What the list says of a pipeline's observe mode (ADR-088): ``observing``, ``ended`` or nothing."""
    if graph.kind != GraphKind.PIPELINE:
        return None
    setting = await observe_state.published_setting(session, graph)
    if setting is None:
        return None
    status_ = observe_state.status_of(graph, setting)
    return "ended" if status_["ended"] else "observing" if status_["observing"] else None


def build_graph_router(kind: GraphKind) -> APIRouter:
    """The router of one kind of graph: ``pipeline`` at ``/api/pipelines``, ``action`` at ``/api/actions``."""
    label = _LABELS[kind]
    router = APIRouter(prefix=f"/api/{kind}s", tags=[f"{kind}s"], responses=GATED)

    def _announce_contract(request: Request, graph_id: str) -> None:
        """A publication or a discarded draft changes what the pipelines that use this graph see as its inputs and outputs (ADR-083 add. 2):
        an editor that shows such a pipeline reads the contract again."""
        request.app.state.event_bus.publish("graph.contract_changed", {"graph_id": graph_id})

    async def _graph(repo: GraphRepository, graph_id: str) -> Graph:
        graph = await repo.get(graph_id)
        if graph is None or graph.kind != kind:  # a graph of the other kind is not found here
            raise _not_found(label)
        return graph

    @router.get(
        "",
        response_model=list[GraphListRead],
        name=f"list_{kind}s",
        summary=f"List {kind}s",
        responses=errors(422),
    )
    async def list_graphs(
        session: SessionDep,
        purpose: Annotated[
            Literal["pipeline", "guard"] | None,
            Query(
                description="Only the actions for pipelines or only the actions for guards (ADR-067); every pipeline is "
                "``pipeline``."
            ),
        ] = None,
        q: Annotated[
            str | None,
            Query(
                max_length=100,
                description="Only the ones whose name, description or a tag contains this text (any case).",
            ),
        ] = None,
        tag: Annotated[
            str | None,
            Query(
                max_length=32, description="Only the ones that carry exactly this tag (any case)."
            ),
        ] = None,
    ) -> list[GraphListRead]:
        """List all of this kind, most recently changed first, each with its description, tags and number of nodes; ``purpose``
        narrows the actions to the ones for pipelines or guards, ``q`` and ``tag`` search (management pages, ADR-069)."""
        repo = GraphRepository(session)
        graphs = await repo.list_all(kind, purpose, q, tag)
        counts = await repo.node_counts([g.id for g in graphs])
        return [
            GraphListRead.model_validate(g).model_copy(
                update={
                    "node_count": counts.get(g.id, 0),
                    "draft_changed": await publishing.draft_changed(session, g),
                    "observe": await _observe_mark(session, g),
                }
            )
            for g in graphs
        ]

    @router.post(
        "",
        response_model=GraphRead,
        status_code=status.HTTP_201_CREATED,
        name=f"create_{kind}",
        summary=f"Create a {kind}",
        responses=errors(422, write=True, body=True),
    )
    async def create_graph(payload: GraphCreate, session: SessionDep) -> GraphRead:
        """Create one; it starts with a trigger (an action definition also with its output). An action is for pipelines or, with
        ``purpose`` ``guard``, only for guards (ADR-067)."""
        try:
            graph = await GraphRepository(session).create(
                payload.name, kind, payload.purpose, payload.description, payload.tags
            )
        except PurposeError as error:
            raise _invalid(error) from None
        await session.commit()
        return GraphRead.model_validate(graph).model_copy(
            update={"draft_changed": await publishing.draft_changed(session, graph)}
        )

    @router.get(
        "/{graph_id}",
        response_model=GraphDetail,
        name=f"get_{kind}",
        summary=f"Get a {kind}",
        responses=errors(404, 422),
    )
    async def get_graph(graph_id: str, session: SessionDep) -> GraphDetail:
        """One with all its nodes and edges."""
        repo = GraphRepository(session)
        graph = await _graph(repo, graph_id)
        nodes, edges = await repo.graph(graph_id)
        return GraphDetail(
            graph=GraphRead.model_validate(graph).model_copy(
                update={"draft_changed": await publishing.draft_changed(session, graph)}
            ),
            nodes=await _node_reads(repo, nodes),
            edges=[EdgeRead.model_validate(e) for e in edges],
        )

    @router.get(
        "/{graph_id}/neighbours",
        response_model=GraphNeighbours,
        name=f"get_{kind}_neighbours",
        summary=f"The predecessors and successors of every node of a {kind}",
        responses=errors(404, 422),
    )
    async def get_neighbours(
        graph_id: str,
        session: SessionDep,
        version: Annotated[
            str,
            Query(
                pattern=r"^(published|draft|[0-9]{1,9})$",
                description="``published`` (default): what executions run, the draft while nothing is published; ``draft``: what the "
                "editor shows; or the number of a published version.",
            ),
        ] = "published",
    ) -> GraphNeighbours:
        """Every node (for a pipeline the trigger, stages, actions, called pipelines and the end; for an action definition its nodes) with
        the nodes that lead to it (``predecessors``) and the ones it leads to (``successors``), each with the connector it hangs on
        (*On Pass*, *On Error*, *On Fail*, a branch, a tool) as the editor draws it. Every connection of the graph appears once as a
        successor and once as a predecessor. ``version`` says which state is read; the answer names the one used."""
        graph = await _graph(GraphRepository(session), graph_id)
        found = await graph_neighbours(session, graph, version)
        if found is None:
            raise _not_found(f"Version {version}")
        return found

    if kind == GraphKind.PIPELINE:

        @router.get(
            "/{graph_id}/stages",
            name="get_stages",
            response_model=list[ChainEntryRead],
            response_model_exclude_unset=True,
            summary="Get the stages of a pipeline",
            responses=errors(404, 422),
        )
        async def get_stages(graph_id: str, session: SessionDep) -> list[dict[str, Any]]:
            """The stages of a pipeline in the order it runs them, with their actions."""
            await _graph(GraphRepository(session), graph_id)
            graph = await graph_of(session, graph_id)
            return pipeline_chain(graph["nodes"], graph["edges"])

    @router.get(
        "/{graph_id}/uses",
        response_model=GraphUses,
        name=f"get_{kind}_uses",
        summary=f"Where a {kind} is used",
        responses=errors(404, 422),
    )
    async def get_uses(graph_id: str, session: SessionDep) -> dict[str, Any]:
        """The places that use it (an action: the stages of pipelines and the guards that run it; a pipeline: pipelines that call
        it and guards attached to it) with a link to each, and for a pipeline how many artifacts start in it and how many runs it
        had."""
        repo = GraphRepository(session)
        return await repo.uses_of(await _graph(repo, graph_id))

    def _version_read(version: GraphVersion, graph: Graph) -> GraphVersionRead:
        nodes = json.loads(version.content).get("nodes", [])
        return GraphVersionRead(
            number=version.number,
            published_at=version.published_at,
            published_via=version.published_via,
            source_number=version.source_number,
            current=graph.published_number == version.number,
            node_count=len(nodes),
        )

    async def _published(
        session: AsyncSession, graph: Graph, version: GraphVersion
    ) -> PublishedGraph:
        counts = await GraphRepository(session).node_counts([graph.id])
        return PublishedGraph(
            graph=GraphListRead.model_validate(graph).model_copy(
                update={
                    "node_count": counts.get(graph.id, 0),
                    "draft_changed": await publishing.draft_changed(session, graph),
                }
            ),
            version=_version_read(version, graph),
        )

    @router.get(
        "/{graph_id}/versions",
        response_model=list[GraphVersionRead],
        name=f"list_{kind}_versions",
        summary=f"List the versions of a {kind}",
        responses=errors(404, 422),
    )
    async def list_versions(graph_id: str, session: SessionDep) -> list[GraphVersionRead]:
        """Every published version, newest first (``current``: the one executions use; ``source_number``: a version made by publishing
        an earlier one again). A {kind} that was never published has none and its draft runs (ADR-070)."""
        graph = await _graph(GraphRepository(session), graph_id)
        return [_version_read(v, graph) for v in await versions.versions_of(session, graph.id)]

    @router.get(
        "/{graph_id}/versions/{number}",
        response_model=GraphVersionDetail,
        name=f"get_{kind}_version",
        summary=f"One version of a {kind}, with its graph",
        responses=errors(404, 422),
    )
    async def get_version(graph_id: str, number: int, session: SessionDep) -> GraphVersionDetail:
        """The frozen graph of a version: its nodes and edges as they were published (to show it read-only)."""
        graph = await _graph(GraphRepository(session), graph_id)
        version = await versions.get_version(session, graph.id, number)
        if version is None:
            raise _not_found(f"Version {number}")
        content = json.loads(version.content)
        nodes, edges = content.get("nodes", []), content.get("edges", [])
        return GraphVersionDetail(
            **_version_read(version, graph).model_dump(),
            name=content.get("name", ""),
            nodes=nodes,
            edges=edges,
            stages=pipeline_chain(nodes, edges) if kind == GraphKind.PIPELINE else None,
        )

    @router.get(
        "/{graph_id}/check",
        response_model=PublishCheck,
        name=f"check_{kind}",
        summary=f"Check the draft of a {kind} before it is published",
        responses=errors(404, 422),
    )
    async def check_graph(graph_id: str, session: SessionDep) -> PublishCheck:
        """What publishing the draft would run into (ADR-082): every reference that names something that is not there, a secret that
        does not exist, a required input without a value (errors), and what may not work (warnings). Reads only, runs nothing."""
        graph = await _graph(GraphRepository(session), graph_id)
        found = [FindingRead(**f.as_dict()) for f in await preflight.check(session, graph.id)]
        return PublishCheck(
            findings=found,
            errors=sum(1 for f in found if f.level == "error"),
            warnings=sum(1 for f in found if f.level == "warning"),
        )

    @router.get(
        "/{graph_id}/contract",
        response_model=GraphContract,
        name=f"contract_of_{kind}",
        summary=f"The inputs and outputs of the version of a {kind} that runs",
        responses=errors(404, 422),
    )
    async def graph_contract_of(graph_id: str, session: SessionDep) -> GraphContract:
        """What the pipelines that use this graph see (ADR-083 add. 2): the contract of the **published** version, the draft's only while
        nothing is published (the engine runs the draft then). While the draft has changes `draft_changed` is true and the newer contract waits
        for Publish; Discard draft brings the published one back."""
        graph = await _graph(GraphRepository(session), graph_id)
        found = await graph_contract.contract_of(session, graph.id)
        if found is None:
            raise HTTPException(404, "No such graph")
        return GraphContract(**found)

    @router.post(
        "/{graph_id}/publish",
        response_model=PublishedGraph,
        name=f"publish_{kind}",
        summary=f"Publish a {kind}",
        responses=errors(404, 409, 422, write=True),
    )
    async def publish_graph(
        graph_id: str, request: Request, session: SessionDep, body: PublishRequest | None = None
    ) -> PublishedGraph:
        """Publish the draft as a new version; executions that start from now on use it. 409 when the draft equals the published
        version (nothing new to publish), and 409 with ``findings`` when the check (``GET .../check``) found something and the body
        does not say ``{"acknowledge": true}``: the caller has seen the findings and publishes anyway (ADR-082)."""
        graph = await _graph(GraphRepository(session), graph_id)
        if not (body and body.acknowledge) and await publishing.would_change(session, graph):
            found = await preflight.check(session, graph.id)
            if found:
                raise ArtifactError(
                    409,
                    f"The check found {len(found)} thing(s) to look at before publishing; "
                    "publish again with acknowledge to publish anyway",
                    code="findings",
                    extra={"findings": [f.as_dict() for f in found]},
                )
        version = await publishing.publish(session, graph, "user")
        await session.commit()
        _announce_contract(request, graph.id)
        return await _published(session, graph, version)

    @router.post(
        "/{graph_id}/draft/discard",
        response_model=GraphDetail,
        name=f"discard_{kind}_draft",
        summary=f"Discard the draft of a {kind}",
        responses=errors(404, 409, 422, write=True),
    )
    async def discard_draft(graph_id: str, request: Request, session: SessionDep) -> GraphDetail:
        """Throw the changes since the published version away: the draft becomes that version again (nodes, connections, settings).
        What an execution runs does not change. 409 while nothing is published and when the draft equals the published version.
        Answers the graph as it is now."""
        repo = GraphRepository(session)
        graph = await _graph(repo, graph_id)
        report = await publishing.discard_draft(session, graph)
        await session.commit()
        _announce_contract(request, graph.id)
        if report.graphs:
            request.app.state.event_bus.publish(
                "graph.changed", {"graph_ids": sorted(report.graphs)}
            )
        return await get_graph(graph_id, session)

    @router.post(
        "/{graph_id}/versions/{number}/republish",
        response_model=PublishedGraph,
        name=f"republish_{kind}_version",
        summary=f"Publish an earlier version of a {kind} again",
        responses=errors(404, 409, 422, write=True),
    )
    async def republish_graph(
        graph_id: str, number: int, request: Request, session: SessionDep
    ) -> PublishedGraph:
        """Publish an earlier version again (a rollback): a new version with that version's content, the history stays and the draft is
        not touched. 409 when it is the published one already."""
        graph = await _graph(GraphRepository(session), graph_id)
        version = await publishing.republish(session, graph, number, "user")
        await session.commit()
        _announce_contract(request, graph.id)
        return await _published(session, graph, version)

    @router.patch(
        "/{graph_id}",
        response_model=GraphRead,
        name=f"rename_{kind}",
        summary=f"Change a {kind}: its name, purpose, description or tags",
        responses=errors(404, 409, 422, write=True, body=True),
    )
    async def rename_graph(graph_id: str, payload: GraphUpdate, session: SessionDep) -> GraphRead:
        """Rename it, and for an action change its purpose (ADR-067): a definition used by a stage cannot become a guard action, one
        run by a guard cannot become a pipeline action, and neither can one that holds a node only the other kind may use; the 409
        answer says where."""
        repo = GraphRepository(session)
        graph = await _graph(repo, graph_id)
        if payload.purpose is not None:
            if kind != GraphKind.ACTION:
                raise _invalid(ValueError("Only an action has a purpose"))
            try:
                await repo.change_purpose(graph, payload.purpose)
            except PurposeError as error:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail=str(error)
                ) from None
        if payload.name is not None:
            await repo.rename(graph, payload.name)
        if payload.description is not None:
            graph.description = payload.description
        if payload.tags is not None:
            graph.tags = list(payload.tags)
        await session.commit()
        return GraphRead.model_validate(graph)

    @router.delete(
        "/{graph_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"delete_{kind}",
        summary=f"Delete a {kind}",
        responses=errors(404, 422, write=True),
    )
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
        summary=f"Add a node to a {kind}",
        responses=errors(404, 422, write=True, body=True),
    )
    async def add_node(graph_id: str, payload: NodeCreate, session: SessionDep) -> NodeRead:
        """Add a stage, an action (inside a stage), a complete node or an execution node."""
        repo = GraphRepository(session)
        graph = await _graph(repo, graph_id)
        await _refuse_artifact_mapping(
            session, payload.kind, (payload.config or {}).get("agent_id"), payload.config
        )
        try:
            node = await repo.add_node(graph, payload)
        except NodeError as error:
            raise _invalid(error) from error
        await repo.touch(graph)
        await session.commit()
        read = (await _node_reads(repo, [node]))[0]
        read.warnings = await repo.reference_hints(node)
        if node.kind == NodeKind.AGENT:
            read.warnings += await agent_node_hints(session, node)
        return read

    @router.patch(
        "/{graph_id}/nodes/{node_id}",
        response_model=NodeRead,
        name=f"update_{kind}_node",
        summary=f"Update a node of a {kind}",
        responses=errors(404, 422, write=True, body=True),
    )
    async def update_node(
        graph_id: str, node_id: str, payload: NodeUpdate, session: SessionDep, request: Request
    ) -> NodeRead:
        """Rename, move or resize a node. ``warnings`` lists problems with the node's context references.

        The error output is one state of an action definition and its uses (ADR-061 addendum): ``notices`` says what a
        change did beyond the node (the definition's On Fail, other uses, connections that were disconnected) and
        ``reload`` that other nodes of this graph changed; ``graph.changed`` goes out for the other graphs."""
        repo = GraphRepository(session)
        # one change of a graph's nodes at a time: the config is read, merged and written, and two settings saved at once
        # (two controls of the inspector) would otherwise lose one of them (one process per data directory, ADR-094)
        async with _graph_writes(graph_id):
            return await _update_node(repo, graph_id, node_id, payload, session, request)

    async def _update_node(
        repo: GraphRepository,
        graph_id: str,
        node_id: str,
        payload: NodeUpdate,
        session: AsyncSession,
        request: Request,
    ) -> NodeRead:
        graph = await _graph(repo, graph_id)
        node = await repo.get_node(graph_id, node_id)
        if node is None:
            raise _not_found("Node")
        await _refuse_artifact_mapping(
            session,
            node.kind,
            (payload.config or {}).get("agent_id", (node.config or {}).get("agent_id")),
            payload.config,
        )
        known: set[str] = set()
        if (
            payload.mock is not None or payload.cases is not None
        ):  # no secret may end up in a mock (ADR-087)
            store = request.app.state.secret_store
            try:
                known = set((await store.resolve([s.name for s in await store.names()])).values())
            except Exception as error:  # secrets not available: only the reference form is checked
                logger.warning(
                    "The secret store could not be read (%s): the mock of node %s is checked "
                    "for secret references only, not for secret values",
                    error,
                    node.id,
                )
                known = set()
        try:
            report = await repo.update_node(node, payload, known)
        except NodeError as error:
            raise _invalid(error) from error
        await repo.touch(graph)
        await session.commit()
        if report.graphs:
            request.app.state.event_bus.publish(
                "graph.changed", {"graph_ids": sorted(report.graphs)}
            )
        read = (await _node_reads(repo, [node]))[0]
        read.warnings = await repo.reference_hints(node)
        read.notices, read.reload = report.notices, report.reload
        if node.kind == NodeKind.AGENT:
            read.warnings += await agent_node_hints(session, node)
        return read

    @router.get(
        "/{graph_id}/nodes/{node_id}/last-result",
        response_model=LastResult,
        name=f"last_result_of_{kind}_node",
        summary="The newest stored result of a node (the source of a mock)",
        responses=errors(404, 422),
    )
    async def last_result(graph_id: str, node_id: str, session: SessionDep) -> LastResult:
        """The result the node left in its newest step of a **real** run (a dry run's skipped or mocked step is no real data), as a mock takes it
        (ADR-087): ``found`` is false while it never ran."""
        repo = GraphRepository(session)
        await _graph(repo, graph_id)
        node = await repo.get_node(graph_id, node_id)
        if node is None:
            raise _not_found("Node")
        row = (
            await session.execute(
                select(RunNodeResult)
                .join(Execution, Execution.id == RunNodeResult.execution_id)
                .where(RunNodeResult.node_id == node_id, Execution.dry_run.is_(False))
                .order_by(RunNodeResult.started_at.desc(), RunNodeResult.seq.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return LastResult(found=False)
        data = {k: v for k, v in (row.data or {}).items() if k not in ("mock", "dry_run")}
        return LastResult(
            found=True,
            outcome="fail" if row.outcome == "fail" else "pass",
            output=row.output or "",
            reason=row.reason or "",
            data=data,
        )

    @router.delete(
        "/{graph_id}/nodes/{node_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"delete_{kind}_node",
        summary=f"Delete a node of a {kind}",
        responses=errors(404, 422, write=True),
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
        summary=f"Connect two nodes of a {kind}",
        responses=errors(404, 422, write=True, body=True),
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
        "/{graph_id}/edges/{edge_id}",
        response_model=EdgeRead,
        name=f"restyle_{kind}_edge",
        summary=f"Restyle an edge of a {kind}",
        responses=errors(404, 422, write=True, body=True),
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
        summary=f"Remove an edge of a {kind}",
        responses=errors(404, 422, write=True),
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

#: The kinds that run text as a child process of the application: the node and the tool of an agent.
EXECUTE_COMMAND_KINDS = frozenset({"code", "code_tool"})

node_types_router = APIRouter(prefix="/api", tags=["node-types"], responses=GATED)


@node_types_router.get(
    "/node-types",
    response_model=list[NodeTypeRead],
    response_model_exclude_unset=True,
    summary="List node types",
)
async def list_node_types(request: Request, session: SessionDep) -> list[dict[str, Any]]:
    """The kinds of nodes: scope, ports, settings, what they link to (the editor draws from this). The texts are in the
    language of the request (cookie ``oa_lang``, else ``Accept-Language``) where a translation exists, else English; the
    stored values (kinds, setting keys, options) never change."""
    saved = await ui_layout.load_all(session)
    described = [
        ui_layout.apply_layout(f"nodes/{t.kind}", t.describe(), saved.get(f"nodes/{t.kind}"))
        for t in NODE_TYPES.values()
    ]
    if (
        not request.app.state.settings.code_nodes_enabled
    ):  # Execute Command nodes are switched off on this instance (ADR-075)
        for entry in described:
            if entry["kind"] in EXECUTE_COMMAND_KINDS:
                entry["unavailable"] = CODE_DISABLED_REASON
    return localize(described, language_for(request))
