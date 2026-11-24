"""Guards as stored (ADR-060): the library of guard definitions and their attachments; the templates.

A **definition** is what a guard is: its trigger, condition, escalation, consequence, fallback and its own action (for
``run_action``, an ordinary action definition edited in the action editor; a definition saved with ``run_action`` and
no action gets an empty one). It may be attached to the scope types it lists. An **attachment** puts a definition on a
pipeline, one of its stages or one of its actions, or on an action definition (the whole action, or one execution node
of it), and is switched on or off there; the graph that holds the scope is the attachment's ``graph_id``. A change to a definition acts on
every place it is attached to (at the next start: a running execution keeps what it froze); switching an attachment
off acts on running executions at once. A definition cannot be deleted while it is attached anywhere (409).
Every change publishes ``guards.changed`` (``{"guard_id"}`` and, for an attachment, ``{"graph_id"}``).
"""

from __future__ import annotations

import builtins
import json
import uuid
from collections import defaultdict
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.database import SessionOpener
from openartifact.engine.snapshot import definition_data
from openartifact.events import EventBus
from openartifact.exceptions import ArtifactError
from openartifact.graph.node_types import node_type
from openartifact.graph.repository import GraphRepository, NodeError
from openartifact.graph.rules import EdgeError
from openartifact.graph.schemas import EdgeCreate, NodeCreate, NodeUpdate
from openartifact.guards.schemas import (
    DEFINITION_SCOPES,
    PIPELINE_SCOPES,
    SCOPES,
    AttachmentCreate,
    AttachmentRead,
    GuardDefinitionCreate,
    GuardDefinitionRead,
    GuardDefinitionWrite,
)
from openartifact.models import (
    Graph,
    GraphKind,
    GraphNode,
    GuardAttachment,
    GuardDefinition,
    NodeKind,
)

TEMPLATES = Path(__file__).parent / "templates"
MAX_GUARDS_PER_PIPELINE = 100  # per graph that holds scopes
MAX_DEFINITIONS = 1000


