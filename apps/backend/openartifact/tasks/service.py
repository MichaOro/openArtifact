"""What can be done with artifacts, once, for every way in.

The browser's REST API, the integration API (``/api/v1``), the MCP server and, later, actions all call
this class, so the rules (validation, the lock while an artifact is processed, events, where a new
artifact came from) exist in one place. Every method opens its own session and commits.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openartifact.engine.chain import pipeline_chain
from openartifact.engine.runner import RunEngine, RunError
from openartifact.engine.snapshot import graph_of
from openartifact.engine.targets import TargetError, resolve_target
from openartifact.events import EventBus
from openartifact.models import PipelineRun, Task, Workflow
from openartifact.tasks.repository import ParentError, PlacementError, TaskRepository
from openartifact.tasks.schemas import TaskCreate, TaskRead, TaskUpdate

LOCKED_FIELDS = {"status", "before_id", "parent_id", "pipeline_id", "stage_id", "action_id"}


class ArtifactError(Exception):
    """A request that cannot be done; ``status`` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class ArtifactService:
    """Create, read, change, delete and process artifacts."""

    def __init__(
        self,
        factory: Callable[[], async_sessionmaker[AsyncSession]],
        bus: EventBus,
        engine: RunEngine,
    ) -> None:
        self._factory = factory
        self._bus = bus
        self._engine = engine

    # ── reading ───────────────────────────────────────────────────────

    async def list_all(self) -> list[TaskRead]:
        """All artifacts in board order."""
        async with self._factory()() as session:
            tasks = await TaskRepository(session).list_all()
            return [TaskRead.model_validate(t) for t in tasks]

    async def get(self, ref: str) -> TaskRead:
        """One artifact by id, or by its number (``12`` or ``#12``)."""
        async with self._factory()() as session:
            return TaskRead.model_validate(await self._task(session, ref))

    async def pipelines(self) -> list[dict[str, Any]]:
        """The pipelines with their stages in running order and the actions of every stage."""
        async with self._factory()() as session:
            result = []
            pipelines = (
                (
                    await session.execute(
                        select(Workflow).where(Workflow.kind == "workflow").order_by(Workflow.name)
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

    async def run(self, ref: str) -> dict[str, Any] | None:
        """The state of the artifact's processing, or ``None`` if it never ran."""
        async with self._factory()() as session:
            task = await self._task(session, ref)
            run = await session.scalar(select(PipelineRun).where(PipelineRun.task_id == task.id))
            return None if run is None else await self._engine.read(session, run)

    # ── changing ──────────────────────────────────────────────────────

    async def create(self, data: TaskCreate, created_by: str = "user") -> TaskRead:
        """Create an artifact: lane, optional parent, optional pipeline with its first stage and action."""
        async with self._factory()() as session:
            try:
                target = await resolve_target(
                    session, data.pipeline_id, data.stage_id, data.action_id
                )
                task = await TaskRepository(session).create(
                    data, created_by=created_by, target=target
                )
            except (TargetError, ParentError) as error:
                raise ArtifactError(422, str(error)) from error
            await session.commit()
            created = TaskRead.model_validate(task)
        self._bus.publish("task.created", created.model_dump(mode="json"))
        return created

    async def update(self, ref: str, payload: TaskUpdate) -> TaskRead:
        """Edit, move, reorder or re-target an artifact (lane, order, parent and target are locked while it runs)."""
        async with self._factory()() as session:
            repo = TaskRepository(session)
            task = await self._task(session, ref)
            if payload.model_fields_set & LOCKED_FIELDS:
                await self._forbid_while_processing(session, task.id)
            start_at = None
            sent = payload.model_fields_set
            if sent & {"pipeline_id", "stage_id", "action_id"}:
                pipeline = payload.pipeline_id if "pipeline_id" in sent else task.pipeline_id
                same = pipeline == task.pipeline_id
                stage = (
                    payload.stage_id if "stage_id" in sent else (task.stage_id if same else None)
                )
                action = (
                    payload.action_id
                    if "action_id" in sent
                    else (task.action_id if same and "stage_id" not in sent else None)
                )
                try:
                    start_at = await resolve_target(session, pipeline, stage, action)
                except TargetError as error:
                    raise ArtifactError(422, str(error)) from error
            try:
                result = await repo.update(task, payload, start_at=start_at)
            except (PlacementError, ParentError) as error:
                raise ArtifactError(422, str(error)) from error
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
        async with self._factory()() as session:
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
        started_by: str = "user",
    ) -> dict[str, Any]:
        """Start processing; without a choice, with the pipeline, stage and action the artifact has."""
        async with self._factory()() as session:
            task = await self._task(session, ref)
            if pipeline_id is None:
                pipeline_id = task.pipeline_id
                stage_id = stage_id or task.stage_id
                action_id = action_id or task.action_id
            task_id = task.id
        if pipeline_id is None:
            raise ArtifactError(422, "Choose a pipeline first")
        try:
            return await self._engine.start(task_id, pipeline_id, stage_id, action_id, started_by)
        except RunError as error:
            raise ArtifactError(error.status, error.message) from error

    async def stop(self, ref: str) -> dict[str, Any]:
        """Stop processing; the artifact keeps its stage and action."""
        async with self._factory()() as session:
            task_id = (await self._task(session, ref)).id
        try:
            return await self._engine.stop(task_id)
        except RunError as error:
            raise ArtifactError(error.status, error.message) from error

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
    async def _forbid_while_processing(session: AsyncSession, task_id: str) -> None:
        running = await session.scalar(
            select(PipelineRun.id).where(
                PipelineRun.task_id == task_id, PipelineRun.status == "running"
            )
        )
        if running is not None:
            raise ArtifactError(409, "The artifact is being processed")
