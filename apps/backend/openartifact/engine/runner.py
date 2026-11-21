"""The execution engine.

``start`` records a run for an artifact and walks it through its pipeline in a background task:
trigger, then stage by stage, action by action, along *On Pass* / *On Error*, until the last stage
is done. Every step is saved and published (``run.updated``), so a restart or a second browser
sees the same state. ``stop`` cancels the task. Starting and stopping are the same for a user
and for the system (``started_by``); the artifact is locked while its run is running.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openartifact.engine.chain import edge_from, locate, pipeline_chain
from openartifact.engine.snapshot import NestingError, build_snapshot
from openartifact.events import EventBus
from openartifact.models import PipelineRun, RunStage, Task, Workflow

logger = logging.getLogger("openartifact")

MAX_STEPS = 1000  # a pipeline that loops for ever fails instead of running for ever
_UNSET: Any = object()


class RunError(Exception):
    """A request the engine refuses; ``status`` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class _RunFailedError(Exception):
    """The run cannot go on (shown as the note of a failed run)."""


class RunEngine:
    """Starts, stops and executes runs."""

    def __init__(
        self, bus: EventBus, factory: Callable[[], async_sessionmaker[AsyncSession]]
    ) -> None:
        self._bus = bus
        self._factory = factory
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._top: dict[str, str] = {}  # the entry of the pipeline a run is in (it may be deeper)

    # ── reading ───────────────────────────────────────────────────────

    async def read(self, session: AsyncSession, run: PipelineRun) -> dict[str, Any]:
        """The run as the API returns it: where it is, in names, and the status of every stage."""
        snapshot = json.loads(run.snapshot)
        graphs = [snapshot, *snapshot.get("pipelines", {}).values()]
        labels = {n["id"]: n["label"] for graph in graphs for n in graph["nodes"]}
        stages = (
            await session.execute(
                select(RunStage).where(RunStage.run_id == run.id).order_by(RunStage.position)
            )
        ).scalars()
        where = locate(snapshot, run.stage_id)
        nested = where["pipeline_id"] is not None
        return {
            "id": run.id,
            "task_id": run.task_id,
            "workflow_id": run.workflow_id,
            "workflow_name": snapshot["name"],
            # where the run is, following the flow into called pipelines
            "pipeline_id": where["pipeline_id"] or run.workflow_id,
            "pipeline_name": where["pipeline_name"],
            # where to start again: the entry of the run's own pipeline (the call, if it is inside one)
            "resume_stage_id": where["entry_id"],
            "resume_action_id": None if nested else run.action_id,
            "status": run.status,
            "started_by": run.started_by,
            "note": run.note,
            "stage_id": run.stage_id,
            "stage_name": labels.get(run.stage_id or ""),
            "action_id": run.action_id,
            "action_name": labels.get(run.action_id or ""),
            "stages": [{"id": s.stage_id, "name": s.name, "status": s.status} for s in stages],
            "updated_at": run.updated_at.isoformat(),
        }

    async def list_all(self, session: AsyncSession) -> list[dict[str, Any]]:
        """Every run."""
        runs = (await session.execute(select(PipelineRun))).scalars().all()
        return [await self.read(session, run) for run in runs]

    async def _publish(self, task_id: str) -> None:
        async with self._factory()() as session:
            run = await self._run_of(session, task_id)
            if run is not None:
                self._bus.publish("run.updated", await self.read(session, run))

    @staticmethod
    async def _run_of(session: AsyncSession, task_id: str) -> PipelineRun | None:
        return await session.scalar(select(PipelineRun).where(PipelineRun.task_id == task_id))

    # ── starting and stopping ─────────────────────────────────────────

    async def start(
        self,
        task_id: str,
        workflow_id: str,
        stage_id: str | None = None,
        action_id: str | None = None,
        started_by: str = "user",
    ) -> dict[str, Any]:
        """Start (or restart) the artifact in a pipeline, at a stage and action (default: the first).

        Stages before the starting stage count as done: those the artifact has passed keep that
        status, the others are marked ``skipped``.
        """
        async with self._factory()() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise RunError(404, "Artifact not found")
            run = await self._run_of(session, task_id)
            if run is not None and run.status == "running":
                raise RunError(409, "The artifact is already being processed")
            workflow = await session.get(Workflow, workflow_id)
            if workflow is None or workflow.kind != "workflow":
                raise RunError(422, "That pipeline does not exist")
            try:
                snapshot = await build_snapshot(session, workflow)
            except NestingError as error:
                raise RunError(422, str(error)) from error
            chain = pipeline_chain(snapshot["nodes"], snapshot["edges"])
            if not chain:
                raise RunError(422, "The pipeline has no stages from its trigger on")
            index = (
                0
                if stage_id is None
                else next((i for i, s in enumerate(chain) if s["id"] == stage_id), -1)
            )
            if index < 0:
                raise RunError(422, "That stage is not part of the pipeline")
            stage = chain[index]
            if action_id is not None and action_id not in {a["id"] for a in stage["actions"]}:
                raise RunError(422, "That action is not in the stage")

            previous: dict[str, str] = {}
            if run is None:
                run = PipelineRun(id=str(uuid.uuid4()), task_id=task_id)
                session.add(run)
            else:
                if run.workflow_id == workflow.id:
                    rows = await session.execute(select(RunStage).where(RunStage.run_id == run.id))
                    previous = {r.stage_id: r.status for r in rows.scalars()}
                await session.execute(delete(RunStage).where(RunStage.run_id == run.id))
            # the artifact keeps what it was started with, so the next start offers the same
            task.pipeline_id, task.stage_id = workflow.id, stage["id"]
            task.action_id = (
                (action_id or stage["first_action_id"]) if stage["kind"] == "stage" else None
            )
            run.workflow_id = workflow.id
            run.created_at = datetime.now(UTC)  # the row is reused: this is when this run began
            run.status = "running"
            run.started_by = started_by
            run.stage_id = stage["id"]
            run.action_id = (
                (action_id or stage["first_action_id"]) if stage["kind"] == "stage" else None
            )
            run.note = None
            run.snapshot = json.dumps(snapshot)
            await session.flush()
            for i, s in enumerate(chain):
                if i < index:
                    state = "passed" if previous.get(s["id"]) == "passed" else "skipped"
                else:
                    state = "pending"
                session.add(
                    RunStage(
                        run_id=run.id, stage_id=s["id"], name=s["name"], position=i, status=state
                    )
                )
            await session.commit()
            result = await self.read(session, run)
        self._bus.publish("run.updated", result)
        self._jobs[task_id] = asyncio.create_task(self._execute(task_id))
        return result

    async def stop(self, task_id: str) -> dict[str, Any]:
        """Stop a running artifact; it stays at its stage and action and can be started again."""
        job = self._jobs.pop(task_id, None)
        if job is not None:
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
        async with self._factory()() as session:
            run = await self._run_of(session, task_id)
            if run is None or run.status != "running":
                raise RunError(409, "The artifact is not being processed")
            run.status = "stopped"
            run.note = "stopped"
            await session.execute(
                update(RunStage)
                .where(RunStage.run_id == run.id, RunStage.status == "running")
                .values(status="pending")
            )
            await session.commit()
            result = await self.read(session, run)
        self._bus.publish("run.updated", result)
        return result

    async def recover(self) -> None:
        """After a restart no run is running any more; the ones that were are stopped."""
        async with self._factory()() as session:
            runs = (
                (await session.execute(select(PipelineRun).where(PipelineRun.status == "running")))
                .scalars()
                .all()
            )
            for run in runs:
                run.status = "stopped"
                run.note = "interrupted"
                await session.execute(
                    update(RunStage)
                    .where(RunStage.run_id == run.id, RunStage.status == "running")
                    .values(status="pending")
                )
            await session.commit()

    async def shutdown(self) -> None:
        """Cancel the running background tasks."""
        jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        self._jobs.clear()

    # ── executing ─────────────────────────────────────────────────────

    async def _save(
        self,
        task_id: str,
        *,
        status: str | None = None,
        stage_id: Any = _UNSET,
        action_id: Any = _UNSET,
        note: str | None = None,
        stage_state: tuple[str, str] | None = None,
    ) -> None:
        async with self._factory()() as session:
            run = await self._run_of(session, task_id)
            if run is None:
                return
            if status is not None:
                run.status = status
            if stage_id is not _UNSET:
                run.stage_id = stage_id
            if action_id is not _UNSET:
                run.action_id = action_id
            if note is not None:
                run.note = note
            if stage_state is not None:
                await session.execute(
                    update(RunStage)
                    .where(RunStage.run_id == run.id, RunStage.stage_id == stage_state[0])
                    .values(status=stage_state[1])
                )
            await session.commit()
        await self._publish(task_id)

    async def _execute(self, task_id: str) -> None:
        try:
            async with self._factory()() as session:
                run = await self._run_of(session, task_id)
                if run is None:
                    return
                snapshot = json.loads(run.snapshot)
                stage_id, action_id = run.stage_id, run.action_id
            chain = pipeline_chain(snapshot["nodes"], snapshot["edges"])
            start = next(i for i, s in enumerate(chain) if s["id"] == stage_id)
            await self._walk(task_id, snapshot, snapshot, chain, start, action_id, {"steps": 0}, 0)
            await self._save(
                task_id, status="done"
            )  # it rests where it ended, even inside a called pipeline
        except asyncio.CancelledError:
            raise
        except _RunFailedError as failure:
            await self._fail(task_id, str(failure))
        except Exception:
            logger.exception("Run of artifact %s failed", task_id)
            await self._fail(task_id, "Internal error")
        finally:
            self._jobs.pop(task_id, None)
            self._top.pop(task_id, None)

    async def _walk(
        self,
        task_id: str,
        snapshot: dict[str, Any],
        graph: dict[str, Any],
        chain: list[dict[str, Any]],
        start: int,
        action_id: str | None,
        state: dict[str, int],
        depth: int,
    ) -> None:
        """Run the entries of a chain from ``start`` on; a pipeline node runs its pipeline the same way.

        Only the entries of the outermost pipeline have a status of their own (``run_stages``); inside
        a called pipeline the run shows the stage and action that are current.
        """
        top = depth == 0
        nodes = {n["id"]: n for n in graph["nodes"]}
        for entry in chain[start:]:
            if top:
                self._top[task_id] = entry["id"]
            if entry["kind"] == "pipeline":
                called = snapshot["pipelines"].get(entry["pipeline_id"] or "")
                if called is None:
                    raise _RunFailedError(f'"{entry["name"]}" has no pipeline chosen')
                await self._save(
                    task_id,
                    stage_id=entry["id"],
                    action_id=None,
                    stage_state=(entry["id"], "running") if top else None,
                )
                inner = pipeline_chain(called["nodes"], called["edges"])
                await self._walk(task_id, snapshot, called, inner, 0, None, state, depth + 1)
                if top:
                    await self._save(task_id, stage_state=(entry["id"], "passed"))
                continue
            action = action_id or entry["first_action_id"]
            action_id = None
            await self._save(
                task_id,
                stage_id=entry["id"],
                action_id=action,
                stage_state=(entry["id"], "running") if top else None,
            )
            while action is not None:
                state["steps"] += 1
                if state["steps"] > MAX_STEPS:
                    raise _RunFailedError("The pipeline does not come to an end")
                node = nodes[action]
                await self._save(task_id, action_id=action)
                passed = await self._run_action(node, snapshot)
                edge = edge_from(graph["edges"], action, "pass" if passed else "error")
                if edge is None:
                    raise _RunFailedError(
                        f'"{node["label"]}" has no On Pass connection'
                        if passed
                        else f'"{node["label"]}" failed'
                    )
                target = nodes[edge["target_id"]]
                action = target["id"] if target["kind"] == "action" else None
            if top:
                await self._save(task_id, stage_state=(entry["id"], "passed"))

    async def _fail(self, task_id: str, note: str) -> None:
        async with self._factory()() as session:
            run = await self._run_of(session, task_id)
            current = run.stage_id if run else None
        top = self._top.get(task_id) or current
        await self._save(
            task_id,
            status="failed",
            note=note,
            stage_state=(top, "failed") if top else None,
        )

    @staticmethod
    async def _run_action(node: dict[str, Any], snapshot: dict[str, Any]) -> bool:
        """Run an action's definition from its trigger: True for On Pass, False for On Fail.

        An action that is not linked to a definition is an empty shell and passes at once.
        """
        if not node["definition_id"]:
            return True
        definition = snapshot["definitions"][node["definition_id"]]
        nodes = {n["id"]: n for n in definition["nodes"]}
        current = next(n for n in definition["nodes"] if n["kind"] == "trigger")
        for _ in range(MAX_STEPS):
            edge = edge_from(definition["edges"], current["id"], "out")
            if edge is None:
                return False  # a dead end: the action did not come to its output
            current = nodes[edge["target_id"]]
            if current["kind"] == "output":
                return bool(edge["target_port"] == "pass")
            if current["kind"] == "timer":
                await asyncio.sleep(current["seconds"] or 0)
        return False
