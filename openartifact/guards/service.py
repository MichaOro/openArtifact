"""Guards as stored (ADR-060): the library of guard definitions and their attachments; the templates.

A **definition** is what a guard is: its trigger, condition, escalation, consequence, fallback and its own action (for
``run_action``, an ordinary action definition edited in the action editor; a definition saved with ``run_action`` and
no action gets an empty one). It may be attached to the scope types it lists. An **attachment** puts a definition on a
pipeline, one of its stages or one of its actions and is switched on or off there. A change to a definition acts on
every place it is attached to (at the next start: a running execution keeps what it froze); switching an attachment
off acts on running executions at once. A definition cannot be deleted while it is attached anywhere (409).
Every change publishes ``guards.changed`` (``{"guard_id"}`` and, for an attachment, ``{"pipeline_id"}``).
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
from openartifact.graph.repository import GraphRepository, NodeError
from openartifact.graph.rules import EdgeError
from openartifact.graph.schemas import EdgeCreate, NodeCreate, NodeUpdate
from openartifact.guards.schemas import (
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
MAX_GUARDS_PER_PIPELINE = 100
MAX_DEFINITIONS = 1000


@cache
def templates() -> dict[str, dict[str, Any]]:
    """The guard templates shipped with the application (``guards/templates/*.json``), by key."""
    found = {}
    for path in sorted(TEMPLATES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        found[data["key"]] = data
    return found


def read_attachment(row: GuardAttachment, name: str) -> AttachmentRead:
    return AttachmentRead(
        id=row.id,
        guard_id=row.guard_id,
        name=name,
        pipeline_id=row.pipeline_id,
        scope_type=row.scope_type,
        scope_id=row.scope_id,
        enabled=row.enabled,
        created_at=row.created_at,
    )


def read(row: GuardDefinition, attachments: Sequence[GuardAttachment]) -> GuardDefinitionRead:
    return GuardDefinitionRead.model_validate(
        {
            **definition_data(row),
            "used_by": len(attachments),
            "attachments": [read_attachment(a, row.name) for a in attachments],
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

    async def list(self, pipeline_id: str | None = None) -> list[GuardDefinitionRead]:
        """Every definition with its attachments; with ``pipeline_id`` only the ones attached to that pipeline, with
        their attachments there."""
        async with self._session() as session:
            query = select(GuardAttachment).order_by(GuardAttachment.created_at, GuardAttachment.id)
            if pipeline_id is not None:
                query = query.where(GuardAttachment.pipeline_id == pipeline_id)
            by_guard: dict[str, list[GuardAttachment]] = defaultdict(list)
            for attachment in await session.scalars(query):
                by_guard[attachment.guard_id].append(attachment)
            rows = await session.scalars(
                select(GuardDefinition).order_by(GuardDefinition.name, GuardDefinition.id)
            )
            return [
                read(row, by_guard.get(row.id, []))
                for row in rows
                if pipeline_id is None or row.id in by_guard
            ]

    async def get(self, guard_id: str) -> GuardDefinitionRead:
        async with self._session() as session:
            row = await self._row(session, guard_id)
            return read(row, await self._attachments_of(session, row.id))

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
            result = read(row, attachments)
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

    async def attachments(self, pipeline_id: str | None = None) -> builtins.list[AttachmentRead]:
        async with self._session() as session:
            query = (
                select(GuardAttachment, GuardDefinition.name)
                .join(GuardDefinition, GuardDefinition.id == GuardAttachment.guard_id)
                .order_by(GuardDefinition.name, GuardAttachment.id)
            )
            if pipeline_id is not None:
                query = query.where(GuardAttachment.pipeline_id == pipeline_id)
            return [
                read_attachment(row, name) for row, name in (await session.execute(query)).all()
            ]

    async def attachments_of(self, guard_id: str) -> builtins.list[AttachmentRead]:
        """Where one definition is attached (404 for an unknown definition)."""
        async with self._session() as session:
            row = await self._row(session, guard_id)
            return [
                read_attachment(a, row.name) for a in await self._attachments_of(session, row.id)
            ]

    async def attachment(self, attachment_id: str) -> AttachmentRead:
        async with self._session() as session:
            row, name = await self._attachment(session, attachment_id)
            return read_attachment(row, name)

    async def attach(self, data: AttachmentCreate) -> AttachmentRead:
        """Attach a definition to a scope: 404 for an unknown definition or pipeline; 422 when the definition may not
        watch that kind of scope or the scope is not part of the pipeline; 409 when it is attached there already."""
        async with self._session() as session:
            definition = await self._row(session, data.guard_id)
            pipeline = await session.get(Graph, data.pipeline_id)
            if pipeline is None or pipeline.kind != GraphKind.PIPELINE:
                raise ArtifactError(404, "Pipeline not found")
            allowed = json.loads(definition.scope_types or "[]")
            if data.scope_type not in allowed:
                raise ArtifactError(
                    422,
                    f"The guard {definition.name!r} watches a {' or '.join(allowed)}, not a {data.scope_type}",
                )
            scope_id = pipeline.id if data.scope_type == "pipeline" else data.scope_id
            if data.scope_type != "pipeline":
                node = await session.get(GraphNode, scope_id or "")
                if node is None or node.graph_id != pipeline.id or node.kind != data.scope_type:
                    raise ArtifactError(
                        422, f"The scope is not a {data.scope_type} of this pipeline"
                    )
            assert scope_id is not None
            placed = await session.scalars(
                select(GuardAttachment.guard_id).where(GuardAttachment.pipeline_id == pipeline.id)
            )
            placed_ids = list(placed)
            if len(placed_ids) >= MAX_GUARDS_PER_PIPELINE:
                raise ArtifactError(422, f"A pipeline has at most {MAX_GUARDS_PER_PIPELINE} guards")
            same = await session.scalar(
                select(GuardAttachment.id).where(
                    GuardAttachment.guard_id == definition.id,
                    GuardAttachment.pipeline_id == pipeline.id,
                    GuardAttachment.scope_type == data.scope_type,
                    GuardAttachment.scope_id == scope_id,
                )
            )
            if same is not None:
                raise ArtifactError(409, f"The guard {definition.name!r} is attached there already")
            row = GuardAttachment(
                id=str(uuid.uuid4()),
                guard_id=definition.id,
                pipeline_id=pipeline.id,
                scope_type=data.scope_type,
                scope_id=scope_id,
                enabled=data.enabled,
            )
            session.add(row)
            await session.commit()
            result = read_attachment(row, definition.name)
        self._changed(guard_id=result.guard_id, pipeline_id=result.pipeline_id)
        return result

    async def set_enabled(self, attachment_id: str, enabled: bool) -> AttachmentRead:
        """Switch an attachment on or off: off acts on running executions at once, on at the next start."""
        async with self._session() as session:
            row, name = await self._attachment(session, attachment_id)
            row.enabled = enabled
            await session.commit()
            result = read_attachment(row, name)
        self._changed(guard_id=result.guard_id, pipeline_id=result.pipeline_id)
        return result

    async def detach(self, attachment_id: str) -> None:
        """Take a definition off a scope (the definition stays in the library)."""
        async with self._session() as session:
            row, _name = await self._attachment(session, attachment_id)
            guard_id, pipeline_id = row.guard_id, row.pipeline_id
            await session.delete(row)
            await session.commit()
        self._changed(guard_id=guard_id, pipeline_id=pipeline_id)

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
        row.scope_types = row.scope_types or json.dumps(["pipeline", "stage", "action"])
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

    def _changed(self, *, guard_id: str, pipeline_id: str | None = None) -> None:
        data = {"guard_id": guard_id}
        if pipeline_id is not None:
            data["pipeline_id"] = pipeline_id
        self._bus.publish("guards.changed", data)
