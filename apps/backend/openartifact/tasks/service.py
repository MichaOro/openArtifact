"""What can be done with artifacts, once, for every way in.

The browser's REST API, the integration API (``/api/v1``), the MCP server and, later, actions all call
this class, so the rules (validation, the lock while an artifact is processed, events, where a new
artifact came from) exist in one place. Every method opens its own session and commits.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from openartifact.artifact_types.service import assign_new, assign_update
from openartifact.database import SessionOpener
from openartifact.engine import history as history_module
from openartifact.engine import history_query
from openartifact.engine.chain import pipeline_chain
from openartifact.engine.flow import build_flow
from openartifact.engine.flow_schemas import ExecutionFlow
from openartifact.engine.history import Changes, labels_of
from openartifact.engine.runner import RunEngine
from openartifact.engine.schemas import (
    ExecutionDetail,
    ExecutionList,
    ExecutionRead,
    ExecutionsPage,
    ExecutionStepRead,
    HistoryPolicyResult,
    HistoryPolicyWrite,
    NodeResultRead,
    RunContextRead,
    RunRead,
)
from openartifact.engine.snapshot import graph_of
from openartifact.engine.targets import TargetError, resolve_target
from openartifact.events import EventBus
from openartifact.exceptions import ArtifactError
from openartifact.models import (
    CreatedBy,
    Execution,
    Graph,
    GraphKind,
    PipelineRun,
    RunNodeResult,
    RunStatus,
    StartedBy,
    Task,
    TaskStatus,
)
from openartifact.tasks.lanes import LaneTitleError, effective_lanes, rename_lane
from openartifact.tasks.repository import ParentError, PlacementError, TaskRepository
from openartifact.tasks.schemas import LaneRead, TaskCreate, TaskRead, TaskUpdate

LOCKED_FIELDS = {
    "status",
    "before_id",
    "parent_id",
    "pipeline_id",
    "stage_id",
    "action_id",
    "type_id",
    "parameters",
    "reset_parameters",
}
#: The fields of a task update that change its type or its parameters.
PARAMETER_FIELDS = {"type_id", "parameters", "reset_parameters"}


#: The fields of a task that say where it starts.
TARGET_FIELDS = {"pipeline_id", "stage_id", "action_id"}


def _target_of(task: Task) -> tuple[str | None, str | None, str | None]:
    return task.pipeline_id, task.stage_id, task.action_id


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

    async def list_all(self) -> list[TaskRead]:
        """All artifacts in board order."""
        async with self._session() as session:
            tasks = await TaskRepository(session).list_all()
            return [TaskRead.model_validate(t) for t in tasks]

    async def get(self, ref: str) -> TaskRead:
        """One artifact by id, or by its number (``12`` or ``#12``)."""
        async with self._session() as session:
            return TaskRead.model_validate(await self._task(session, ref))

    async def lanes(self) -> list[LaneRead]:
        """The board lanes with their current titles."""
        async with self._session() as session:
            return await effective_lanes(session)

    async def rename_lane(self, status: str, title: str | None) -> list[LaneRead]:
        """Give a lane its own title (``None``: back to the default); publishes ``board.lanes``."""
        try:
            lane = TaskStatus(status)
        except ValueError as error:
            raise ArtifactError(404, f"Unknown lane '{status}'") from error
        async with self._session() as session:
            try:
                lanes = await rename_lane(session, lane, title)
            except LaneTitleError as error:
                raise ArtifactError(422, str(error)) from error
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
                graph = await graph_of(session, pipeline.id)
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
        """The newest ``limit`` executions of the artifact (newest first), their total and the policy."""
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
                policy=self._engine.history.policy_of(task),
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
    ) -> ExecutionsPage:
        """The executions of all artifacts, newest first, one page (see ``engine/history_query.py``)."""
        flt = history_query.ExecutionFilter.parse(
            status=status, started_by=started_by, pipeline=pipeline, q=q, since=since, until=until
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
            return build_flow(
                ExecutionRead.of(row),
                row.snapshot,
                self._named(steps, row.snapshot),
                outputs,
                (row.started_stage_id, row.started_action_id),
            )

    async def execution_step(self, ref: str, execution_id: str, step_id: str) -> ExecutionStepRead:
        """One step of the execution with its complete output; 404 if it is not a step of this execution."""
        async with self._session() as session:
            task = await self._task(session, ref)
            row = await self._execution(session, task.id, execution_id, with_snapshot=True)
            step = await session.scalar(
                select(RunNodeResult).where(
                    RunNodeResult.id == step_id, RunNodeResult.execution_id == row.id
                )
            )
            if step is None:
                raise ArtifactError(404, "Step not found")
            return self._named([NodeResultRead.of(step)], row.snapshot)[0]

    async def delete_execution(self, ref: str, execution_id: str) -> None:
        """Delete one execution with its steps (409 while it runs)."""
        async with self._session() as session:
            task = await self._task(session, ref)
            row = await self._execution(session, task.id, execution_id)
            if row.status == RunStatus.RUNNING:
                raise ArtifactError(409, "The execution is running; stop it first")
            changes = Changes()
            await self._engine.history.remove(session, task.id, [row.id], changes)
            await session.commit()
        self._engine.history.publish(changes)

    async def clear_executions(self, ref: str) -> int:
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
            await self._engine.history.remove(session, task.id, ids, changes)
            await session.commit()
        self._engine.history.publish(changes)
        return len(ids)

    async def set_history_policy(self, ref: str, policy: HistoryPolicyWrite) -> HistoryPolicyResult:
        """Replace the artifact's retention policy and apply it at once."""
        async with self._session() as session:
            task = await self._task(session, ref)
            task.history_keep_last = policy.keep_last
            task.history_keep_hours = policy.keep_hours
            changes = Changes()
            deleted = await self._engine.history.prune(session, task, changes)
            await session.commit()
            result = HistoryPolicyResult(
                policy=self._engine.history.policy_of(task), deleted=deleted
            )
        self._engine.history.publish(changes)
        return result

    # ── changing ──────────────────────────────────────────────────────

    async def create(self, data: TaskCreate, created_by: CreatedBy = CreatedBy.USER) -> TaskRead:
        """Create an artifact: lane, optional parent, optional pipeline with its first stage and action."""
        async with self._session() as session:
            try:
                target = await resolve_target(
                    session, data.pipeline_id, data.stage_id, data.action_id
                )
                task = await TaskRepository(session).create(
                    data, created_by=created_by, target=target
                )
            except (TargetError, ParentError) as error:
                raise ArtifactError(422, str(error)) from error
            assignment = await assign_new(session, data.type_id, data.parameters)
            task.type_id, task.parameters = assignment.type_id, assignment.text
            await session.commit()
            created = TaskRead.model_validate(task)
        self._bus.publish("task.created", created.model_dump(mode="json"))
        return created

    async def update(self, ref: str, payload: TaskUpdate) -> TaskRead:
        """Edit, move, reorder or re-target an artifact (lane, order, parent and target are locked while it runs)."""
        async with self._session() as session:
            repo = TaskRepository(session)
            task = await self._task(session, ref)
            if payload.model_fields_set & LOCKED_FIELDS:
                await self._forbid_while_processing(session, task.id)
            start_at = None
            if payload.model_fields_set & TARGET_FIELDS:
                try:
                    start_at = await resolve_target(session, *requested_target(task, payload))
                except TargetError as error:
                    raise ArtifactError(422, str(error)) from error
            assignment = None
            if payload.model_fields_set & PARAMETER_FIELDS:
                assignment = await assign_update(
                    session,
                    task,
                    type_id=payload.type_id,
                    type_sent="type_id" in payload.model_fields_set,
                    values=payload.parameters,
                    reset=payload.reset_parameters,
                )
            try:
                result = await repo.update(task, payload, start_at=start_at)
            except (PlacementError, ParentError) as error:
                raise ArtifactError(422, str(error)) from error
            if assignment is not None and (assignment.type_id, assignment.text) != (
                task.type_id,
                task.parameters,
            ):
                task.type_id, task.parameters = assignment.type_id, assignment.text
                result.changed.add("parameters")
            if not result.changed and not result.renumbered:
                return TaskRead.model_validate(task)
            await session.commit()
            updated = TaskRead.model_validate(task)
        # lane/position only -> "moved"; anything touching the content -> "updated"
        moved_only = result.changed <= {"status", "position"}
        self._bus.publish(
            "task.moved" if moved_only else "task.updated", updated.model_dump(mode="json")
        )
        if result.renumbered:
            self._bus.publish("board.resync", {})  # other tasks of the lane got new positions
        return updated

    async def delete(self, ref: str) -> str:
        """Delete an artifact (not while it runs); its children become parentless. Returns its id."""
        async with self._session() as session:
            task = await self._task(session, ref)
            await self._forbid_while_processing(session, task.id)
            task_id = task.id
            detached = await TaskRepository(session).delete(task)
            await session.commit()
        self._bus.publish("task.deleted", {"id": task_id})
        if detached:
            self._bus.publish("board.resync", {})  # the children lost their parent
        return task_id

    # ── processing ────────────────────────────────────────────────────

    async def start(
        self,
        ref: str,
        pipeline_id: str | None = None,
        stage_id: str | None = None,
        action_id: str | None = None,
        started_by: StartedBy = StartedBy.USER,
    ) -> RunRead:
        """Start processing; without a choice, with the pipeline, stage and action the artifact has."""
        async with self._session() as session:
            task = await self._task(session, ref)
            if pipeline_id is None:
                pipeline_id = task.pipeline_id
                stage_id = stage_id or task.stage_id
                action_id = action_id or task.action_id
            task_id = task.id
            before = _target_of(task)
        if pipeline_id is None:
            raise ArtifactError(422, "Choose a pipeline first")
        run = await self._engine.start(task_id, pipeline_id, stage_id, action_id, started_by)
        # the engine re-targets the artifact in the transaction that claims its run
        async with self._session() as session:
            task = await self._task(session, task_id)
            if _target_of(task) != before:
                self._bus.publish(
                    "task.updated", TaskRead.model_validate(task).model_dump(mode="json")
                )
        return run

    async def stop(self, ref: str) -> RunRead:
        """Stop processing; the artifact keeps its stage and action."""
        async with self._session() as session:
            task_id = (await self._task(session, ref)).id
        return await self._engine.stop(task_id)

    # ── helpers ───────────────────────────────────────────────────────

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
