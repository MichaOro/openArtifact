"""Guards as stored (ADR-060): list, create, change, switch on and off, delete; the templates.

A guard belongs to a pipeline and watches the pipeline, one of its stages or one of its actions. Its own action (for
the consequence ``run_action``) is an ordinary action definition, edited in the action editor; a guard created with
``run_action`` and no action gets an empty one. Every change publishes ``guards.changed`` (``{"pipeline_id"}``).
A running execution keeps the guards it started with; switching one off acts on it at once (checked when it would
fire).
"""

from __future__ import annotations

import json
import uuid
from functools import cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.database import SessionOpener
from openartifact.engine.snapshot import guard_data
from openartifact.events import EventBus
from openartifact.exceptions import ArtifactError
from openartifact.graph.repository import GraphRepository, NodeError
from openartifact.graph.rules import EdgeError
from openartifact.graph.schemas import EdgeCreate, NodeCreate, NodeUpdate
from openartifact.guards.schemas import (
    GuardCreate,
    GuardRead,
    GuardWrite,
)
from openartifact.models import Graph, GraphKind, GraphNode, Guard, NodeKind

TEMPLATES = Path(__file__).parent / "templates"
MAX_GUARDS_PER_PIPELINE = 100


@cache
def templates() -> dict[str, dict[str, Any]]:
    """The guard templates shipped with the application (``guards/templates/*.json``), by key."""
    found = {}
    for path in sorted(TEMPLATES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        found[data["key"]] = data
    return found


def read(row: Guard) -> GuardRead:
    return GuardRead.model_validate(
        {**guard_data(row), "created_at": row.created_at, "updated_at": row.updated_at}
    )


class GuardService:
    """The guards of pipelines, for every way in (browser, ``/api/v1``, MCP)."""

    def __init__(self, session: SessionOpener, bus: EventBus, min_interval_seconds: float) -> None:
        self._session = session
        self._bus = bus
        self.min_interval_seconds = min_interval_seconds

    async def list(self, pipeline_id: str | None = None) -> list[GuardRead]:
        async with self._session() as session:
            query = select(Guard).order_by(Guard.name, Guard.id)
            if pipeline_id is not None:
                query = query.where(Guard.pipeline_id == pipeline_id)
            return [read(row) for row in await session.scalars(query)]

    async def get(self, guard_id: str) -> GuardRead:
        async with self._session() as session:
            return read(await self._row(session, guard_id))

    async def create(self, data: GuardCreate) -> GuardRead:
        async with self._session() as session:
            pipeline = await session.get(Graph, data.pipeline_id)
            if pipeline is None or pipeline.kind != GraphKind.PIPELINE:
                raise ArtifactError(404, "Pipeline not found")
            count = len(
                (
                    await session.scalars(select(Guard.id).where(Guard.pipeline_id == pipeline.id))
                ).all()
            )
            if count >= MAX_GUARDS_PER_PIPELINE:
                raise ArtifactError(422, f"A pipeline has at most {MAX_GUARDS_PER_PIPELINE} guards")
            row = Guard(id=str(uuid.uuid4()), pipeline_id=pipeline.id, name=data.name)
            self._apply(row, data)
            if row.scope_type == "pipeline":
                row.scope_id = pipeline.id
            await self._check(session, row)
            if row.consequence == "run_action" and row.definition_id is None:
                row.definition_id = (await self._new_action(session, f"{row.name} (guard)")).id
            session.add(row)
            await session.commit()
            result = read(row)
        self._changed(result.pipeline_id)
        return result

    async def update(self, guard_id: str, data: GuardWrite) -> GuardRead:
        async with self._session() as session:
            row = await self._row(session, guard_id)
            self._apply(row, data)
            if row.scope_type == "pipeline":
                row.scope_id = row.pipeline_id
            await self._check(session, row)
            if row.consequence == "run_action" and row.definition_id is None:
                row.definition_id = (await self._new_action(session, f"{row.name} (guard)")).id
            await session.commit()
            result = read(row)
        self._changed(result.pipeline_id)
        return result

    async def set_enabled(self, guard_id: str, enabled: bool) -> GuardRead:
        return await self.update(guard_id, GuardWrite(enabled=enabled))

    async def delete(self, guard_id: str) -> None:
        """Delete the guard (its own action stays: it is an action definition like any other)."""
        async with self._session() as session:
            row = await self._row(session, guard_id)
            pipeline_id = row.pipeline_id
            await session.delete(row)
            await session.commit()
        self._changed(pipeline_id)

    async def from_template(
        self,
        key: str,
        pipeline_id: str,
        scope_type: str,
        scope_id: str | None,
        name: str | None = None,
    ) -> GuardRead:
        """A guard made from a template, with its own action when the template has one."""
        template = templates().get(key)
        if template is None:
            raise ArtifactError(404, "Guard template not found")
        if scope_type not in template["scope_types"]:
            raise ArtifactError(
                422, f"The {template['name']} watches a {' or '.join(template['scope_types'])}"
            )
        definition_id = None
        if "action" in template:
            async with self._session() as session:
                definition_id = (await self._build_action(session, template["action"])).id
                await session.commit()
        data = GuardCreate.model_validate(
            {
                **template["guard"],
                "name": name or template["name"],
                "pipeline_id": pipeline_id,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "definition_id": definition_id,
            }
        )
        return await self.create(data)

    # ── checks ───────────────────────────────────────────────────────

    @staticmethod
    def _apply(row: Guard, data: GuardWrite) -> None:
        given = data.model_dump(exclude_unset=True)
        for key in (
            "name",
            "scope_type",
            "scope_id",
            "consequence",
            "fallback",
            "definition_id",
            "enabled",
        ):
            if key in given and (given[key] is not None or key in ("scope_id", "definition_id")):
                setattr(row, key, given[key])
        if data.trigger is not None:
            row.trigger = json.dumps(data.trigger.model_dump(mode="json"))
        if data.when is not None:
            row.condition = json.dumps(data.when.model_dump(mode="json"))
        if data.escalation is not None:
            row.escalation = json.dumps(
                [s.model_dump(mode="json", exclude_none=True) for s in data.escalation]
            )
        row.consequence = row.consequence or "pause"
        row.fallback = row.fallback or "pause"
        row.condition = row.condition or json.dumps({"type": "group", "mode": "all", "items": []})
        row.escalation = row.escalation or "[]"
        if row.enabled is None:
            row.enabled = True

    async def _check(self, session: AsyncSession, row: Guard) -> None:
        """422 unless the scope is a stage or an action of the guard's pipeline (or the pipeline), the interval is
        not shorter than the minimum, and the guard's own action is an action definition."""
        if row.scope_type in ("stage", "action"):
            node = await session.get(GraphNode, row.scope_id or "")
            if node is None or node.graph_id != row.pipeline_id or node.kind != row.scope_type:
                raise ArtifactError(422, f"The scope is not a {row.scope_type} of this pipeline")
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
        if row.definition_id is not None:
            graph = await session.get(Graph, row.definition_id)
            if graph is None or graph.kind != GraphKind.ACTION:
                raise ArtifactError(422, "The guard's action must be an action definition")

    @staticmethod
    async def _row(session: AsyncSession, guard_id: str) -> Guard:
        row = await session.get(Guard, guard_id)
        if row is None:
            raise ArtifactError(404, "Guard not found")
        return row

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

    def _changed(self, pipeline_id: str) -> None:
        self._bus.publish("guards.changed", {"pipeline_id": pipeline_id})
