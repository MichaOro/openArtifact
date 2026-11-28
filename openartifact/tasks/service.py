"""What can be done with artifacts, once, for every way in.

The browser's REST API, the integration API (``/api/v1``), the MCP server and, later, actions all call
this class, so the rules (validation, the lock while an artifact is processed, events, where a new
artifact came from) exist in one place. Every method opens its own session and commits.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from openartifact import personal_settings
from openartifact.activity.recorder import SYSTEM, record, short
from openartifact.activity.schemas import ActivityRead
from openartifact.artifact_fields import rules as field_rules
from openartifact.artifact_fields.body import (
    PREVIEW_WORDS,
    has_references,
    marked_or_none,
    preview_or_none,
    resolved_or_none,
    unknown_references,
)
from openartifact.artifact_fields.service import (
    body_card,
    field_specs,
    values_of_new,
    values_of_update,
)
from openartifact.comments.schemas import Author
from openartifact.database import SessionOpener
from openartifact.engine import history as history_module
from openartifact.engine import history_query, stop_switch
from openartifact.engine.chain import pipeline_chain
from openartifact.engine.flow import build_flow
from openartifact.engine.flow_schemas import ExecutionFlow
from openartifact.engine.history import Changes, labels_of
from openartifact.engine.neighbour_schemas import ExecutionPosition, GraphNeighbours
from openartifact.engine.neighbours import graph_neighbours, position_of
from openartifact.engine.runner import RunEngine
from openartifact.engine.schemas import (
    ExecutionDetail,
    ExecutionList,
    ExecutionRead,
    ExecutionsPage,
    ExecutionStepRead,
    NodeResultRead,
    RunContextRead,
    RunRead,
)
from openartifact.engine.targets import TargetError, resolve_target
from openartifact.events import EventBus
from openartifact.exceptions import ArtifactError
from openartifact.graph.publishing import graph_for_run
from openartifact.graph.repository import GraphRepository
from openartifact.models import (
    ArtifactField,
    CreatedBy,
    Execution,
    Graph,
    GraphKind,
    GuardAttachment,
    PipelineRun,
    RunNodeResult,
    RunStatus,
    StartedBy,
    Task,
)
from openartifact.tasks import card_rules, card_sweeper, technical
from openartifact.tasks import lanes as lane_rules
from openartifact.tasks.card_rules import Rule
from openartifact.tasks.repository import ParentError, PlacementError, TaskRepository
from openartifact.tasks.schemas import LaneRead, TaskCreate, TaskRead, TaskUpdate

LANE_GONE = "The lane no longer exists."
LOCKED_FIELDS = {
    "status",
    "before_id",
    "parent_id",
    "pipeline_id",
    "stage_id",
    "action_id",
    "fields",
}


#: The fields of a task that say where it starts.
TARGET_FIELDS = {"pipeline_id", "stage_id", "action_id"}


def _target_of(task: Task) -> tuple[str | None, str | None, str | None]:
    return task.pipeline_id, task.stage_id, task.action_id


def _snapshot_of(task: Task) -> dict[str, Any]:
    """What the activity compares an artifact with after an update."""
    return {
        "title": task.title,
        "body": task.body,
        "status": task.status,
        "parent_id": task.parent_id,
        "target": _target_of(task),
        "fields": json.loads(task.field_values or "{}"),
    }


def requested_target(task: Task, payload: TaskUpdate) -> tuple[str | None, str | None, str | None]:
    """The (pipeline, stage, action) a task update asks for, to be completed by ``resolve_target``.

    A field that is sent wins. A field that is not sent keeps the task's value, except that a new
    pipeline resets the stage and the action, and a new stage resets the action.
    """
    sent = payload.model_fields_set
    pipeline = payload.pipeline_id if "pipeline_id" in sent else task.pipeline_id
    same_pipeline = pipeline == task.pipeline_id
    stage = payload.stage_id if "stage_id" in sent else (task.stage_id if same_pipeline else None)
    if "action_id" in sent:
        action = payload.action_id
    else:
        action = task.action_id if same_pipeline and "stage_id" not in sent else None
    return pipeline, stage, action


class ArtifactService:
    """Create, read, change, delete and process artifacts."""

    def __init__(
        self,
        session: SessionOpener,
        bus: EventBus,
        engine: RunEngine,
    ) -> None:
        self._session = session
        self._bus = bus
        self._engine = engine

    # ── reading ───────────────────────────────────────────────────────

    async def list_all(
        self,
        archived: str = "exclude",
        sort: str | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        parent: str | None = None,
    ) -> list[TaskRead]:
        """The artifacts, each with its ``marks`` (card rules, ADR-071); a body with references also carries ``preview``.

        ``archived``: ``exclude`` (the board: default), ``only`` (the archive) or ``include`` (both). Board order unless ``sort`` is
        ``archived_at`` (default of the archive, newest first) or ``title`` (``order`` ``asc`` or ``desc``); ``limit`` and ``offset`` page.
        ``parent`` (an id or a number) keeps only the direct children of that card.
        """
        async with self._session() as session:
            parent_id = await self._parent_filter(session, parent)
            tasks = [
                t
                for t in await TaskRepository(session).list_all()
                if (archived == "include" or (t.archived_at is not None) == (archived == "only"))
                and (parent_id is None or t.parent_id == parent_id)
            ]
            if sort is None and archived == "only":
                sort = "archived_at"
            if sort == "archived_at":
                tasks.sort(
                    key=lambda t: (t.archived_at is None, t.archived_at or datetime.min),
                    reverse=(order or "desc") == "desc",
                )
            elif sort == "title":
                tasks.sort(key=lambda t: t.title.lower(), reverse=order == "desc")
            if limit is not None:
                tasks = tasks[offset : offset + limit]
            elif offset:
                tasks = tasks[offset:]
            card_marks = await card_rules.marks_for(session, tasks)
            titles = await self._lane_titles(session)
            named = await self._lane_names(session)
            refs = any(has_references(t.body) for t in tasks)
            specs = await field_specs(session) if refs else []
            marks = refs and await personal_settings.marks_resolved_references(session)
            reads = [self._read(t, specs, preview=True, marks=marks) for t in tasks]
            archived_children = await self._archived_children(session, {t.id for t in tasks})
            for read in reads:
                read.marks = card_marks.get(read.id)
                read.archived_from_lane = titles.get(read.archived_from_status or "")
                read.lane_id, read.lane_name = named.get(read.status, (None, None))
                read.archived_children = archived_children.get(read.id, 0)
            return reads

    @staticmethod
    async def _parent_filter(session: AsyncSession, parent: str | None) -> str | None:
        """The id a ``parent`` filter (an id or a number, ``#`` allowed) stands for; an id that names no card matches no card."""
        if parent is None or parent == "":
            return None
        number = parent.lstrip("#")
        if number.isdigit():
            found = await session.scalar(select(Task.id).where(Task.number == int(number)))
            return found or ""
        return parent

    @staticmethod
    async def _archived_children(session: AsyncSession, ids: set[str]) -> dict[str, int]:
        """How many archived cards each of ``ids`` has as direct children (an archived card keeps its parent link, ADR-071)."""
        if not ids:
            return {}
        counts: dict[str, int] = {}
        for start in range(
            0, len(ids), 500
        ):  # chunked: SQLite limits the variables of one statement
            chunk = list(ids)[start : start + 500]
            rows = await session.execute(
                select(Task.parent_id, func.count())
                .where(
                    Task.parent_id.in_(chunk),
                    Task.archived_at.is_not(None),
                    Task.technical.is_(False),
                )
                .group_by(Task.parent_id)
            )
            counts.update({pid: n for pid, n in rows if pid})
        return counts

    async def processing_ids(self) -> set[str]:
        """The ids of the cards that are being processed now (a run of theirs is running)."""
        async with self._session() as session:
            rows = await session.scalars(
                select(PipelineRun.task_id).where(PipelineRun.status == RunStatus.RUNNING)
            )
            return set(rows)

    async def count_cards(self, archived: str, parent: str | None = None) -> int:
        """How many cards a list with this ``archived`` value (and ``parent`` filter) holds in all (before paging)."""
        async with self._session() as session:
            query = select(func.count()).select_from(Task).where(Task.technical.is_(False))
            parent_id = await self._parent_filter(session, parent)
            if parent_id is not None:
                query = query.where(Task.parent_id == parent_id)
            if archived == "only":
                query = query.where(Task.archived_at.is_not(None))
            elif archived == "exclude":
                query = query.where(Task.archived_at.is_(None))
            return await session.scalar(query) or 0

    async def get(self, ref: str) -> TaskRead:
        """One artifact by id, or by its number (``12`` or ``#12``); ``body_resolved`` has the references filled in."""
        async with self._session() as session:
            task = await self._task(session, ref)
            specs = await field_specs(session) if has_references(task.body) else []
            marks = has_references(task.body) and await personal_settings.marks_resolved_references(
                session
            )
            read = self._read(task, specs, resolved=True, marks=marks)
            read.marks = (await card_rules.marks_for(session, [task])).get(task.id)
            read.archived_from_lane = (await self._lane_titles(session)).get(
                task.archived_from_status or ""
            )
            read.lane_id, read.lane_name = (await self._lane_names(session)).get(
                task.status, (None, None)
            )
            read.archived_children = (await self._archived_children(session, {task.id})).get(
                task.id, 0
            )
            return read

    @staticmethod
    def forbid_archived(task: Task) -> None:
        """An archived card can only be read (and taken out of the archive): 409 ``archived`` (ADR-071)."""
        if task.archived_at is not None:
            raise ArtifactError(409, "archived")

    @staticmethod
    def _read(
        task: Task,
        specs: list[field_rules.FieldSpec],
        *,
        resolved: bool = False,
        preview: bool = False,
        marks: bool = False,
    ) -> TaskRead:
        """The artifact as read, with what a body's ``${card.x}`` stand for filled in where it is asked for; with
        ``marks`` (the personal setting *Mark resolved references*) also as segments that tell filled in text from written."""
        read = TaskRead.model_validate(task)
        if has_references(task.body) and (resolved or preview):
            card = body_card(specs, task)
            if resolved:
                read.body_resolved = resolved_or_none(task.body, card)
                if marks:
                    read.body_resolved_segments = marked_or_none(task.body, card)
            if preview:
                read.preview = preview_or_none(task.body, card)
                if marks:
                    read.preview_segments = marked_or_none(task.body, card, PREVIEW_WORDS)
        return read

    async def _read_after_save(self, session: AsyncSession, task: Task) -> TaskRead:
        """The artifact after a create or an update: resolved body and preview for the open dialog and the board
        (they travel in the event), and the calm note about a reference that names nothing (never a refusal)."""
        specs = await field_specs(session) if has_references(task.body) else []
        marks = has_references(task.body) and await personal_settings.marks_resolved_references(
            session
        )
        read = self._read(task, specs, resolved=True, preview=True, marks=marks)
        read.marks = (await card_rules.marks_for(session, [task])).get(task.id)
        read.archived_from_lane = (await self._lane_titles(session)).get(
            task.archived_from_status or ""
        )
        read.lane_id, read.lane_name = (await self._lane_names(session)).get(
            task.status, (None, None)
        )
        read.archived_children = (await self._archived_children(session, {task.id})).get(task.id, 0)
        if has_references(task.body):
            read.warnings = unknown_references(task.body, set(body_card(specs, task)))
        return read

    async def lanes(self) -> list[LaneRead]:
        """The board lanes in order."""
        async with self._session() as session:
            return await lane_rules.effective_lanes(session)

    async def lane(self, value: str) -> LaneRead:
        """The lane a name, an id or an old key stands for (ADR-090); 422 with the names of the lanes when it is none."""
        async with self._session() as session:
            try:
                key = await lane_rules.require_lane(session, value)
            except lane_rules.LaneError as error:
                raise ArtifactError(error.code, error.message) from error
            return next(x for x in await lane_rules.effective_lanes(session) if x.status == key)

    async def create_lane(self, title: str) -> list[LaneRead]:
        """Append a lane; publishes ``board.lanes``."""
        return await self._change_lanes(lambda session: lane_rules.create_lane(session, title))

    async def update_lane(
        self, status: str, title: str | None = None, style: str | None = None
    ) -> list[LaneRead]:
        """Change a lane's title and/or style; publishes ``board.lanes``."""

        async def change(session: AsyncSession) -> list[LaneRead]:
            try:
                key = (
                    await lane_rules.resolve_lane(session, status)
                ).key  # before a rename in this very call changes the name
            except lane_rules.LaneError:
                key = status  # update_lane below answers the 404
            lanes = await lane_rules.update_lane(
                session, status, title, style
            )  # resolved once more inside: the value as given
            if (
                style is not None
            ):  # the old switch is the rule *Set card as done* without a condition (ADR-071)
                await card_rules.set_lane_finished(session, key, style == "finished")
                await session.commit()
            return lanes

        return await self._change_lanes(change)

    async def reorder_lanes(self, values: list[str]) -> list[LaneRead]:
        """Put the lanes in a new order (each named once); publishes ``board.lanes``."""
        return await self._change_lanes(lambda session: lane_rules.reorder_lanes(session, values))

    async def delete_lane(self, status: str) -> list[LaneRead]:
        """Delete a lane that holds no artifacts; publishes ``board.lanes``."""
        return await self._change_lanes(lambda session: lane_rules.delete_lane(session, status))

    async def _change_lanes(
        self, change: Callable[[AsyncSession], Awaitable[list[LaneRead]]]
    ) -> list[LaneRead]:
        async with self._session() as session:
            try:
                lanes = await change(session)
            except lane_rules.LaneError as error:
                raise ArtifactError(error.code, error.message) from error
        self._bus.publish(
            "board.lanes", {"lanes": [lane.model_dump(mode="json") for lane in lanes]}
        )
        return lanes

    async def pipelines(self) -> list[dict[str, Any]]:
        """The pipelines with their stages in running order and the actions of every stage."""
        async with self._session() as session:
            result = []
            pipelines = (
                (
                    await session.execute(
                        select(Graph).where(Graph.kind == GraphKind.PIPELINE).order_by(Graph.name)
                    )
                )
                .scalars()
                .all()
            )
            for pipeline in pipelines:
                graph = await graph_for_run(
                    session, pipeline.id
                )  # the stages and actions a run would start in (ADR-070)
                result.append(
                    {
                        "id": pipeline.id,
                        "name": pipeline.name,
                        "slug": pipeline.slug,
                        "stages": pipeline_chain(graph["nodes"], graph["edges"]),
                    }
                )
            return result

    async def run(self, ref: str) -> RunRead | None:
        """The state of the artifact's processing, or ``None`` if it never ran."""
        async with self._session() as session:
            task = await self._task(session, ref)
            run = await session.scalar(select(PipelineRun).where(PipelineRun.task_id == task.id))
            return None if run is None else await self._engine.read(session, run)

    async def run_results(self, ref: str) -> list[NodeResultRead] | None:
        """Every step of the artifact's run inside action definitions, or ``None`` if it never ran."""
        async with self._session() as session:
            task = await self._task(session, ref)
            run = await session.scalar(select(PipelineRun).where(PipelineRun.task_id == task.id))
            if run is None:
                return None
            return (await self._engine.node_results(session, run.execution_id))[0]

    # ── execution history ─────────────────────────────────────────────

    async def executions(self, ref: str, limit: int = 100) -> ExecutionList:
        """The newest ``limit`` executions of the artifact (newest first), their total."""
        async with self._session() as session:
            task = await self._task(session, ref)
            rows = (
                (
                    await session.execute(
                        select(Execution)
                        .where(Execution.task_id == task.id)
                        .order_by(Execution.number.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            total = await session.scalar(
                select(func.count()).select_from(Execution).where(Execution.task_id == task.id)
            )
            return ExecutionList(
                items=[ExecutionRead.of(r) for r in rows],
                total=total or 0,
            )

    async def all_executions(
        self,
        *,
        status: str | None = None,
        started_by: str | None = None,
        pipeline: str | None = None,
        q: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = history_query.DEFAULT_LIMIT,
        cursor: str | None = None,
        dry_run: str | None = None,
        observed: str | None = None,
    ) -> ExecutionsPage:
        """The executions of all artifacts, newest first, one page (see ``engine/history_query.py``)."""
        flt = history_query.ExecutionFilter.parse(
            status=status,
            started_by=started_by,
            pipeline=pipeline,
            q=q,
            since=since,
            until=until,
            dry_run=dry_run,
            observed=observed,
        )
        async with self._session() as session:
            return await history_query.list_executions(
                session, flt, limit=limit, cursor=cursor, now=history_module.utcnow()
            )

    @staticmethod
    def _named(steps: list[NodeResultRead], snapshot_json: str) -> list[ExecutionStepRead]:
        """The steps with the names of their stage and action, as far as the snapshot knows them."""
        try:
            labels = labels_of(json.loads(snapshot_json))
        except (ValueError, KeyError):
            labels = {}
        return [
            ExecutionStepRead(
                **step.model_dump(),
                stage_name=labels.get(step.stage_id or ""),
                action_name=labels.get(step.action_id or ""),
            )
            for step in steps
        ]

    async def execution(self, ref: str, execution_id: str) -> ExecutionDetail:
        """One execution with all its steps (names of stage and action filled in from its snapshot)."""
        async with self._session() as session:
            task = await self._task(session, ref)
            row = await self._execution(
                session, task.id, execution_id, with_snapshot=True, with_context=True
            )
            steps, _ = await self._engine.node_results(session, row.id)
            return ExecutionDetail(
                **ExecutionRead.of(row).model_dump(),
                steps=self._named(steps, row.snapshot),
                context=RunContextRead.of(row.context),
            )

    async def execution_context(self, ref: str, execution_id: str) -> RunContextRead:
        """The run context of one execution (variables and the latest result of each node)."""
        async with self._session() as session:
            task = await self._task(session, ref)
            row = await self._execution(session, task.id, execution_id, with_context=True)
            return RunContextRead.of(row.context)

    async def execution_flow(self, ref: str, execution_id: str, outputs: bool) -> ExecutionFlow:
        """The frozen graphs of an execution, its steps (outputs only if asked for) and the path it took."""
        async with self._session() as session:
            task = await self._task(session, ref)
            row = await self._execution(session, task.id, execution_id, with_snapshot=True)
            steps, _ = await self._engine.node_results(session, row.id)
            guard_state = await session.scalar(
                select(Execution.guard_state).where(Execution.id == row.id)
            )
            return build_flow(
                ExecutionRead.of(row),
                row.snapshot,
                self._named(steps, row.snapshot),
                outputs,
                (row.started_stage_id, row.started_action_id),
                guard_state,
                await self._attachments_enabled(session, row.snapshot),
            )

    async def execution_position(self, ref: str, execution_id: str) -> ExecutionPosition:
        """Where an execution is, from its frozen graphs: the place, what leaves it and the path walked (the flow's data, ADR-069 add. 2)."""
        return position_of(await self.execution_flow(ref, execution_id, False))

    async def graph_neighbours(
        self, kind: GraphKind, ref: str, version: str = "published"
    ) -> GraphNeighbours:
        """The neighbours of a pipeline or an action definition given by id, URL name or name; 404 when there is none (or that version)."""
        async with self._session() as session:
            wanted = ref.strip().lower()
            graph = next(
                (
                    g
                    for g in await GraphRepository(session).list_all(kind)
                    if wanted in (g.id.lower(), (g.slug or "").lower(), g.name.lower())
                ),
                None,
            )
            if graph is None:
                raise ArtifactError(404, f"{kind.value.capitalize()} not found")
            try:
                found = await graph_neighbours(session, graph, version)
            except ValueError as error:
                raise ArtifactError(422, str(error)) from error
            if found is None:
                raise ArtifactError(404, f"Version {version} not found")
            return found

    @staticmethod
    async def _attachments_enabled(session: AsyncSession, snapshot_json: str) -> dict[str, bool]:
        """Whether each guard attachment of a frozen run is switched on now (the engine checks that live), by attachment id."""
        try:
            ids = [g["id"] for g in json.loads(snapshot_json).get("guards", []) if g.get("id")]
        except (ValueError, AttributeError, TypeError):
            return {}
        if not ids:
            return {}
        rows = await session.execute(
            select(GuardAttachment.id, GuardAttachment.enabled).where(GuardAttachment.id.in_(ids))
        )
        return {i: bool(e) for i, e in rows.all()}

    async def execution_step(self, ref: str, execution_id: str, step_id: str) -> ExecutionStepRead:
        """One step of the execution with its complete output; 404 if it is not a step of this execution."""
        async with self._session() as session:
            task = await self._task(session, ref)
            row = await self._execution(session, task.id, execution_id, with_snapshot=True)
            step = await session.scalar(
                select(RunNodeResult)
                .where(RunNodeResult.id == step_id, RunNodeResult.execution_id == row.id)
                .options(undefer(RunNodeResult.detail))
            )
            if step is None:
                raise ArtifactError(404, "Step not found")
            return self._named([NodeResultRead.of(step, detail=step.detail)], row.snapshot)[0]

    async def delete_execution(self, ref: str, execution_id: str, actor: Author = SYSTEM) -> None:
        """Delete one execution with its steps (409 while it runs)."""
        async with self._session() as session:
            task = await self._task(session, ref)
            row = await self._execution(session, task.id, execution_id)
            if row.status == RunStatus.RUNNING:
                raise ArtifactError(409, "The execution is running; stop it first")
            changes = Changes()
            await self._engine.history.remove(session, task.id, [row.id], changes, actor)
            await session.commit()
        self._engine.history.publish(changes)

    async def delete_executions(self, ids: list[str], actor: Author = SYSTEM) -> tuple[int, int]:
        """Delete the finished ones among these executions, whatever artifact they belong to; returns
        ``(deleted, skipped_running)``. An unknown id is already gone; a running execution is never touched."""
        wanted = list(dict.fromkeys(ids))
        async with self._session() as session:
            rows = (
                await session.execute(
                    select(Execution.id, Execution.task_id, Execution.status).where(
                        Execution.id.in_(wanted)
                    )
                )
            ).all()
            skipped = sum(1 for row in rows if row.status == RunStatus.RUNNING)
            by_task: dict[str, list[str]] = {}
            for row in rows:
                if row.status != RunStatus.RUNNING:
                    by_task.setdefault(row.task_id, []).append(row.id)
            changes = Changes()
            for task_id, execution_ids in by_task.items():
                await self._engine.history.remove(session, task_id, execution_ids, changes, actor)
            await session.commit()
        self._engine.history.publish(changes)
        return sum(len(v) for v in by_task.values()), skipped

    async def clear_executions(self, ref: str, actor: Author = SYSTEM) -> int:
        """Delete every finished execution of the artifact (the running one stays); returns how many."""
        async with self._session() as session:
            task = await self._task(session, ref)
            ids = list(
                (
                    await session.scalars(
                        select(Execution.id).where(
                            Execution.task_id == task.id, Execution.status != RunStatus.RUNNING
                        )
                    )
                ).all()
            )
            changes = Changes()
            await self._engine.history.remove(session, task.id, ids, changes, actor)
            await session.commit()
        self._engine.history.publish(changes)
        return len(ids)

    # ── changing ──────────────────────────────────────────────────────

    async def create(
        self, data: TaskCreate, created_by: CreatedBy = CreatedBy.USER, actor: Author = SYSTEM
    ) -> TaskRead:
        """Create an artifact: lane, optional parent, optional pipeline with its first stage and action.

        ``actor`` is who asked (it goes into the activity, ADR-058).
        """
        recorded: list[ActivityRead] = []
        async with self._session() as session:
            try:
                status = (
                    await lane_rules.first_lane(session)
                    if data.status is None
                    else await lane_rules.require_lane(session, data.status)
                )
                target = await resolve_target(
                    session, data.pipeline_id, data.stage_id, data.action_id
                )
                task = await TaskRepository(session).create(
                    data, status=status, created_by=created_by, target=target
                )
                task.field_values = await values_of_new(session, data.fields)
                lanes = await self._lane_titles(session)
                recorded.append(
                    await record(
                        session, task.id, "created", actor, {"lane": lanes.get(task.status)}
                    )
                )
                await session.commit()
            except lane_rules.LaneError as error:
                raise ArtifactError(error.code, error.message) from error
            except (TargetError, ParentError) as error:
                raise ArtifactError(422, str(error)) from error
            except IntegrityError as error:  # the lane was deleted in the meantime
                raise ArtifactError(409, LANE_GONE) from error
            created = await self._read_after_save(session, task)
        self._bus.publish("task.created", created.model_dump(mode="json", exclude={"warnings"}))
        self._publish_activity(recorded)
        return created

    async def update(self, ref: str, payload: TaskUpdate, actor: Author = SYSTEM) -> TaskRead:
        """Edit, move, reorder or re-target an artifact (lane, order, parent and target are locked while it runs).

        Every real change is recorded in the artifact's activity under ``actor`` (ADR-058).
        """
        recorded: list[ActivityRead] = []
        async with self._session() as session:
            repo = TaskRepository(session)
            task = await self._task(session, ref)
            self.forbid_archived(task)
            if payload.model_fields_set & LOCKED_FIELDS:
                await self._forbid_while_processing(session, task.id)
            if payload.status is not None:
                try:
                    payload.status = await lane_rules.require_lane(session, payload.status)
                except lane_rules.LaneError as error:
                    raise ArtifactError(error.code, error.message) from error
            start_at = None
            if payload.model_fields_set & TARGET_FIELDS:
                try:
                    start_at = await resolve_target(session, *requested_target(task, payload))
                except TargetError as error:
                    raise ArtifactError(422, str(error)) from error
            values = None
            if payload.fields is not None:
                values = await values_of_update(session, task, payload.fields)
            before = _snapshot_of(task)
            try:
                result = await repo.update(task, payload, start_at=start_at)
                if values is not None and values != task.field_values:
                    task.field_values = values
                    result.changed.add("fields")
                if not result.changed and not result.renumbered:
                    return await self._read_after_save(session, task)
                recorded = await self._record_changes(session, task, before, actor)
                await session.commit()
            except (PlacementError, ParentError) as error:
                raise ArtifactError(422, str(error)) from error
            except IntegrityError as error:  # the lane was deleted in the meantime
                raise ArtifactError(409, LANE_GONE) from error
            updated = await self._read_after_save(session, task)
        # lane/position only -> "moved"; anything touching the content -> "updated"
        moved_only = result.changed <= {"status", "position"}
        self._bus.publish(
            "task.moved" if moved_only else "task.updated",
            updated.model_dump(mode="json", exclude={"warnings"}),
        )
        self._publish_activity(recorded)
        if result.renumbered:
            self._bus.publish("board.resync", {})  # other tasks of the lane got new positions
        return updated

    async def delete(self, ref: str, by_rule: bool = False) -> str:
        """Delete an artifact (not while it runs, not an archived one unless a board rule does it); its children become
        parentless. Returns its id."""
        async with self._session() as session:
            task = await self._task(session, ref)
            if not by_rule:
                self.forbid_archived(task)
            await self._forbid_while_processing(session, task.id)
            task_id = task.id
            detached = await TaskRepository(session).delete(task)
            await session.commit()
        self._bus.publish("task.deleted", {"id": task_id})
        if detached:
            self._bus.publish("board.resync", {})  # the children lost their parent
        return task_id

    async def archive(self, ref: str, actor: Author = SYSTEM) -> TaskRead:
        """Archive a card by hand: it leaves the board, remembers its lane and can only be read until it is taken out again.
        409 ``archived`` when it already is, 409 while it is being processed. Its children stay on the board."""
        async with self._session() as session:
            task = await self._task(session, ref)
            self.forbid_archived(task)
            await self._forbid_while_processing(session, task.id)
            now = datetime.now(UTC)
            await card_sweeper.archive(session, [task], now, actor)
            await session.commit()
            await session.refresh(task)
            read = await self._read_after_save(session, task)
        self._bus.publish("task.updated", read.model_dump(mode="json", exclude={"warnings"}))
        self._bus.publish("board.updated", {"archived": 1, "deleted": 0})
        self._bus.publish("board.resync", {})
        return read

    async def unarchive(self, ref: str, actor: Author = SYSTEM) -> TaskRead:
        """Take a card out of the archive: back into the lane it came from at the very top (the first lane when that lane is
        gone), ``archived_at`` and ``archived_from_status`` cleared. 409 ``not archived`` for a visible card."""
        async with self._session() as session:
            task = await self._task(session, ref)
            if task.archived_at is None:
                raise ArtifactError(409, "not archived")
            keys = await lane_rules.lane_keys(session)
            lane = task.archived_from_status if task.archived_from_status in keys else keys[0]
            top = await session.scalar(
                select(func.min(Task.position)).where(Task.status == lane, Task.id != task.id)
            )
            titles = await self._lane_titles(session)
            task.status = lane
            task.position = (top - 1.0) if top is not None else 0.0
            task.archived_at = None
            task.archived_from_status = None
            entry = await record(
                session,
                task.id,
                "unarchived",
                actor,
                {"to": titles.get(lane)},
            )
            await session.commit()
            await session.refresh(task)
            read = await self._read_after_save(session, task)
        self._bus.publish("task.updated", read.model_dump(mode="json", exclude={"warnings"}))
        self._publish_activity([entry])
        self._bus.publish("board.updated", {"archived": 0, "deleted": 0, "restored": 1})
        self._bus.publish("board.resync", {})
        return read

    # ── card rules (ADR-071) ──────────────────────────────────────────

    async def card_rules(self) -> card_rules.CardRules:
        """Every card rule: per lane and for the board."""
        async with self._session() as session:
            return await card_rules.load_rules(session)

    async def lane_card_rules(self, lane: str) -> list[Rule]:
        """The rules of one lane (404 for an unknown lane)."""
        async with self._session() as session:
            try:
                key = await lane_rules.require_lane(session, lane)
            except lane_rules.LaneError as error:
                raise ArtifactError(404, error.message) from error
            return (await card_rules.load_rules(session)).lanes.get(key, [])

    async def save_lane_rules(self, lane: str, rules: list[Rule]) -> list[Rule]:
        """Replace the rules of one lane (404 for an unknown lane, 422 for an action a lane does not offer); a sweep follows."""
        async with self._session() as session:
            try:
                lane = await lane_rules.require_lane(session, lane)
                stored = await card_rules.save_lane_rules(session, lane, rules)
            except lane_rules.LaneError as error:
                raise ArtifactError(
                    404 if error.code == 422 else error.code, error.message
                ) from error
            except ValueError as error:
                raise ArtifactError(422, str(error)) from error
            await session.commit()
            lanes = await lane_rules.effective_lanes(session)
        self._bus.publish("board.lanes", {"lanes": [x.model_dump(mode="json") for x in lanes]})
        await self._rules_changed()
        return stored.lanes.get(lane, [])

    async def save_board_rules(self, rules: list[Rule]) -> list[Rule]:
        """Replace the rules of the board (422 for an action the board does not offer); a sweep follows."""
        async with self._session() as session:
            try:
                stored = await card_rules.save_board_rules(session, rules)
            except ValueError as error:
                raise ArtifactError(422, str(error)) from error
            await session.commit()
        await self._rules_changed()
        return stored.board

    async def _rules_changed(self) -> None:
        self._bus.publish("cards.rules.changed", {})
        await self.sweep()
        self._bus.publish("board.resync", {})  # the marks of the cards follow the rules

    async def preview_rule(self, rule: Rule, lane: str | None) -> card_sweeper.Preview:
        """How many cards a rule would hit now (``lane``: one lane; ``None``: the board); ``delete``: archived ones only."""
        async with self._session() as session:
            if lane is not None:
                try:
                    lane = await lane_rules.require_lane(session, lane)
                except lane_rules.LaneError as error:
                    raise ArtifactError(404, error.message) from error
            return await card_sweeper.preview(session, rule, lane)

    async def sweep(self, dry_run: bool = False) -> card_sweeper.Plan:
        """Do what the rules say to the data: archive cards, delete archived ones (never one with children or a run that is
        running; every deletion is logged). ``dry_run`` only reports. Publishes ``board.updated`` when something changed."""
        now = datetime.now(UTC)
        async with self._session() as session:
            rules = await card_rules.load_rules(session)
            todo = await card_sweeper.plan(session, rules, now)
            if dry_run or not (todo.archive or todo.delete):
                return todo
            entries = await card_sweeper.archive(session, todo.archive, now)
            await session.commit()
        self._publish_activity(entries)
        for task in todo.delete:
            try:
                await self.delete(task.id, by_rule=True)
            except ArtifactError:  # it started to run in the meantime: not now
                continue
            async with self._session() as session:
                await card_rules.append_log(
                    session,
                    [card_sweeper.log_entry(task, todo.rule_of.get(task.id, "delete"), now)],
                )
                await session.commit()
            logging.getLogger(__name__).info(
                "Card rule deleted #%s %r (%s)",
                task.number,
                task.title[:80],
                todo.rule_of.get(task.id),
            )
        if todo.archive or todo.delete:
            self._bus.publish(
                "board.updated", {"archived": len(todo.archive), "deleted": len(todo.delete)}
            )
            self._bus.publish("board.resync", {})
        return todo

    async def deletion_log(self) -> list[dict[str, Any]]:
        """What the card rules deleted lately (the last 100): number, title, lane, rule and time."""
        async with self._session() as session:
            return await card_rules.read_log(session)

    # ── processing ────────────────────────────────────────────────────

    @staticmethod
    async def _graph_of_ref(session: AsyncSession, ref: str) -> Graph:
        """A pipeline or an action definition by id, slug or name (what the integration API and MCP are given)."""
        wanted = ref.strip().lower()
        for kind in (GraphKind.PIPELINE, GraphKind.ACTION):
            for graph in await GraphRepository(session).list_all(kind):
                if wanted in (graph.id.lower(), (graph.slug or "").lower(), graph.name.lower()):
                    return graph
        raise ArtifactError(404, "Pipeline or action not found")

    async def dry_run_card(self, graph_ref: str) -> tuple[str | None, int | None]:
        """The hidden card the card-less dry runs of this graph belong to, as (id, number), or (None, None) while none was made (ADR-089)."""
        async with self._session() as session:
            graph = await self._graph_of_ref(session, graph_ref)
            card = await technical.existing_card_of_graph(session, graph.id)
            return (card.id, card.number) if card else (None, None)

    async def check_dry_run(
        self,
        graph_ref: str,
        *,
        task_ref: str | None = None,
        stage_id: str | None = None,
        action_id: str | None = None,
        inputs: Mapping[str, Any] | None = None,
        version: str | None = None,
    ) -> list[str]:
        """What would refuse the dry run of this pipeline or action (by itself) started like this, in plain words; reads only."""
        async with self._session() as session:
            graph = await self._graph_of_ref(session, graph_ref)
            task_id = (await self._task(session, task_ref)).id if task_ref else None
            by_itself = graph.kind == GraphKind.ACTION
        return await self._engine.check_start(
            task_id,
            graph.id,
            None if by_itself else stage_id,
            None if by_itself else action_id,
            inputs,
            version or "draft",
            definition_id=graph.id if by_itself else None,
        )

    async def start_dry_run(
        self,
        graph_ref: str,
        *,
        task_ref: str | None = None,
        stage_id: str | None = None,
        action_id: str | None = None,
        inputs: Mapping[str, Any] | None = None,
        version: str | None = None,
        started_by: StartedBy = StartedBy.USER,
    ) -> RunRead:
        """A dry run (ADR-086) of a pipeline, or of an action definition by itself (ADR-089: its own nodes up to its Output), on the card
        ``task_ref`` or, without one, on the hidden card of the graph, made when it is first needed. ``version`` is ``draft`` or
        ``published`` (the caller's default)."""
        async with self._session() as session:
            graph = await self._graph_of_ref(session, graph_ref)
            if task_ref:
                task = await self._task(session, task_ref)
                self.forbid_archived(task)
            else:
                task = await technical.card_of_graph(session, graph)
                await session.commit()
            task_id, by_itself = task.id, graph.kind == GraphKind.ACTION
        return await self.start(
            task_id,
            graph.id,
            None if by_itself else stage_id,
            None if by_itself else action_id,
            started_by,
            dry_run=True,
            inputs=inputs,
            version=version,
            definition_id=graph.id if by_itself else None,
        )

    async def start(
        self,
        ref: str,
        pipeline_id: str | None = None,
        stage_id: str | None = None,
        action_id: str | None = None,
        started_by: StartedBy = StartedBy.USER,
        *,
        dry_run: bool = False,
        inputs: Mapping[str, Any] | None = None,
        version: str | None = None,
        definition_id: str | None = None,
    ) -> RunRead:
        """Start processing; without a choice, with the pipeline, stage and action the artifact has. A dry run (ADR-086) skips what
        writes and leaves the artifact's own target as it is; with ``definition_id`` it runs that action by itself (ADR-089)."""
        async with self._session() as session:
            task = await self._task(session, ref)
            self.forbid_archived(task)
            if definition_id is not None:
                pipeline_id = definition_id
            if pipeline_id is None:
                pipeline_id = task.pipeline_id
                stage_id = stage_id or task.stage_id
                action_id = action_id or task.action_id
            task_id = task.id
            before = _target_of(task)
        if pipeline_id is None:
            raise ArtifactError(422, "Choose a pipeline first")
        run = await self._engine.start(
            task_id,
            pipeline_id,
            stage_id,
            action_id,
            started_by,
            dry_run=dry_run,
            inputs=inputs,
            version=version,
            definition_id=definition_id,
        )
        # the engine re-targets the artifact in the transaction that claims its run
        async with self._session() as session:
            task = await self._task(session, task_id)
            if _target_of(task) != before:
                read = await self._read_after_save(session, task)
                self._bus.publish(
                    "task.updated", read.model_dump(mode="json", exclude={"warnings"})
                )
        return run

    async def stop(self, ref: str) -> RunRead:
        """Stop processing; the artifact keeps its stage and action."""
        async with self._session() as session:
            task_id = (await self._task(session, ref)).id
        return await self._engine.stop(task_id)

    # ── the emergency stop (ADR-076) ─────────────────────────────────────

    async def stop_switch_state(self) -> stop_switch.StopState:
        """Whether the emergency stop is on, since when, whether the switch is offered and how many executions run."""
        async with self._session() as session:
            active, since = await stop_switch.load(session)
            available = await personal_settings.stop_switch_available(session)
        return stop_switch.StopState(
            active=active,
            since=since,
            available=available,
            running=await self._engine.running_count(),
        )

    async def set_stop_switch(self, active: bool) -> stop_switch.StopState:
        """Switch the emergency stop on (aborts every running execution) or off. On needs the personal setting *Show the emergency stop*.

        Off is always allowed, so a stop can never get stuck behind a hidden switch. Publishes ``settings.changed``
        with ``stop``.
        """
        state = await self.stop_switch_state()
        if active and not state.available:
            raise ArtifactError(
                409,
                'The emergency stop is switched off: switch on "Show the emergency stop" in the personal settings first',
                "stop_unavailable",
            )
        if active == state.active:
            return state
        aborted = await self._engine.set_stop(active)
        state = (await self.stop_switch_state()).model_copy(update={"aborted": aborted})
        self._bus.publish("settings.changed", {"stop": state.model_dump(mode="json")})
        return state

    async def refuse_hiding_active_stop(self) -> None:
        """409 while the emergency stop is on: the switch cannot be hidden then, a stop is never cleared by a settings change."""
        if await self._engine.stop_active():
            raise ArtifactError(
                409,
                "The emergency stop is on: switch it off before you hide it",
                "stop_active",
            )

    # ── helpers ───────────────────────────────────────────────────────

    def _publish_activity(self, entries: list[ActivityRead]) -> None:
        for entry in entries:
            self._bus.publish("activity.created", entry.model_dump(mode="json"))

    @staticmethod
    async def _lane_titles(session: AsyncSession) -> dict[str, str]:
        return {lane.status: lane.title for lane in await lane_rules.effective_lanes(session)}

    @staticmethod
    async def _lane_names(session: AsyncSession) -> dict[str, tuple[str, str]]:
        """Storage key -> (id, name) of every lane: how a card says which lane it is in (ADR-090)."""
        return {
            lane.status: (lane.id, lane.title) for lane in await lane_rules.effective_lanes(session)
        }

    @staticmethod
    async def _title_of(session: AsyncSession, task_id: str | None) -> str | None:
        task = None if task_id is None else await session.get(Task, task_id)
        return None if task is None else task.title

    @staticmethod
    async def _names_of(
        session: AsyncSession, pipeline_id: str | None, *node_ids: str | None
    ) -> tuple[str | None, list[str | None]]:
        """The name of a pipeline and the labels of some of its nodes (``None`` where unknown)."""
        if pipeline_id is None:
            return None, [None] * len(node_ids)
        graph = await graph_for_run(session, pipeline_id)
        labels = {n["id"]: n["label"] for n in graph["nodes"]}
        return graph["name"] or None, [labels.get(i) if i else None for i in node_ids]

    async def _record_changes(
        self, session: AsyncSession, task: Task, before: dict[str, Any], actor: Author
    ) -> list[ActivityRead]:
        """One activity entry per real change between ``before`` and the task now (in the caller's transaction)."""
        entries: list[ActivityRead] = []

        async def add(kind: str, data: dict[str, Any]) -> None:
            entries.append(await record(session, task.id, kind, actor, data))

        if task.status != before["status"]:
            lanes = await self._lane_titles(session)
            await add(
                "lane",
                {"from": lanes.get(before["status"]), "to": lanes.get(task.status)},
            )
        if task.title != before["title"]:
            await add("title", {"from": short(before["title"]), "to": short(task.title)})
        if task.body != before["body"]:
            await add("description", {})
        if task.parent_id != before["parent_id"]:
            await add(
                "parent",
                {
                    "from": await self._title_of(session, before["parent_id"]),
                    "to": await self._title_of(session, task.parent_id),
                },
            )
        if _target_of(task) != before["target"]:
            old_pipeline, new_pipeline = before["target"][0], task.pipeline_id
            if old_pipeline != new_pipeline:
                name, _ = await self._names_of(session, new_pipeline)
                await add("pipeline", {"to": name})
            elif task.stage_id != before["target"][1]:
                name, (stage,) = await self._names_of(session, new_pipeline, task.stage_id)
                await add("stage", {"to": stage, "pipeline": name})
            else:
                name, (action,) = await self._names_of(session, new_pipeline, task.action_id)
                await add("action", {"to": action, "pipeline": name})
        now = json.loads(task.field_values or "{}")
        for name in sorted(set(before["fields"]) | set(now)):
            if before["fields"].get(name) == now.get(name):
                continue
            field_row = await session.get(ArtifactField, name)
            await add(
                "field",
                {
                    "field": name,
                    "label": field_row.label if field_row else name,
                    "from": short(before["fields"].get(name)),
                    "to": short(now.get(name)),
                },
            )
        return entries

    @staticmethod
    async def _task(session: AsyncSession, ref: str) -> Task:
        repo = TaskRepository(session)
        number = ref.lstrip("#")
        task = None
        if number.isdigit():
            task = await session.scalar(select(Task).where(Task.number == int(number)))
        if task is None:
            task = await repo.get(ref)
        if task is None:
            raise ArtifactError(404, "Artifact not found")
        return task

    @staticmethod
    async def _execution(
        session: AsyncSession,
        task_id: str,
        execution_id: str,
        *,
        with_snapshot: bool = False,
        with_context: bool = False,
    ) -> Execution:
        query = select(Execution).where(Execution.id == execution_id, Execution.task_id == task_id)
        if with_snapshot:
            query = query.options(undefer(Execution.snapshot))
        if with_context:
            query = query.options(undefer(Execution.context))
        row = await session.scalar(query)
        if row is None:
            raise ArtifactError(404, "Execution not found")
        return row

    @staticmethod
    async def _forbid_while_processing(session: AsyncSession, task_id: str) -> None:
        running = await session.scalar(
            select(PipelineRun.id).where(
                PipelineRun.task_id == task_id, PipelineRun.status == RunStatus.RUNNING
            )
        )
        if running is not None:
            raise ArtifactError(409, "The artifact is being processed")
