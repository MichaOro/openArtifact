"""Persistence for graph definitions. Receives an ``AsyncSession``; never creates its own."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, NamedTuple, cast

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.artifact_fields.service import field_specs
from openartifact.engine.context import NodeIndex, node_key, problems
from openartifact.graph.node_types import (
    NODE_TYPES,
    FailureMode,
    NodeType,
    Port,
    Ports,
    SettingError,
    fixed_in,
    kinds_in,
    node_type,
    switch_case_used,
)
from openartifact.graph.rules import Endpoint, validate_edge
from openartifact.graph.schemas import EdgeCreate, EdgeUpdate, NodeCreate, NodeUpdate
from openartifact.graph.slug import slugify
from openartifact.graph.versions import published_node_kinds, published_users
from openartifact.models import (
    Execution,
    Graph,
    GraphEdge,
    GraphKind,
    GraphNode,
    GuardAttachment,
    GuardDefinition,
    NodeKind,
    Task,
)


class NodeError(ValueError):
    """The requested node (or change of it) is not valid."""


class PurposeError(ValueError):
    """The purpose of an action definition cannot change, or does not fit where it is used; the message says where."""


class LinkInfo(NamedTuple):
    """What a linked node shows of the graph it links to."""

    name: str
    fail_enabled: bool  # the definition has an On Fail output
    slug: str


@dataclass
class SyncReport:
    """What a change did beyond the node itself: the error output is one state of an action definition and its uses
    (ADR-061 addendum), so a change on one side can change the other. ``notices`` are machine readable, the editor turns
    them into its short messages; ``graphs`` are the OTHER graphs whose nodes or edges changed (open editors reload);
    ``reload`` says that other nodes of the edited graph changed too."""

    notices: list[dict[str, Any]] = field(default_factory=list)
    graphs: set[str] = field(default_factory=set)
    reload: bool = False


def _mode(node: GraphNode) -> str:
    """The setting *If the node fails* of a node as stored (unset: Stop the run)."""
    return str((node.config or {}).get("on_failure", FailureMode.FAIL))


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


def _port_phrase(port: Port) -> str:
    """How a message names a connector that a setting can take away: the error output, or the connector by its label."""
    return "error output" if port.name in (Ports.FAIL, Ports.ERROR) else f"connector '{port.label}'"


def _hidden_port_message(kind_type: NodeType, node: GraphNode, port_name: str) -> str:
    port = next(p for p in (*kind_type.inputs, *kind_type.outputs) if p.name == port_name)
    when = port.visible_when or {}
    setting = next((s for s in kind_type.settings if s.key == when.get("setting")), None)
    how = ""
    if setting is not None:
        shown = (setting.option_labels or {}).get(when["equals"], when["equals"])
        how = f": set '{setting.label}' to '{shown}' first"
    return f"The {_port_phrase(port)} of '{node.name}' is off{how}"


def _disconnected(count: int, places: list[dict[str, Any]], inner: int) -> dict[str, Any]:
    """The notice that connections were disconnected: how many, where (``places``), and how many of them inside the
    definition itself (``inner``)."""
    return {"kind": "disconnected", "count": count, "places": places, "inner": inner}


class GraphRepository:
    """Database access for graphs, their nodes and edges."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── graphs ─────────────────────────────────────────────────────

    async def create(
        self,
        name: str,
        kind: GraphKind = GraphKind.PIPELINE,
        purpose: str = "pipeline",
        description: str = "",
        tags: Sequence[str] = (),
    ) -> Graph:
        """Create a graph with its fixed nodes, connected with each other.

        A pipeline gets a trigger and a complete, an action definition a trigger and an output. An action definition is for
        pipelines or for guards (``purpose``, ADR-067); a pipeline has no other purpose than ``pipeline``.
        """
        if purpose not in ("pipeline", "guard"):
            raise PurposeError("The purpose of an action is pipeline or guard")
        if purpose == "guard" and kind != GraphKind.ACTION:
            raise PurposeError("Only an action can be for guards")
        graph = Graph(
            id=str(uuid.uuid4()),
            name=name,
            kind=kind,
            purpose=purpose,
            description=description,
            tags=list(tags),
        )
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

    async def list_all(
        self,
        kind: GraphKind = GraphKind.PIPELINE,
        purpose: str | None = None,
        q: str | None = None,
        tag: str | None = None,
    ) -> Sequence[Graph]:
        """All graphs (or action definitions, of one ``purpose`` when given), most recently changed first. ``q`` keeps the ones whose
        name, description or a tag contains the text (any case); ``tag`` the ones that carry exactly this tag (any case)."""
        query = select(Graph).where(Graph.kind == kind)
        if purpose is not None:
            query = query.where(Graph.purpose == purpose)
        result = await self._session.execute(query.order_by(Graph.updated_at.desc(), Graph.id))
        graphs = result.scalars().all()
        if q and q.strip():
            needle = q.strip().lower()
            graphs = [
                g
                for g in graphs
                if needle in g.name.lower()
                or needle in (g.description or "").lower()
                or any(needle in t.lower() for t in g.tags or [])
            ]
        if tag and tag.strip():
            wanted = tag.strip().lower()
            graphs = [g for g in graphs if wanted in [t.lower() for t in g.tags or []]]
        return graphs

    async def node_counts(self, graph_ids: Sequence[str]) -> dict[str, int]:
        """How many nodes each graph holds (the card of the management page says it)."""
        if not graph_ids:
            return {}
        rows = await self._session.execute(
            select(GraphNode.graph_id, func.count())
            .where(GraphNode.graph_id.in_(graph_ids))
            .group_by(GraphNode.graph_id)
        )
        return {graph_id: count for graph_id, count in rows.all()}

    async def uses_of(self, graph: Graph) -> dict[str, Any]:
        """Where a definition is used, for the Usage tab: an action definition by the stages of pipelines and by guards; a pipeline
        by pipelines that call it, by guards attached to it and by the artifacts that start in it (with how many runs it had)."""
        uses: list[dict[str, str]] = []
        if graph.kind == GraphKind.ACTION:
            rows = await self._session.execute(
                select(Graph.name, Graph.slug, GraphNode.stage_id)
                .join(GraphNode, GraphNode.graph_id == Graph.id)
                .where(GraphNode.kind == NodeKind.ACTION.value, GraphNode.definition_id == graph.id)
                .order_by(Graph.name)
            )
            for name, slug, stage_id in rows.all():
                stage = await self._session.get(GraphNode, stage_id) if stage_id else None
                uses.append(
                    {
                        "kind": "stage",
                        "name": name,
                        "href": f"/pipelines/{slug}",
                        "detail": stage.name if stage else "",
                    }
                )
            listed = {u["name"] for u in uses}
            for user, number in await published_users(self._session, NodeKind.ACTION, graph.id):
                if (
                    user.name not in listed
                ):  # its draft no longer uses it, its published version still does
                    uses.append(
                        {
                            "kind": "stage",
                            "name": user.name,
                            "href": f"/pipelines/{user.slug}",
                            "detail": f"v{number} published",
                        }
                    )
            for (guard_name,) in (
                await self._session.execute(
                    select(GuardDefinition.name)
                    .where(GuardDefinition.action_id == graph.id)
                    .order_by(GuardDefinition.name)
                )
            ).all():
                uses.append({"kind": "guard", "name": guard_name, "href": "/guards", "detail": ""})
            return {"uses": uses, "artifacts": None, "executions": None}
        for name, slug in (
            await self._session.execute(
                select(Graph.name, Graph.slug)
                .join(GraphNode, GraphNode.graph_id == Graph.id)
                .where(
                    GraphNode.kind == NodeKind.PIPELINE.value, GraphNode.definition_id == graph.id
                )
                .distinct()
                .order_by(Graph.name)
            )
        ).all():
            uses.append(
                {"kind": "pipeline", "name": name, "href": f"/pipelines/{slug}", "detail": ""}
            )
        listed = {u["name"] for u in uses}
        for user, number in await published_users(self._session, NodeKind.PIPELINE, graph.id):
            if user.name not in listed:
                uses.append(
                    {
                        "kind": "pipeline",
                        "name": user.name,
                        "href": f"/pipelines/{user.slug}",
                        "detail": f"v{number} published",
                    }
                )
        for (guard_name,) in (
            await self._session.execute(
                select(GuardDefinition.name)
                .join(GuardAttachment, GuardAttachment.guard_id == GuardDefinition.id)
                .where(GuardAttachment.graph_id == graph.id)
                .distinct()
                .order_by(GuardDefinition.name)
            )
        ).all():
            uses.append({"kind": "guard", "name": guard_name, "href": "/guards", "detail": ""})
        artifacts = await self._session.scalar(
            select(func.count()).select_from(Task).where(Task.pipeline_id == graph.id)
        )
        executions = await self._session.scalar(
            select(func.count()).select_from(Execution).where(Execution.pipeline_id == graph.id)
        )
        return {"uses": uses, "artifacts": artifacts or 0, "executions": executions or 0}

    async def places_of(self, graph: Graph) -> tuple[list[str], list[str]]:
        """Where an action definition is used: the names of the pipelines whose stages use it and of the guards that run it."""
        pipelines = await self._session.scalars(
            select(Graph.name)
            .join(GraphNode, GraphNode.graph_id == Graph.id)
            .where(GraphNode.kind == NodeKind.ACTION.value, GraphNode.definition_id == graph.id)
            .distinct()
            .order_by(Graph.name)
        )
        guards = await self._session.scalars(
            select(GuardDefinition.name)
            .where(GuardDefinition.action_id == graph.id)
            .order_by(GuardDefinition.name)
        )
        names = list(pipelines)
        # a pipeline whose published version still uses it runs it, whatever its draft says (ADR-070)
        for user, _number in await published_users(self._session, NodeKind.ACTION, graph.id):
            if user.name not in names:
                names.append(user.name)
        return sorted(names), list(guards)

    async def change_purpose(self, graph: Graph, purpose: str) -> None:
        """Make an action definition for pipelines or for guards (ADR-067). It must not be used on the other side and must not
        hold a node of a kind that is not for the new purpose; the error names where."""
        if graph.kind != GraphKind.ACTION:
            raise PurposeError("Only an action has a purpose")
        if purpose not in ("pipeline", "guard"):
            raise PurposeError("The purpose of an action is pipeline or guard")
        if graph.purpose == purpose:
            return
        pipelines, guards = await self.places_of(graph)
        if purpose == "guard" and pipelines:
            raise PurposeError(
                f"'{graph.name}' is used by the stages of {_names(pipelines)}: take it out there before it becomes a guard action"
            )
        if purpose == "pipeline" and guards:
            raise PurposeError(
                f"'{graph.name}' is run by the {'guard' if len(guards) == 1 else 'guards'} {_names(guards)}: choose another action there before it becomes a pipeline action"
            )
        nodes, _ = await self.graph(graph.id)
        kinds = {n.kind for n in nodes} | await published_node_kinds(
            self._session, graph
        )  # the published version runs too
        unfit = sorted({node_type(k).label for k in kinds if purpose not in node_type(k).purposes})
        if unfit:
            raise PurposeError(
                f"'{graph.name}' holds {_names(unfit)}, which can only be used in a {'pipeline' if purpose == 'guard' else 'guard'} action: take "
                f"{'it' if len(unfit) == 1 else 'them'} out first"
            )
        graph.purpose = purpose
        await self._session.flush()

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
        """Problems with the ``${node...}`` references of a node's settings (HTTP: URL, headers, body; If, Switch).

        Only hints (the node is saved anyway): names that two nodes of the same action share, names
        no node of any action has, malformed references. Which pipeline runs the action, and so which
        nodes are around it, is only known at run time, where such a reference fails the node.
        """
        kind = node_type(node.kind)
        if not kind.reference_keys:
            return []
        config = kind.effective_config(node.config)
        text = "\n".join(str(config.get(k) or "") for k in kind.reference_keys)
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
        results = [k for k in NodeKind if node_type(k).produces_result]
        others = await self._session.execute(
            select(GraphNode.name).where(
                GraphNode.graph_id != node.graph_id, GraphNode.kind.in_(results)
            )
        )
        keys = {node_key(name) for (name,) in others}
        fields = {spec.name for spec in await field_specs(self._session)}
        return problems(text, local, lambda key: key in keys, fields)

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
        if graph.kind == GraphKind.ACTION and graph.purpose not in kind_type.purposes:
            raise NodeError(
                f"A {kind_type.label} can only be used in a {'guard' if graph.purpose == 'pipeline' else 'pipeline'} action"
            )
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

    async def update_node(self, node: GraphNode, data: NodeUpdate) -> SyncReport:
        """Rename, move or (stages) resize a node, or change its settings.

        The error output is one state of an action definition (its Output's *On Fail*) and its uses (*If the action
        fails: Error output*): a change on one side is carried to the other in this same transaction, and a change that
        takes a connector away disconnects what was connected there instead of refusing (ADR-061 addendum). The report
        says what happened beyond the node.
        """
        report = SyncReport()
        sent = data.model_fields_set
        kind_type = node_type(node.kind)
        if {"width", "height"} & sent and kind_type.size is None:
            raise NodeError("Only stages have a size")
        own = {s.key for s in kind_type.settings}
        settings = _setting_keys()
        for key in settings & sent - own:
            raise NodeError(f"A {node.kind} has no setting '{key}'")
        previous_mode = _mode(node)
        previous_fail = node.fail_enabled
        if data.config is not None:
            merged = _merged_config(kind_type, node.config, data.config)
            dropped = await self._drop_hidden_edges(node, kind_type, merged)
            node.config = merged
            if dropped:
                place = await self._place(node)
                report.notices.append(_disconnected(dropped, [{**place, "count": dropped}], 0))
        if "definition_id" in sent:
            await self._link(node, data.definition_id)
        for field_name in ("name", "x", "y", "width", "height", *sorted(settings)):
            value = getattr(data, field_name)
            if field_name in sent and value is not None:
                setattr(node, field_name, value)
        await self._session.flush()
        if node.kind == NodeKind.SWITCH and data.config is not None:
            unused = [
                p
                for p in node_type(node.kind).output_names()
                if p.startswith("case_") and not switch_case_used(node.config, p)
            ]
            await (
                self._session.execute(  # a case without a value has no output: its connection goes
                    delete(GraphEdge).where(
                        GraphEdge.source_id == node.id, GraphEdge.source_port.in_(unused)
                    )
                )
            )
        if (
            node.kind == NodeKind.OUTPUT
            and "fail_enabled" in sent
            and node.fail_enabled != previous_fail
        ):
            await self._sync_definition(node, report)
        elif node.kind == NodeKind.ACTION and ("config" in sent or "definition_id" in sent):
            await self._sync_use(node, previous_mode, "definition_id" in sent, report)
        if node.graph_id in report.graphs:  # other nodes of this very graph changed
            report.graphs.discard(node.graph_id)
            report.reload = True
        await self._touch_ids(report.graphs)
        return report

    async def _place(self, node: GraphNode) -> dict[str, Any]:
        """Where a node is, as a notice names it: its graph, its stage and its own name."""
        graph = await self._session.get(Graph, node.graph_id)
        stage = await self._session.get(GraphNode, node.stage_id) if node.stage_id else None
        return {
            "graph": graph.name if graph else None,
            "stage": stage.name if stage else None,
            "node": node.name,
        }

    async def _drop_hidden_edges(
        self, node: GraphNode, kind_type: NodeType, config: dict[str, Any]
    ) -> int:
        """Delete the connections at the connectors that a setting takes away (the error output); how many."""
        count = 0
        for port in (*kind_type.inputs, *kind_type.outputs):
            if not kind_type.port_hidden(config, port.name):
                continue
            result = await self._session.execute(
                delete(GraphEdge).where(
                    or_(
                        and_(GraphEdge.source_id == node.id, GraphEdge.source_port == port.name),
                        and_(GraphEdge.target_id == node.id, GraphEdge.target_port == port.name),
                    )
                )
            )
            count += int(cast("CursorResult[Any]", result).rowcount or 0)
        return count

    async def _outputs(self, definition_id: str) -> list[GraphNode]:
        """The Output nodes of an action definition (older ones may hold several; they agree)."""
        found = await self._session.scalars(
            select(GraphNode).where(
                GraphNode.graph_id == definition_id, GraphNode.kind == NodeKind.OUTPUT.value
            )
        )
        return list(found)

    async def _uses(self, definition_id: str, *, besides: str | None = None) -> list[GraphNode]:
        """The action nodes of all pipelines that run this definition (``besides``: not this node)."""
        statement = select(GraphNode).where(
            GraphNode.kind == NodeKind.ACTION.value, GraphNode.definition_id == definition_id
        )
        if besides is not None:
            statement = statement.where(GraphNode.id != besides)
        found = await self._session.scalars(statement.order_by(GraphNode.created_at, GraphNode.id))
        return list(found)

    async def _promote_uses(self, uses: Sequence[GraphNode], report: SyncReport) -> None:
        """Uses that stop the run on a failure get the error output (an unconnected one fails the run as before)."""
        for use in uses:
            if _mode(use) == FailureMode.FAIL:
                use.config = {**(use.config or {}), "on_failure": FailureMode.ERROR_OUTPUT}
                report.graphs.add(use.graph_id)

    async def _sync_definition(self, output: GraphNode, report: SyncReport) -> None:
        """The *On Fail* switch of a definition's Output changed: carry it to the other Outputs and to every use."""
        outputs = await self._outputs(output.graph_id)
        enabled = output.fail_enabled
        for other in outputs:
            other.fail_enabled = enabled
        await self._session.flush()
        if enabled:
            await self._promote_uses(await self._uses(output.graph_id), report)
        else:
            await self._definition_off(output.graph_id, outputs, report)

    async def _definition_off(
        self, definition_id: str, outputs: Sequence[GraphNode], report: SyncReport
    ) -> None:
        """The definition has no error output any more: disconnect what was connected at it, in the definition and in
        every use, and let the uses that followed it stop the run again. Nothing else is repaired."""
        inner = 0
        for out in outputs:
            out.fail_enabled = False
            result = await self._session.execute(
                delete(GraphEdge).where(
                    GraphEdge.target_id == out.id, GraphEdge.target_port == Ports.FAIL
                )
            )
            inner += int(cast("CursorResult[Any]", result).rowcount or 0)
        places: list[dict[str, Any]] = []
        for use in await self._uses(definition_id):
            result = await self._session.execute(
                delete(GraphEdge).where(
                    GraphEdge.source_id == use.id, GraphEdge.source_port == Ports.ERROR
                )
            )
            cut = int(cast("CursorResult[Any]", result).rowcount or 0)
            changed = cut > 0
            if _mode(use) == FailureMode.ERROR_OUTPUT:
                use.config = {**(use.config or {}), "on_failure": FailureMode.FAIL}
                changed = True
            if changed:
                report.graphs.add(use.graph_id)
            if cut:
                places.append({**await self._place(use), "count": cut})
        total = inner + sum(p["count"] for p in places)
        if inner:
            definition = await self._session.get(Graph, definition_id)
            places.append(
                {
                    "graph": definition.name if definition else None,
                    "stage": None,
                    "node": outputs[0].name if outputs else "Output",
                    "count": inner,
                }
            )
        report.graphs.add(definition_id)  # its Output has no On Fail now
        if total:
            report.notices.append(_disconnected(total, places, inner))
        await self._session.flush()

    async def _sync_use(
        self, use: GraphNode, previous_mode: str, linked: bool, report: SyncReport
    ) -> None:
        """An action node (a use of a definition) changed its error mode or its definition: carry it to the definition."""
        if use.definition_id is None:
            return
        definition_id = use.definition_id
        definition = await self._session.get(Graph, definition_id)
        outputs = await self._outputs(definition_id)
        if definition is None or not outputs:
            return
        flag = any(o.fail_enabled for o in outputs)
        mode = _mode(use)
        others = await self._uses(definition_id, besides=use.id)
        if mode == FailureMode.ERROR_OUTPUT and (previous_mode != mode or linked):
            if not flag:  # it has the error output now, so the definition offers it, and so does every other use
                for out in outputs:
                    out.fail_enabled = True
                report.graphs.add(definition_id)
                await self._promote_uses(others, report)
                if others:
                    report.notices.append(
                        {
                            "kind": "definition_on",
                            "definition": definition.name,
                            "uses": len(others),
                        }
                    )
        elif mode == FailureMode.FAIL and linked and flag:
            use.config = {**(use.config or {}), "on_failure": FailureMode.ERROR_OUTPUT}
        elif (
            previous_mode == FailureMode.ERROR_OUTPUT
            and mode != previous_mode
            and flag
            and not linked
        ):
            still = [u for u in others if _mode(u) == FailureMode.ERROR_OUTPUT]
            if still:
                report.notices.append(
                    {
                        "kind": "definition_stays_on",
                        "definition": definition.name,
                        "uses": len(still),
                    }
                )
            else:
                await self._definition_off(definition_id, outputs, report)
        await self._session.flush()

    async def _touch_ids(self, graph_ids: set[str]) -> None:
        """Mark other graphs that a change reached as changed."""
        for graph_id in graph_ids:
            graph = await self._session.get(Graph, graph_id)
            if graph is not None:
                graph.updated_at = datetime.now(UTC)
        await self._session.flush()

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
            if not calls and target.purpose != "pipeline":
                raise NodeError(
                    f"'{target.name}' is a guard action: only a guard can run it, a stage takes a pipeline action"
                )
            if calls and await self._calls(definition_id, graph.id):
                raise NodeError("A pipeline cannot call itself, not even through other pipelines")
        node.definition_id = definition_id
        await self._session.flush()

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
        by_definition: dict[str, LinkInfo] = {}
        for (
            row
        ) in rows:  # older definitions may hold several Outputs: it has On Fail if any of them has
            known = by_definition.get(row[0])
            by_definition[row[0]] = LinkInfo(
                row[1], bool(row[2]) or bool(known and known.fail_enabled), row[3]
            )
        return {
            n.id: by_definition[n.definition_id] for n in nodes if n.definition_id in by_definition
        }

    async def restore(self, graph: Graph, content: dict[str, Any]) -> SyncReport:
        """Make the draft the graph of ``content`` (a published version): *Discard draft* (ADR-070 addendum).

        Nodes that are in the version stay the rows they are (same id, so the guards attached to them stay) and take its values;
        nodes that are not in it go (with the guards attached to them), nodes only the version has are made again, and the
        connections are replaced. The error output is one state of an action definition and its uses (ADR-061 addendum): a
        definition whose *On Fail* changes is carried to its uses, and a restored use is made to agree with its definition, in
        this same transaction, exactly as an edit of a node does. A link to a definition that no longer exists is left empty.
        """
        report = SyncReport()
        nodes, _ = await self.graph(graph.id)
        before = {n.id: n for n in nodes}
        wanted = {str(n["id"]): n for n in content.get("nodes", [])}
        had_fail = any(n.fail_enabled for n in nodes if n.kind == NodeKind.OUTPUT.value)
        gone = [i for i in before if i not in wanted]
        if gone:
            await self._session.execute(
                delete(GuardAttachment).where(
                    GuardAttachment.graph_id == graph.id, GuardAttachment.scope_id.in_(gone)
                )
            )
        await self._session.execute(delete(GraphEdge).where(GraphEdge.graph_id == graph.id))
        if gone:
            await self._session.execute(delete(GraphNode).where(GraphNode.id.in_(gone)))
            for node_id in gone:
                self._session.expunge(before.pop(node_id))
        await self._session.flush()
        known = set(
            await self._session.scalars(
                select(Graph.id).where(
                    Graph.id.in_(
                        {str(n["definition_id"]) for n in wanted.values() if n.get("definition_id")}
                    )
                )
            )
        )
        # a stage is stored before the actions inside it
        ordered = sorted(wanted.values(), key=lambda n: n.get("stage_id") is not None)
        for data in ordered:
            row = before.get(str(data["id"]))
            if row is None:
                row = GraphNode(id=str(data["id"]), graph_id=graph.id)
                self._session.add(row)
            row.kind, row.stage_id, row.name = data["kind"], data.get("stage_id"), data["name"]
            row.x, row.y = data.get("x") or 0.0, data.get("y") or 0.0
            row.width, row.height = data.get("width"), data.get("height")
            row.fail_enabled = bool(data.get("fail_enabled"))
            row.seconds = data.get("seconds")
            row.config = dict(data.get("config") or {})
            definition = data.get("definition_id")
            row.definition_id = definition if definition in known else None
            await self._session.flush()
        for edge in content.get("edges", []):
            self._session.add(
                GraphEdge(
                    id=str(edge["id"]),
                    graph_id=graph.id,
                    source_id=edge["source_id"],
                    source_port=edge["source_port"],
                    target_id=edge["target_id"],
                    target_port=edge["target_port"],
                    style=edge.get("style") or "curved",
                    source_slot=edge.get("source_slot") or 0,
                    target_slot=edge.get("target_slot") or 0,
                )
            )
        await self._session.flush()
        outputs = await self._outputs(graph.id)
        has_fail = any(n.fail_enabled for n in outputs)
        if has_fail != had_fail and outputs:
            await self._sync_definition(outputs[0], report)
        uses = await self._session.scalars(
            select(GraphNode).where(
                GraphNode.graph_id == graph.id, GraphNode.kind == NodeKind.ACTION.value
            )
        )
        for use in list(uses):
            await self._sync_use(use, _mode(use), True, report)
        report.graphs.discard(graph.id)
        await self.touch(graph)
        await self._touch_ids(report.graphs)
        return report

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
        # the guards attached to it (and, for a stage, to its actions) go with it; their definitions stay
        watched = [
            node.id,
            *await self._session.scalars(select(GraphNode.id).where(GraphNode.stage_id == node.id)),
        ]
        await self._session.execute(
            delete(GuardAttachment).where(
                GuardAttachment.graph_id == graph.id, GuardAttachment.scope_id.in_(watched)
            )
        )
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
        for end, port in ((source, data.source_port), (target, data.target_port)):
            kind_type = node_type(end.kind)
            if kind_type.port_hidden(kind_type.effective_config(end.config), port):
                raise NodeError(_hidden_port_message(kind_type, end, port))
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


def _names(names: Sequence[str]) -> str:
    """Names for a sentence: 'A', 'A and B', 'A, B and C' (at most five, then the rest is counted)."""
    shown = [f"'{n}'" for n in names[:5]]
    if len(names) > 5:
        shown.append(f"{len(names) - 5} more")
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + f" and {shown[-1]}"


def _endpoint(node: GraphNode) -> Endpoint:
    return Endpoint(
        id=node.id, kind=NodeKind(node.kind), stage_id=node.stage_id, config=node.config
    )