@cache
def templates() -> dict[str, dict[str, Any]]:
    """The guard templates shipped with the application (``guards/templates/*.json``), by key."""
    found = {}
    for path in sorted(TEMPLATES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        found[data["key"]] = data
    return found


#: What names a graph or a node: ``(holder id) -> (name, kind)`` and ``(node id) -> name``.
Names = tuple[dict[str, tuple[str, str]], dict[str, str]]
NO_NAMES: Names = ({}, {})


def read_attachment(row: GuardAttachment, name: str, names: Names = NO_NAMES) -> AttachmentRead:
    graphs, nodes = names
    holder_name, holder_kind = graphs.get(row.graph_id, ("", "action"))
    if row.scope_type in ("pipeline", "definition"):
        scope_name = holder_name
    else:
        scope_name = nodes.get(row.scope_id, "")
    return AttachmentRead(
        id=row.id,
        guard_id=row.guard_id,
        name=name,
        graph_id=row.graph_id,
        pipeline_id=row.graph_id if row.scope_type in PIPELINE_SCOPES else None,
        holder_kind="pipeline" if row.scope_type in PIPELINE_SCOPES else holder_kind,
        holder_name=holder_name,
        scope_type=row.scope_type,
        scope_id=row.scope_id,
        scope_name=scope_name,
        enabled=row.enabled,
        created_at=row.created_at,
    )


async def names_of(session: AsyncSession, rows: Sequence[GuardAttachment]) -> Names:
    """The names of the graphs that hold the attachments and of the nodes they watch (two queries for any number)."""
    graph_ids = {r.graph_id for r in rows}
    node_ids = {r.scope_id for r in rows if r.scope_type not in ("pipeline", "definition")}
    graphs = (
        {
            g.id: (g.name, g.kind.value if hasattr(g.kind, "value") else str(g.kind))
            for g in await session.scalars(select(Graph).where(Graph.id.in_(graph_ids)))
        }
        if graph_ids
        else {}
    )
    nodes = (
        {
            n.id: n.name
            for n in await session.scalars(select(GraphNode).where(GraphNode.id.in_(node_ids)))
        }
        if node_ids
        else {}
    )
    return graphs, nodes


def read(
    row: GuardDefinition, attachments: Sequence[GuardAttachment], names: Names = NO_NAMES
) -> GuardDefinitionRead:
    return GuardDefinitionRead.model_validate(
        {
            **definition_data(row),
            "used_by": len(attachments),
            "attachments": [read_attachment(a, row.name, names) for a in attachments],
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )


class GuardService:
    """The guard library and its attachments, for every way in (browser, ``/api/v1``, MCP)."""

    def __init__(self, session: SessionOpener, bus: EventBus, min_interval_seconds: float) -> None:
        self._session = session
        self._bus = bus
        self.min_interval_seconds = min_interval_seconds

    # ── definitions ──────────────────────────────────────────────────

    async def holders(self, graph_id: str, *, inner: bool = False) -> builtins.list[str]:
        """The graphs whose attachments belong to ``graph_id``: itself and, with ``inner``, the action definitions its
        action nodes use (the guards that sit inside those actions, which the editor mirrors on the action's card)."""
        ids = [graph_id]
        if inner:
            async with self._session() as session:
                used = await session.scalars(
                    select(GraphNode.definition_id)
                    .where(
                        GraphNode.graph_id == graph_id,
                        GraphNode.kind == NodeKind.ACTION,
                        GraphNode.definition_id.is_not(None),
                    )
                    .distinct()
                )
                ids += [i for i in used if i]
        return ids

    async def list(
        self, pipeline_id: str | None = None, *, inner: bool = False
    ) -> builtins.list[GuardDefinitionRead]:
        """Every definition with its attachments; with ``pipeline_id`` (any graph that holds scopes) only the ones
        attached to that graph, with their attachments there; with ``inner`` also those attached inside the action
        definitions the graph's action nodes use."""
        holders = await self.holders(pipeline_id, inner=inner) if pipeline_id is not None else None
        async with self._session() as session:
            query = select(GuardAttachment).order_by(GuardAttachment.created_at, GuardAttachment.id)
            if holders is not None:
                query = query.where(GuardAttachment.graph_id.in_(holders))
            attachments = builtins.list(await session.scalars(query))
            names = await names_of(session, attachments)
            by_guard: dict[str, builtins.list[GuardAttachment]] = defaultdict(builtins.list)
            for attachment in attachments:
                by_guard[attachment.guard_id].append(attachment)
            rows = await session.scalars(
                select(GuardDefinition).order_by(GuardDefinition.name, GuardDefinition.id)
            )
            return [
                read(row, by_guard.get(row.id, []), names)
                for row in rows
                if holders is None or row.id in by_guard
            ]

    async def get(self, guard_id: str) -> GuardDefinitionRead:
        async with self._session() as session:
            row = await self._row(session, guard_id)
            attachments = await self._attachments_of(session, row.id)
            return read(row, attachments, await names_of(session, attachments))

    async def create(self, data: GuardDefinitionCreate) -> GuardDefinitionRead:
        async with self._session() as session:
            count = await session.scalar(select(func.count()).select_from(GuardDefinition))
            if (count or 0) >= MAX_DEFINITIONS:
                raise ArtifactError(422, f"The library holds at most {MAX_DEFINITIONS} guards")
            row = GuardDefinition(id=str(uuid.uuid4()), name=data.name)
            self._apply(row, data)
            await self._check(session, row, [])
            if row.consequence == "run_action" and row.action_id is None:
                row.action_id = (await self._new_action(session, f"{row.name} (guard)")).id
            session.add(row)
            await session.commit()
            result = read(row, [])
        self._changed(guard_id=result.id)
        return result

    async def update(self, guard_id: str, data: GuardDefinitionWrite) -> GuardDefinitionRead:
        async with self._session() as session:
            row = await self._row(session, guard_id)
            attachments = await self._attachments_of(session, row.id)
            self._apply(row, data)
            await self._check(session, row, attachments)
            if row.consequence == "run_action" and row.action_id is None:
                row.action_id = (await self._new_action(session, f"{row.name} (guard)")).id
            await session.commit()
            result = read(row, attachments, await names_of(session, attachments))
        self._changed(guard_id=result.id)
        return result

    async def delete(self, guard_id: str) -> None:
        """Delete a definition that is attached nowhere (its own action stays: an action definition like any
        other). 409 while it is attached: detach it first."""
        async with self._session() as session:
            row = await self._row(session, guard_id)
            used = len(await self._attachments_of(session, row.id))
            if used:
                raise ArtifactError(
                    409,
                    f"The guard {row.name!r} is attached in {used} place{'s' if used != 1 else ''}: "
                    "detach it first",
                )
            await session.delete(row)
            await session.commit()
        self._changed(guard_id=guard_id)

    async def from_template(
        self, key: str, name: str | None = None, description: str | None = None
    ) -> GuardDefinitionRead:
        """A definition made from a template, with its own action when the template has one."""
        template = templates().get(key)
        if template is None:
            raise ArtifactError(404, "Guard template not found")
        action_id = None
        if "action" in template:
            async with self._session() as session:
                action_id = (await self._build_action(session, template["action"])).id
                await session.commit()
        data = GuardDefinitionCreate.model_validate(
            {
                **template["guard"],
                "name": name or template["name"],
                "description": template["summary"] if description is None else description,
                "scope_types": template["scope_types"],
                "action_id": action_id,
            }
        )
        return await self.create(data)

    # ── attachments ──────────────────────────────────────────────────

    async def attachments(
        self, pipeline_id: str | None = None, *, inner: bool = False
    ) -> builtins.list[AttachmentRead]:
        """The attachments of a graph (a pipeline or an action definition; with ``inner`` also those inside the action
        definitions a pipeline uses), or every attachment."""
        holders = await self.holders(pipeline_id, inner=inner) if pipeline_id is not None else None
        async with self._session() as session:
            query = (
                select(GuardAttachment, GuardDefinition.name)
                .join(GuardDefinition, GuardDefinition.id == GuardAttachment.guard_id)
                .order_by(GuardDefinition.name, GuardAttachment.created_at, GuardAttachment.id)
            )
            if holders is not None:
                query = query.where(GuardAttachment.graph_id.in_(holders))
            found = (await session.execute(query)).all()
            names = await names_of(session, [row for row, _ in found])
            return [read_attachment(row, name, names) for row, name in found]

    async def attachments_of(self, guard_id: str) -> builtins.list[AttachmentRead]:
        """Where one definition is attached (404 for an unknown definition)."""
        async with self._session() as session:
            row = await self._row(session, guard_id)
            attached = await self._attachments_of(session, row.id)
            names = await names_of(session, attached)
            return [read_attachment(a, row.name, names) for a in attached]

    async def attachment(self, attachment_id: str) -> AttachmentRead:
        async with self._session() as session:
            row, name = await self._attachment(session, attachment_id)
            return read_attachment(row, name, await names_of(session, [row]))

    async def attach(self, data: AttachmentCreate) -> AttachmentRead:
        """Attach a definition to a scope: 404 for an unknown definition or graph; 422 when the definition may not
        watch that kind of scope, the graph cannot hold it (a pipeline holds ``pipeline``, ``stage`` and ``action``, an
        action definition ``definition`` and ``node``) or the scope is not part of the graph; 409 when it is attached
        there already."""
        async with self._session() as session:
            definition = await self._row(session, data.guard_id)
            holder = await session.get(Graph, data.holder)
            if holder is None or holder.kind not in (GraphKind.PIPELINE, GraphKind.ACTION):
                raise ArtifactError(404, "Pipeline or action definition not found")
            allowed = json.loads(definition.scope_types or "[]")
            if data.scope_type not in allowed:
                raise ArtifactError(
                    422,
                    f"The guard {definition.name!r} watches a {' or '.join(allowed)}, not a {data.scope_type}",
                )
            fits = PIPELINE_SCOPES if holder.kind == GraphKind.PIPELINE else DEFINITION_SCOPES
            if data.scope_type not in fits:
                raise ArtifactError(
                    422,
                    f"A {holder.kind.value if hasattr(holder.kind, 'value') else holder.kind} holds "
                    f"{' and '.join(fits)} scopes, not a {data.scope_type}",
                )
            scope_id = await self._scope_id(session, holder, data)
            count = await session.scalar(
                select(func.count())
                .select_from(GuardAttachment)
                .where(GuardAttachment.graph_id == holder.id)
            )
            if (count or 0) >= MAX_GUARDS_PER_PIPELINE:
                raise ArtifactError(422, f"A graph has at most {MAX_GUARDS_PER_PIPELINE} guards")
            same = await session.scalar(
                select(GuardAttachment.id).where(
                    GuardAttachment.guard_id == definition.id,
                    GuardAttachment.graph_id == holder.id,
                    GuardAttachment.scope_type == data.scope_type,
                    GuardAttachment.scope_id == scope_id,
                )
            )
            if same is not None:
                raise ArtifactError(409, f"The guard {definition.name!r} is attached there already")
            row = GuardAttachment(
                id=str(uuid.uuid4()),
                guard_id=definition.id,
                graph_id=holder.id,
                scope_type=data.scope_type,
                scope_id=scope_id,
                enabled=data.enabled,
            )
            session.add(row)
            await session.commit()
            result = read_attachment(row, definition.name, await names_of(session, [row]))
        self._changed(guard_id=result.guard_id, graph_id=result.graph_id)
        return result

    @staticmethod
    async def _scope_id(session: AsyncSession, holder: Graph, data: AttachmentCreate) -> str:
        """The id the attachment watches; 422 when it is not part of the holder."""
        if data.scope_type in ("pipeline", "definition"):
            return holder.id
        of = "pipeline" if holder.kind == GraphKind.PIPELINE else "action"
        node = await session.get(GraphNode, data.scope_id or "")
        if node is None or node.graph_id != holder.id:
            raise ArtifactError(422, f"The scope is not a {data.scope_type} of this {of}")
        if data.scope_type in ("stage", "action"):
            if node.kind != data.scope_type:
                raise ArtifactError(422, f"The scope is not a {data.scope_type} of this {of}")
        elif not node_type(NodeKind(node.kind)).guardable:
            raise ArtifactError(
                422, f"A guard cannot watch a {node.kind} node (it does not run as a step)"
            )
        return node.id

    async def set_enabled(self, attachment_id: str, enabled: bool) -> AttachmentRead:
        """Switch an attachment on or off: off acts on running executions at once, on at the next start."""
        async with self._session() as session:
            row, name = await self._attachment(session, attachment_id)
            row.enabled = enabled
            await session.commit()
            result = read_attachment(row, name, await names_of(session, [row]))
        self._changed(guard_id=result.guard_id, graph_id=result.graph_id)
        return result

    async def detach(self, attachment_id: str) -> None:
        """Take a definition off a scope (the definition stays in the library)."""
        async with self._session() as session:
            row, _name = await self._attachment(session, attachment_id)
            guard_id, graph_id = row.guard_id, row.graph_id
            await session.delete(row)
            await session.commit()
        self._changed(guard_id=guard_id, graph_id=graph_id)

    # ── checks ───────────────────────────────────────────────────────

    @staticmethod
    def _apply(row: GuardDefinition, data: GuardDefinitionWrite) -> None:
        given = data.model_dump(exclude_unset=True)
        for key in ("name", "description", "consequence", "fallback", "action_id"):
            if key in given and (given[key] is not None or key == "action_id"):
                setattr(row, key, given[key])
        if data.scope_types is not None:
            row.scope_types = json.dumps(data.scope_types)
        if data.trigger is not None:
            row.trigger = json.dumps(data.trigger.model_dump(mode="json"))
        if data.when is not None:
            row.condition = json.dumps(data.when.model_dump(mode="json"))
        if data.escalation is not None:
            row.escalation = json.dumps(
                [s.model_dump(mode="json", exclude_none=True) for s in data.escalation]
            )
        row.description = row.description or ""
        row.scope_types = row.scope_types or json.dumps(list(SCOPES))
        row.consequence = row.consequence or "pause"
        row.fallback = row.fallback or "pause"
        row.condition = row.condition or json.dumps({"type": "group", "mode": "all", "items": []})
        row.escalation = row.escalation or "[]"

    async def _check(
        self,
        session: AsyncSession,
        row: GuardDefinition,
        attachments: Sequence[GuardAttachment],
    ) -> None:
        """422 unless the interval is not shorter than the minimum, the guard's own action is an action definition
        and the scope types still cover every place it is attached to."""
        trigger = json.loads(row.trigger or "{}")
        every = trigger.get("every_seconds")
        if (
            trigger.get("type") == "interval"
            and every is not None
            and every < self.min_interval_seconds
        ):
            raise ArtifactError(
                422,
                f"An interval guard checks at most every {self.min_interval_seconds:g} s (the minimum interval)",
            )
        if row.action_id is not None:
            graph = await session.get(Graph, row.action_id)
            if graph is None or graph.kind != GraphKind.ACTION:
                raise ArtifactError(422, "The guard's action must be an action definition")
        allowed = set(json.loads(row.scope_types or "[]"))
        used = sorted({a.scope_type for a in attachments} - allowed)
        if used:
            raise ArtifactError(
                422, f"The guard is attached to a {' and a '.join(used)}: detach it there first"
            )

    @staticmethod
    async def _row(session: AsyncSession, guard_id: str) -> GuardDefinition:
        row = await session.get(GuardDefinition, guard_id)
        if row is None:
            raise ArtifactError(404, "Guard not found")
        return row

    @staticmethod
    async def _attachments_of(
        session: AsyncSession, guard_id: str
    ) -> builtins.list[GuardAttachment]:
        return list(
            await session.scalars(
                select(GuardAttachment)
                .where(GuardAttachment.guard_id == guard_id)
                .order_by(GuardAttachment.created_at, GuardAttachment.id)
            )
        )

    @staticmethod
    async def _attachment(session: AsyncSession, attachment_id: str) -> tuple[GuardAttachment, str]:
        found = (
            await session.execute(
                select(GuardAttachment, GuardDefinition.name)
                .join(GuardDefinition, GuardDefinition.id == GuardAttachment.guard_id)
                .where(GuardAttachment.id == attachment_id)
            )
        ).first()
        if found is None:
            raise ArtifactError(404, "Guard attachment not found")
        return found[0], found[1]

    @staticmethod
    async def _new_action(session: AsyncSession, name: str) -> Graph:
        return await GraphRepository(session).create(name[:255], GraphKind.ACTION)

    async def _build_action(self, session: AsyncSession, spec: dict[str, Any]) -> Graph:
        """An action definition from a template: its nodes, connected as the template says."""
        repo = GraphRepository(session)
        graph = await repo.create(spec["name"], GraphKind.ACTION)
        nodes, edges = await repo.graph(graph.id)
        for edge in edges:  # the default trigger -> output connection is replaced by the template's
            await repo.disconnect(edge)
        refs = {"trigger": next(n for n in nodes if n.kind == NodeKind.TRIGGER)}
        refs["output"] = next(n for n in nodes if n.kind == NodeKind.OUTPUT)
        try:
            if spec.get("fail_enabled"):
                await repo.update_node(refs["output"], NodeUpdate(fail_enabled=True))
            for node in spec["nodes"]:
                refs[node["ref"]] = await repo.add_node(
                    graph,
                    NodeCreate(
                        kind=NodeKind(node["kind"]),
                        name=node["name"],
                        x=node.get("x", 0),
                        y=node.get("y", 0),
                        config=node.get("config"),
                    ),
                )
            for source, source_port, target, target_port in spec["edges"]:
                await repo.connect(
                    graph,
                    EdgeCreate(
                        source_id=refs[source].id,
                        source_port=source_port,
                        target_id=refs[target].id,
                        target_port=target_port,
                    ),
                )
        except (
            NodeError,
            EdgeError,
            ValueError,
        ) as error:  # a template that does not fit the node kinds
            raise ArtifactError(422, f"The template's action cannot be built: {error}") from error
        return graph

    def _changed(self, *, guard_id: str, graph_id: str | None = None) -> None:
        data = {"guard_id": guard_id}
        if graph_id is not None:
            data["graph_id"] = graph_id
            data["pipeline_id"] = graph_id  # the editor's old name for it
        self._bus.publish("guards.changed", data)
