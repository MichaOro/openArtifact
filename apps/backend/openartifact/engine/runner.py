"""The execution engine.

``start`` records a run for an artifact and walks it through its pipeline in a background task:
trigger, then stage by stage, action by action, along *On Pass* / *On Error*, until the last stage
is done. Every step is saved and published (``run.updated``), so a restart or a second browser
sees the same state. ``stop`` cancels the task. Starting and stopping are the same for a user
and for the system (``started_by``); the artifact is locked while its run is running.

The run row is the *current* state of an artifact and is reused by every start; each start also
opens an ``Execution`` (see ``history.py``) that keeps its steps and its end result for good.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.database import SessionOpener
from openartifact.engine import code_registry
from openartifact.engine.chain import edge_from, locate, pipeline_chain
from openartifact.engine.executors import EXECUTORS, Limits
from openartifact.engine.history import Changes, ExecutionHistory, utcnow
from openartifact.engine.results import NodeResult
from openartifact.engine.schemas import ExecutionRead, NodeResultRead, RunRead, RunStageRead
from openartifact.engine.snapshot import NestingError, build_snapshot
from openartifact.engine.targets import TargetError, load_pipeline, pick_start
from openartifact.events import EventBus
from openartifact.exceptions import ArtifactError
from openartifact.graph.node_types import Ports
from openartifact.models import (
    Execution,
    NodeKind,
    PipelineRun,
    RunNodeResult,
    RunStage,
    RunStatus,
    StageStatus,
    StartedBy,
    Task,
)

logger = logging.getLogger(__name__)

#: All outputs of one execution together; when it is exceeded the oldest outputs are removed.
RUN_OUTPUT_LIMIT_CHARS = 1024 * 1024
#: Longest output stored for one node.
RESULT_OUTPUT_LIMIT_CHARS = 256 * 1024
REMOVED_OUTPUT = "[output removed: the results of this execution are limited]"
#: Steps a run read carries (the newest); ``results`` of the run has them all.
RUN_READ_RESULTS = 200
MAX_STEPS = 1000  # a pipeline that loops for ever fails instead of running for ever
_UNSET: Any = object()


class _RunFailedError(Exception):
    """The run cannot go on (shown as the note of a failed run)."""


@dataclass
class _Walk:
    """What one execution of a run carries along: its snapshot, the steps taken and where it is."""

    task_id: str
    execution_id: str | None
    snapshot: dict[str, Any]
    steps: int = 0
    #: The entry of the outermost pipeline the run is in (the walk may be deeper, in a called one).
    top_entry: str | None = None
    #: Where the run is while it executes an action (stored with every step it records).
    pipeline_id: str | None = None
    depth: int = 0
    stage_id: str | None = None
    action_id: str | None = None
    seq: int = 0

    def step(self) -> None:
        """Count a step; actions and the nodes of their definitions count against the same limit."""
        self.steps += 1
        if self.steps > MAX_STEPS:
            raise _RunFailedError("The pipeline does not come to an end")


class RunEngine:
    """Starts, stops and executes runs."""

    def __init__(
        self,
        bus: EventBus,
        session: SessionOpener,
        max_runs: int = 8,
        limits: Limits | None = None,
        history_default_keep: int = 50,
    ) -> None:
        self._bus = bus
        self.history = ExecutionHistory(bus, history_default_keep)
        self._session = session
        self._max_runs = max_runs
        self._limits = limits or Limits()
        # artifacts whose start has not reached its background task
        self._starting: set[str] = set()
        self._jobs: dict[str, asyncio.Task[None]] = {}

    # ── reading ───────────────────────────────────────────────────────

    async def read(self, session: AsyncSession, run: PipelineRun) -> RunRead:
        """The run as the API returns it: where it is, in names, and the status of every stage."""
        snapshot = json.loads(run.snapshot)
        graphs = [snapshot, *snapshot.get("pipelines", {}).values()]
        labels = {n["id"]: n["label"] for graph in graphs for n in graph["nodes"]}
        stages = (
            await session.execute(
                select(RunStage).where(RunStage.run_id == run.id).order_by(RunStage.position)
            )
        ).scalars()
        results, results_cut = await self.node_results(session, run.execution_id, preview=True)
        execution_number = (
            None
            if run.execution_id is None
            else await session.scalar(
                select(Execution.number).where(Execution.id == run.execution_id)
            )
        )
        where = locate(snapshot, run.stage_id)
        nested = where["pipeline_id"] is not None
        return RunRead(
            id=run.id,
            task_id=run.task_id,
            root_pipeline_id=run.pipeline_id,
            root_pipeline_name=snapshot["name"],
            pipeline_id=where["pipeline_id"] or run.pipeline_id,
            pipeline_name=where["pipeline_name"],
            resume_stage_id=where["entry_id"],
            resume_action_id=None if nested else run.action_id,
            status=RunStatus(run.status),
            started_by=StartedBy(run.started_by),
            note=run.note,
            stage_id=run.stage_id,
            stage_name=labels.get(run.stage_id or ""),
            action_id=run.action_id,
            action_name=labels.get(run.action_id or ""),
            stages=[
                RunStageRead(id=s.stage_id, name=s.name, status=StageStatus(s.status))
                for s in stages
            ],
            node_results=results,
            node_results_truncated=results_cut,
            execution_id=run.execution_id,
            execution_number=execution_number,
            updated_at=run.updated_at,
        )

    @staticmethod
    async def node_results(
        session: AsyncSession, execution_id: str | None, *, preview: bool = False
    ) -> tuple[list[NodeResultRead], bool]:
        """The steps of the execution in order and whether older ones were left out.

        ``preview`` is what a run read carries: the last ``RUN_READ_RESULTS`` steps with long
        outputs cut. Without it: all steps, complete.
        """
        if execution_id is None:
            return [], False
        query = select(RunNodeResult).where(RunNodeResult.execution_id == execution_id)
        if not preview:
            rows = (await session.execute(query.order_by(RunNodeResult.seq))).scalars().all()
            return [NodeResultRead.of(row) for row in rows], False
        newest = (
            (
                await session.execute(
                    query.order_by(RunNodeResult.seq.desc()).limit(RUN_READ_RESULTS + 1)
                )
            )
            .scalars()
            .all()
        )
        cut = len(newest) > RUN_READ_RESULTS
        rows = list(reversed(newest[:RUN_READ_RESULTS]))
        return [NodeResultRead.of(row, preview=True) for row in rows], cut

    async def list_all(self, session: AsyncSession) -> list[RunRead]:
        """Every run."""
        runs = (await session.execute(select(PipelineRun))).scalars().all()
        return [await self.read(session, run) for run in runs]

    async def _publish(self, task_id: str) -> None:
        async with self._session() as session:
            run = await self._run_of(session, task_id)
            if run is not None:
                self._bus.publish(
                    "run.updated", (await self.read(session, run)).model_dump(mode="json")
                )

    @staticmethod
    async def _run_of(session: AsyncSession, task_id: str) -> PipelineRun | None:
        return await session.scalar(select(PipelineRun).where(PipelineRun.task_id == task_id))

    # ── starting and stopping ─────────────────────────────────────────

    async def start(
        self,
        task_id: str,
        pipeline_id: str,
        stage_id: str | None = None,
        action_id: str | None = None,
        started_by: StartedBy = StartedBy.USER,
    ) -> RunRead:
        """Start (or restart) the artifact in a pipeline, at a stage and action (default: the first).

        Stages before the starting stage count as done: those the artifact has passed keep that
        status, the others are marked ``skipped``.
        """
        # Everything up to the registration of the background task happens for one artifact at a time:
        # the check below runs before the first await, so a second start cannot slip in.
        if task_id in self._starting or task_id in self._jobs:
            raise ArtifactError(409, "The artifact is already being processed")
        if len(self._starting) + len(self._jobs) >= self._max_runs:
            raise ArtifactError(
                429, f"{self._max_runs} runs are active, the limit; try again later"
            )
        self._starting.add(task_id)
        try:
            return await self._start(task_id, pipeline_id, stage_id, action_id, started_by)
        finally:
            self._starting.discard(task_id)

    async def _start(
        self,
        task_id: str,
        pipeline_id: str,
        stage_id: str | None,
        action_id: str | None,
        started_by: StartedBy,
    ) -> RunRead:
        async with self._session() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise ArtifactError(404, "Artifact not found")
            run = await self._run_of(session, task_id)
            if run is not None and run.status == RunStatus.RUNNING:
                raise ArtifactError(409, "The artifact is already being processed")
            try:
                pipeline = await load_pipeline(session, pipeline_id)
                snapshot = await build_snapshot(session, pipeline)
                chain = pipeline_chain(snapshot["nodes"], snapshot["edges"])
                index, entry, first_action = pick_start(chain, stage_id, action_id)
            except (TargetError, NestingError) as error:
                raise ArtifactError(422, str(error)) from error

            run, previous = await self._claim(session, task_id, run, pipeline_id, started_by)
            # the artifact keeps what it was started with, so the next start offers the same
            at_action = first_action if entry["kind"] == NodeKind.STAGE else None
            task.pipeline_id, task.stage_id, task.action_id = pipeline_id, entry["id"], at_action
            run.pipeline_id = pipeline_id
            run.created_at = datetime.now(UTC)  # the row is reused: this is when this run began
            run.status = RunStatus.RUNNING
            run.started_by = started_by
            run.stage_id = entry["id"]
            run.action_id = at_action
            run.note = None
            run.snapshot = json.dumps(snapshot)
            await session.flush()
            changes = Changes()
            execution = await self.history.open(
                session,
                task,
                pipeline_id=pipeline_id,
                snapshot=snapshot,
                stage_id=entry["id"],
                action_id=at_action,
                started_by=started_by,
            )
            run.execution_id = execution.id
            changes.updated.append(ExecutionRead.of(execution))
            for i, stage in enumerate(chain):
                if i >= index:
                    state = StageStatus.PENDING
                elif previous.get(stage["id"]) == StageStatus.PASSED:
                    state = StageStatus.PASSED
                else:
                    state = StageStatus.SKIPPED
                session.add(
                    RunStage(
                        run_id=run.id,
                        stage_id=stage["id"],
                        name=stage["name"],
                        position=i,
                        status=state,
                    )
                )
            await self.history.prune(session, task, changes)
            await session.commit()
            result = await self.read(session, run)
            execution_id = execution.id
        self._bus.publish("run.updated", result.model_dump(mode="json"))
        self.history.publish(changes)
        self._jobs[task_id] = asyncio.create_task(self._execute(task_id, execution_id))
        return result

    async def _claim(
        self,
        session: AsyncSession,
        task_id: str,
        run: PipelineRun | None,
        pipeline_id: str,
        started_by: StartedBy,
    ) -> tuple[PipelineRun, dict[str, str]]:
        """Take the artifact's run row for a new start, and drop its stages.

        The database decides who starts first (a second server process included): the first run is
        inserted unless one exists, a restart changes a run that is not running. Returns the row and
        the status its stages had if it was a run of the same pipeline. The steps of the earlier
        executions stay: they belong to those executions.
        """
        existing = run is not None
        now = datetime.now(UTC)
        if run is None:
            claimed = await session.execute(
                insert(PipelineRun)
                .values(
                    id=str(uuid.uuid4()),
                    task_id=task_id,
                    pipeline_id=pipeline_id,
                    status=RunStatus.RUNNING,
                    started_by=started_by,
                    snapshot="{}",
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=["task_id"])
            )
            run = await self._run_of(session, task_id)
        else:
            claimed = await session.execute(
                update(PipelineRun)
                .where(PipelineRun.id == run.id, PipelineRun.status != RunStatus.RUNNING)
                .values(status=RunStatus.RUNNING)
            )
        if cast(CursorResult[Any], claimed).rowcount != 1 or run is None:
            raise ArtifactError(409, "The artifact is already being processed")
        previous: dict[str, str] = {}
        if existing:
            if run.pipeline_id == pipeline_id:
                rows = await session.execute(select(RunStage).where(RunStage.run_id == run.id))
                previous = {r.stage_id: r.status for r in rows.scalars()}
            await session.execute(delete(RunStage).where(RunStage.run_id == run.id))
        return run, previous

    async def stop(self, task_id: str) -> RunRead:
        """Stop a running artifact; it stays at its stage and action and can be started again."""
        if task_id in self._starting:
            raise ArtifactError(409, "The artifact is just being started")
        job = self._jobs.pop(task_id, None)
        if job is not None:
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
        async with self._session() as session:
            run = await self._run_of(session, task_id)
            if run is None or run.status != RunStatus.RUNNING:
                raise ArtifactError(409, "The artifact is not being processed")
            run.status = RunStatus.STOPPED
            run.note = "stopped"
            await self._pause_running_stages(session, run.id)
            changes = await self._close_execution(session, run)
            await session.commit()
            result = await self.read(session, run)
        self._bus.publish("run.updated", result.model_dump(mode="json"))
        self.history.publish(changes)
        return result

    async def recover(self) -> None:
        """After a restart no run is running any more; the ones that were are stopped.

        Code processes an earlier, hard-killed application left behind are ended first.
        """
        killed = await asyncio.to_thread(code_registry.cleanup_leftovers)
        logger.info("Cleaned up %d leftover code process(es)", killed)
        async with self._session() as session:
            runs = (
                (
                    await session.execute(
                        select(PipelineRun).where(PipelineRun.status == RunStatus.RUNNING)
                    )
                )
                .scalars()
                .all()
            )
            for run in runs:
                run.status = RunStatus.STOPPED
                run.note = "interrupted"
                await self._pause_running_stages(session, run.id)
                await self._close_execution(session, run)
            # executions that no run points to any more (a crash in between) are closed the same way
            await session.execute(
                update(Execution)
                .where(Execution.status == RunStatus.RUNNING)
                .values(status=RunStatus.STOPPED, note="interrupted", finished_at=utcnow())
            )
            await session.commit()

    async def _close_execution(self, session: AsyncSession, run: PipelineRun) -> Changes:
        """Bring the run's execution in line with the run, then apply the retention policy."""
        changes = Changes()
        await self.history.close(session, run, changes)
        task = await session.get(Task, run.task_id)
        if task is not None:
            await self.history.prune(session, task, changes)
        return changes

    @staticmethod
    async def _pause_running_stages(session: AsyncSession, run_id: str) -> None:
        """A stage that was running when its run stopped waits for the next start."""
        await session.execute(
            update(RunStage)
            .where(RunStage.run_id == run_id, RunStage.status == StageStatus.RUNNING)
            .values(status=StageStatus.PENDING)
        )

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
        status: RunStatus | None = None,
        stage_id: Any = _UNSET,
        action_id: Any = _UNSET,
        note: str | None = None,
        stage_state: tuple[str, StageStatus] | None = None,
    ) -> None:
        async with self._session() as session:
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
            changes = await self._close_execution(session, run) if status is not None else None
            await session.commit()
        if status in (RunStatus.DONE, RunStatus.FAILED):
            self._release(
                task_id
            )  # the run is over in the database: the artifact may start again now
        await self._publish(task_id)
        if changes is not None:
            self.history.publish(changes)

    def _release(self, task_id: str) -> None:
        """Forget the job of a run that is over, if the caller is that job.

        Without this the artifact stayed refused ("already being processed") for the few
        milliseconds that publishing the final events takes, although its status already says
        done or failed. A stopped run is removed by :meth:`stop`, not here.
        """
        if self._jobs.get(task_id) is asyncio.current_task():
            del self._jobs[task_id]

    async def _execute(self, task_id: str, execution_id: str) -> None:
        walk: _Walk | None = None
        try:
            async with self._session() as session:
                run = await self._run_of(session, task_id)
                if run is None:
                    return
                walk = _Walk(
                    task_id, execution_id, json.loads(run.snapshot), pipeline_id=run.pipeline_id
                )
                stage_id, action_id, run_pipeline = run.stage_id, run.action_id, run.pipeline_id
            chain = pipeline_chain(walk.snapshot["nodes"], walk.snapshot["edges"])
            start = next(i for i, s in enumerate(chain) if s["id"] == stage_id)
            await self._walk(walk, walk.snapshot, chain, start, action_id, 0, run_pipeline)
            # it rests where it ended, even inside a called pipeline
            await self._save(task_id, status=RunStatus.DONE)
        except asyncio.CancelledError:
            raise
        except _RunFailedError as failure:
            await self._fail(task_id, str(failure), walk)
        except Exception:
            logger.exception("Run of artifact %s failed", task_id)
            await self._fail(task_id, "Internal error", walk)
        finally:
            # a stopped run must not remove the bookkeeping of the run that replaced it
            self._release(task_id)

    async def _walk(
        self,
        walk: _Walk,
        graph: dict[str, Any],
        chain: list[dict[str, Any]],
        start: int,
        action_id: str | None,
        depth: int,
        pipeline_id: str | None,
    ) -> None:
        """Run the entries of a chain from ``start`` on; a pipeline node runs its pipeline the same way.

        Only the entries of the outermost pipeline have a status of their own (``run_stages``); inside
        a called pipeline the run shows the stage and action that are current.
        """
        top = depth == 0
        for entry in chain[start:]:
            if top:
                walk.top_entry = entry["id"]
            running = (entry["id"], StageStatus.RUNNING) if top else None
            if entry["kind"] == NodeKind.PIPELINE:
                called = walk.snapshot["pipelines"].get(entry["pipeline_id"] or "")
                if called is None:
                    raise _RunFailedError(f'"{entry["name"]}" has no pipeline chosen')
                await self._save(
                    walk.task_id, stage_id=entry["id"], action_id=None, stage_state=running
                )
                inner = pipeline_chain(called["nodes"], called["edges"])
                await self._walk(walk, called, inner, 0, None, depth + 1, entry["pipeline_id"])
            else:
                first = action_id or entry["first_action_id"]
                action_id = None
                walk.stage_id, walk.pipeline_id, walk.depth = entry["id"], pipeline_id, depth
                await self._save(
                    walk.task_id, stage_id=entry["id"], action_id=first, stage_state=running
                )
                await self._run_actions(walk, graph, first)
            if top:
                await self._save(walk.task_id, stage_state=(entry["id"], StageStatus.PASSED))

    async def _run_actions(self, walk: _Walk, graph: dict[str, Any], action: str | None) -> None:
        """Run the actions of a stage from ``action`` on, along *On Pass* / *On Error*, until the
        flow leaves the stage."""
        nodes = {n["id"]: n for n in graph["nodes"]}
        while action is not None:
            walk.step()
            node = nodes[action]
            walk.action_id = action
            await self._save(walk.task_id, action_id=action)
            passed = await self._run_action(node, walk)
            edge = edge_from(graph["edges"], action, Ports.PASS if passed else Ports.ERROR)
            if edge is None:
                raise _RunFailedError(
                    f'"{node["label"]}" has no On Pass connection'
                    if passed
                    else f'"{node["label"]}" failed'
                )
            target = nodes[edge["target_id"]]
            action = target["id"] if target["kind"] == NodeKind.ACTION else None

    async def _fail(self, task_id: str, note: str, walk: _Walk | None) -> None:
        async with self._session() as session:
            run = await self._run_of(session, task_id)
            current = run.stage_id if run else None
        top = (walk.top_entry if walk else None) or current
        await self._save(
            task_id,
            status=RunStatus.FAILED,
            note=note,
            stage_state=(top, StageStatus.FAILED) if top else None,
        )

    async def _run_action(self, node: dict[str, Any], walk: _Walk) -> bool:
        """Run an action's definition from its trigger: True for On Pass, False for On Fail.

        Every node on the way is recorded as a step of the run. A node that has an executor is run and
        leaves by the port of its outcome. An action that is not linked to a definition is an empty
        shell and passes at once (and has no steps).
        """
        if not node["definition_id"]:
            return True
        definition = walk.snapshot["definitions"][node["definition_id"]]
        nodes = {n["id"]: n for n in definition["nodes"]}
        current = next(n for n in definition["nodes"] if n["kind"] == NodeKind.TRIGGER)
        now = datetime.now(UTC)
        await self._record(walk, node["definition_id"], current, "pass", Ports.OUT, None, now)
        port = Ports.OUT
        while True:
            walk.step()
            edge = edge_from(definition["edges"], current["id"], port)
            if edge is None:
                return False  # a dead end: the action did not come to its output
            current = nodes[edge["target_id"]]
            started = datetime.now(UTC)
            if current["kind"] == NodeKind.OUTPUT:
                passed = edge["target_port"] == Ports.PASS
                outcome = "pass" if passed else "fail"
                await self._record(
                    walk, node["definition_id"], current, outcome, None, None, started
                )
                return bool(passed)
            executor = EXECUTORS.get(NodeKind(current["kind"]))
            if executor is None:
                port = Ports.OUT
                await self._record(
                    walk, node["definition_id"], current, "pass", port, None, started
                )
                continue
            result = await executor.run(current, self._limits)
            port = (
                (Ports.PASS if result.outcome == "pass" else Ports.FAIL)
                if executor.by_outcome
                else Ports.OUT
            )
            if port == Ports.FAIL and (current.get("config") or {}).get("on_failure") == "continue":
                port = (
                    Ports.PASS
                )  # fail open: the step keeps its failure and reason, the way on is On Pass
                result = replace(
                    result,
                    reason=f"{result.reason or 'The node failed'} (continued through On Pass)",
                )
            await self._record(
                walk, node["definition_id"], current, result.outcome, port, result, started
            )

    async def _record(
        self,
        walk: _Walk,
        definition_id: str,
        node: dict[str, Any],
        outcome: str,
        port: str | None,
        result: NodeResult | None,
        started: datetime,
    ) -> None:
        """Store one step of the run (never logged but as id, kind and outcome: the output may hold anything)."""
        logger.info(
            "Node %s (%s) of artifact %s: %s", node["id"], node["kind"], walk.task_id, outcome
        )
        walk.seq += 1
        output = result.output[:RESULT_OUTPUT_LIMIT_CHARS] if result else ""
        async with self._session() as session:
            run = await self._run_of(session, walk.task_id)
            if run is None:
                return
            session.add(
                RunNodeResult(
                    id=str(uuid.uuid4()),
                    run_id=run.id,
                    execution_id=walk.execution_id,
                    seq=walk.seq,
                    pipeline_id=walk.pipeline_id,
                    depth=walk.depth,
                    top_stage_id=walk.top_entry,
                    stage_id=walk.stage_id,
                    action_id=walk.action_id,
                    definition_id=definition_id,
                    node_id=node["id"],
                    node_name=node["name"],
                    kind=node["kind"],
                    outcome=outcome,
                    port=port,
                    exit_code=result.exit_code if result else None,
                    output=output,
                    reason=result.reason if result else None,
                    data=result.data if result else None,
                    started_at=started,
                    finished_at=datetime.now(UTC),
                )
            )
            await session.flush()
            await session.execute(
                update(Execution)
                .where(Execution.id == walk.execution_id)
                .values(step_count=Execution.step_count + 1)
            )
            if output and walk.execution_id is not None:
                await self._trim_outputs(session, walk.execution_id)
            await session.commit()
        if result is not None:  # the steps without output show up with the next save of the run
            await self._publish(walk.task_id)

    @staticmethod
    async def _trim_outputs(session: AsyncSession, execution_id: str) -> None:
        """Keep all outputs of the execution within ``RUN_OUTPUT_LIMIT_CHARS``: the oldest go first."""
        rows = (
            (
                await session.execute(
                    select(RunNodeResult)
                    .where(RunNodeResult.execution_id == execution_id)
                    .order_by(RunNodeResult.seq)
                )
            )
            .scalars()
            .all()
        )
        total = sum(len(r.output) for r in rows)
        for row in rows[:-1]:
            if total <= RUN_OUTPUT_LIMIT_CHARS:
                break
            total -= len(row.output) - len(REMOVED_OUTPUT)
            row.output = REMOVED_OUTPUT
        if (
            total > RUN_OUTPUT_LIMIT_CHARS
        ):  # the newest alone is too long (cannot be: it is bounded)
            rows[-1].output = rows[-1].output[:RUN_OUTPUT_LIMIT_CHARS]
