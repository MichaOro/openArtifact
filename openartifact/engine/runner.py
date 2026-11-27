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
import time
import uuid
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from functools import partial
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.activity import recorder as activity
from openartifact.artifact_fields.service import card_of
from openartifact.comments.schemas import Author
from openartifact.database import SessionOpener
from openartifact.engine import code_registry, dry_run, stop_switch
from openartifact.engine.chain import edge_from, locate, pipeline_chain
from openartifact.engine.context import (
    ContextError,
    NodeIndex,
    RunContext,
    RunView,
    bind_given,
    bind_inputs,
    build_outputs,
    check_card,
    depends_on_skipped,
)
from openartifact.engine.executors import EXECUTORS, Limits
from openartifact.engine.history import Changes, ExecutionHistory, utcnow
from openartifact.engine.limits import RunLimits, load_limits
from openartifact.engine.results import NodeResult
from openartifact.engine.retry import retry_of, tried
from openartifact.engine.schemas import ExecutionRead, NodeResultRead, RunRead, RunStageRead
from openartifact.engine.snapshot import NestingError, build_snapshot
from openartifact.engine.storage import StorageLimits, cut_detail, load_policy
from openartifact.engine.targets import TargetError, load_pipeline, pick_start
from openartifact.engine.telemetry import TelemetrySource
from openartifact.events import EventBus
from openartifact.exceptions import ArtifactError
from openartifact.graph import observe_state, preflight
from openartifact.graph.effects import writes
from openartifact.graph.node_types import FailureMode, Ports
from openartifact.guards.monitor import GuardSettings, Monitor, Verdict
from openartifact.models import (
    Execution,
    Graph,
    GuardAttachment,
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
OUTPUT_CUT_MARK = "[output truncated]"
#: The note of a run (and its execution) that was still running when the application restarted (``recover``, ADR-013).
INTERRUPTED_NOTE = "Interrupted by restart"
#: Steps a run read carries (the newest); ``results`` of the run has them all.
RUN_READ_RESULTS = 200
#: How a time limit in minutes becomes seconds (one place, so a test can make a minute short).
SECONDS_PER_MINUTE = 60
_UNSET: Any = object()
#: How long ``set_stop`` waits for starts that are on their way (they take milliseconds).
_START_WAIT_SECONDS = 10.0


def _declared(graph: Mapping[str, Any], kind: NodeKind, key: str) -> list[dict[str, Any]]:
    """The inputs (of its Trigger) or outputs (of its Output or Complete) an action or pipeline declares; ``[]`` when it declares none (ADR-083)."""
    for node in graph["nodes"]:
        if node["kind"] == kind:
            value = (node.get("config") or {}).get(key)
            return [dict(f) for f in value] if isinstance(value, list) else []
    return []


def _cut(result: NodeResult, limit: int | None = None) -> NodeResult:
    """``result`` with its output cut to the limit of a step (today's, or the user's lower one: ADR-084), marked in the text, the
    data and the reason."""
    limit = RESULT_OUTPUT_LIMIT_CHARS if limit is None else limit
    note = f"Note: the output was cut at {limit // 1024} Ki characters"
    return replace(
        result,
        output=result.output[: limit - len(OUTPUT_CUT_MARK) - 1] + f"\n{OUTPUT_CUT_MARK}",
        data={**(result.data or {}), "output_truncated": True},
        reason=f"{result.reason}; {note[6:]}" if result.reason else note,
    )


def _failed_message(node: Mapping[str, Any], reason: str) -> str:
    """Why a run stops at a failed action: its name and, when the last node said one, the reason."""
    base = f'"{node["label"]}" failed'
    return f"{base}: {reason}" if reason else base


def _node_failed(node: Mapping[str, Any], result: NodeResult) -> tuple[NodeResult, str]:
    """The result and the connector of a node that failed, by its setting *If the node fails* (ADR-061).

    Whatever the setting, the failure is data of the step (``data.error`` with the message, the setting's value and the
    node), so a later node and the run's view can read it. ``fail``: the way on is the (hidden) error output, which has no
    connection, so the action ends as failed; ``continue``: On Pass (fail open: the step keeps its failure and reason);
    ``error_output``: On Fail.
    """
    mode = (node.get("config") or {}).get("on_failure") or FailureMode.FAIL
    message = result.reason or "The node failed"
    error = {"message": message, "mode": mode, "node": node["name"]}
    data = {**(result.data or {}), "error": error}
    if mode == FailureMode.CONTINUE:
        return (
            replace(result, data=data, reason=f"{message} (continued through On Pass)"),
            Ports.PASS,
        )
    return replace(
        result, data=data
    ), Ports.FAIL  # error_output follows the connection, stop has none


class _RunFailedError(Exception):
    """The run cannot go on (shown as the note of a failed run)."""


class _ObservationEndedError(Exception):
    """An observed run (ADR-088) reached a node that needs what a skipped write would have produced: it cannot be observed any further, so
    the run ends there as done, with this text as its note. It is not a failure and it does not take On Fail."""


def _not_observable(name: str) -> _ObservationEndedError:
    return _ObservationEndedError(
        f"Observed up to '{name}': from there on the run needs what a skipped step would have produced, so it cannot be observed any further"
    )


class _RunPausedError(Exception):
    """A guard paused the run: it ends ``stopped`` with the reason as its note and can be started again."""


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
    #: The context of the execution (kept in ``executions.context``, written with every step).
    context: RunContext = field(default_factory=RunContext)
    index: NodeIndex = field(default_factory=NodeIndex)
    #: The limits the execution froze at its start (Settings > Run limits).
    limits: RunLimits = field(default_factory=RunLimits)
    #: What the execution stores of its steps, frozen at its start (the user's *Data storage* limits, ADR-084).
    storage: StorageLimits = field(default_factory=StorageLimits)
    #: The guards of the execution (ADR-060) and the path of pipeline nodes that leads to where the walk is.
    monitor: Monitor | None = None
    path: str = ""
    #: What an interval guard decided while the flow ran (the job was cancelled for it).
    interrupt: Verdict | None = None
    #: The outputs the Output node of the action definition that just ended handed back (ADR-083); ``None`` when it declares none.
    outputs: dict[str, Any] | None = None
    #: The run is a dry run (ADR-086): what writes is skipped, a timer does not wait, the tools of an agent that change something answer
    #: that it was a dry run.
    dry_run: bool = False
    #: The run was started by the observe mode of its pipeline (ADR-088): also a dry run; a node that waits for a skipped write ends it as done.
    observed: bool = False
    #: The values given at the start for the inputs of the entry action (``{"action_id", "values"}``, already checked), used once.
    entry_inputs: dict[str, Any] | None = None

    def step(self) -> None:
        """Count a step; actions and the nodes of their definitions count against the same limit, so a
        pipeline that loops for ever fails instead of running for ever."""
        self.steps += 1
        if self.steps > self.limits.max_steps:
            raise _RunFailedError(
                f"The pipeline does not come to an end: more than {self.limits.max_steps} steps "
                "(Settings > Run limits)"
            )


class _GuardHooks:
    """What the engine does for the guard monitor of one execution."""

    def __init__(self, engine: RunEngine, walk: _Walk) -> None:
        self._engine = engine
        self._walk = walk

    async def run_body(
        self, guard: Mapping[str, Any], facts: Mapping[str, Any]
    ) -> tuple[bool, str]:
        """The guard's own action, as a child of the run: a copy of the run's context with the facts as
        ``${var.guard_*}``; what it does to that copy is not kept."""
        walk = self._walk
        definition_id = str(guard.get("definition_id") or "")
        definition = walk.snapshot.get("guard_definitions", {}).get(definition_id)
        if definition is None:
            raise RuntimeError("the guard has no action to run")
        context = RunContext.loads(walk.context.dumps())
        inputs: dict[str, Any] = {"guard_name": str(guard.get("name", ""))}
        for key, value in facts.items():
            if key.startswith("var."):
                continue
            name = "guard_firing" if key == "guard.runs" else f"guard_{key.replace('.', '_')}"
            inputs[name] = value
        # where the guard looks (a SQLite node of the guard action reads the run through these, ADR-068)
        inputs["guard_execution"] = walk.execution_id or ""
        inputs["guard_task"] = walk.task_id
        context.set_vars(inputs)
        view = RunView(
            context,
            NodeIndex.of_graphs([definition]),
            walk.task_id,
            walk.execution_id,
            walk.dry_run,
        )
        return await self._engine._run_definition(definition_id, definition, walk, view)

    async def interrupt(self, verdict: Verdict) -> None:
        self._walk.interrupt = verdict
        job = self._engine._jobs.get(self._walk.task_id)
        if job is not None and not job.done():
            job.cancel()

    async def fired(self, firing: Mapping[str, Any], state: str) -> None:
        """An activity entry of the artifact (kind ``guard``, the guard as the actor, the facts) and the state."""
        walk = self._walk
        data = {k: v for k, v in firing.items() if k not in ("at", "scope_id")}
        async with self._engine._session() as session:
            entry = await activity.record(
                session,
                walk.task_id,
                "guard",
                Author("system", str(firing["guard"])),
                data,
                execution_id=walk.execution_id,
            )
            if walk.execution_id is not None:
                await session.execute(
                    update(Execution)
                    .where(Execution.id == walk.execution_id)
                    .values(guard_state=state)
                )
            await session.commit()
        self._engine._bus.publish("activity.created", entry.model_dump(mode="json"))
        self._engine._bus.publish(
            "guard.fired", {"task_id": walk.task_id, "execution_id": walk.execution_id, **firing}
        )

    async def persist(self, state: str) -> None:
        await self._engine._store_guard_state(self._walk.execution_id, state)


class RunEngine:
    """Starts, stops and executes runs."""

    def __init__(
        self,
        bus: EventBus,
        session: SessionOpener,
        max_runs: int = 8,
        limits: Limits | None = None,
        history_default_keep: int = 50,
        guards: GuardSettings | None = None,
        telemetry: TelemetrySource | None = None,
    ) -> None:
        self._bus = bus
        #: What the agents of a running execution do (the ``agent.*`` facts of the guards); ``None``: nothing is known.
        self._telemetry = telemetry
        self.history = ExecutionHistory(bus, history_default_keep)
        self._session = session
        self._max_runs = max_runs
        self._limits = limits or Limits()
        # artifacts whose start has not reached its background task
        self._starting: set[str] = set()
        self._jobs: dict[str, asyncio.Task[None]] = {}
        #: The emergency stop (ADR-076) as this process last saw it: no execution starts while it is on.
        self._stopped = False
        self.guard_settings = guards or GuardSettings()
        #: The guard monitor of every execution that runs, by execution id (heartbeats, previews).
        self.monitors: dict[str, tuple[str, Monitor]] = {}

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
        execution_number, context_size = None, 0
        if run.execution_id is not None:
            row = (
                await session.execute(
                    select(Execution.number, func.length(Execution.context)).where(
                        Execution.id == run.execution_id
                    )
                )
            ).one_or_none()
            if row is not None:
                execution_number, context_size = row[0], row[1] or 0
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
            dry_run=bool(run.dry_run),
            observed=bool(run.observed),
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
            context_size=context_size,
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
        *,
        dry_run: bool = False,
        inputs: Mapping[str, Any] | None = None,
        version: str | None = None,
    ) -> RunRead:
        """Start (or restart) the artifact in a pipeline, at a stage and action (default: the first).

        Stages before the starting stage count as done: those the artifact has passed keep that
        status, the others are marked ``skipped``.

        ``dry_run`` (ADR-086): a run under real conditions that skips what writes; it leaves the artifact's own target (pipeline, stage,
        action) as it is. ``version`` (``draft`` or ``published``, dry runs only) says which version of the graphs it freezes:
        ``None`` is the published one. ``inputs`` are values for the declared inputs of the entry: the action's when ``action_id`` is
        given, else the pipeline's own (dry runs only).
        """
        if not dry_run and (inputs is not None or version is not None):
            raise ArtifactError(422, "inputs and version are for a dry run")
        if version not in (None, "draft", "published"):
            raise ArtifactError(422, "version is draft or published")
        # Everything up to the registration of the background task happens for one artifact at a time:
        # the check below runs before the first await, so a second start cannot slip in.
        if self._stopped:
            raise ArtifactError(409, stop_switch.MESSAGE, stop_switch.CODE)
        if task_id in self._starting or task_id in self._jobs:
            raise ArtifactError(409, "The artifact is already being processed")
        if len(self._starting) + len(self._jobs) >= self._max_runs:
            raise ArtifactError(
                429, f"{self._max_runs} runs are active, the limit; try again later"
            )
        self._starting.add(task_id)
        try:
            return await self._start(
                task_id, pipeline_id, stage_id, action_id, started_by, dry_run, inputs, version
            )
        finally:
            self._starting.discard(task_id)

    async def _start(
        self,
        task_id: str,
        pipeline_id: str,
        stage_id: str | None,
        action_id: str | None,
        started_by: StartedBy,
        dry_run: bool = False,
        inputs: Mapping[str, Any] | None = None,
        version: str | None = None,
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
                snapshot = await build_snapshot(session, pipeline, draft=version == "draft")
                snapshot["limits"] = (await load_limits(session))[
                    0
                ].to_data()  # frozen for this run
                snapshot["storage"] = (await load_policy(session)).limits().to_data()
                chain = pipeline_chain(snapshot["nodes"], snapshot["edges"])
                index, entry, first_action = pick_start(chain, stage_id, action_id)
            except (TargetError, NestingError) as error:
                raise ArtifactError(422, str(error)) from error
            start_inputs: dict[str, Any] | None = None
            if inputs is not None:
                start_inputs = self._entry_inputs(snapshot, inputs, action_id)

            observed = False
            if not dry_run:  # a start that is not a manual dry run is observed when the pipeline's published version says so (ADR-088)
                graph = await session.get(Graph, pipeline_id)
                if graph is not None:
                    observed = await observe_state.admit(session, graph)
            dry_run = dry_run or observed  # an observed run is a dry run nobody asked for by hand
            if observed:
                snapshot["observed"] = True

            card = await card_of(session, task)
            try:
                check_card(card)  # a card too large for a run is refused here, not cut
            except ContextError as error:
                raise ArtifactError(422, str(error)) from error

            run, previous = await self._claim(session, task_id, run, pipeline_id, started_by)
            if run.dry_run:
                previous = {}  # the stage states of a dry run say nothing about what the artifact has passed
            # the artifact keeps what it was started with, so the next start offers the same; a dry run leaves it as it is
            at_action = first_action if entry["kind"] == NodeKind.STAGE else None
            if not dry_run:
                task.pipeline_id, task.stage_id, task.action_id = (
                    pipeline_id,
                    entry["id"],
                    at_action,
                )
            run.dry_run = dry_run
            run.observed = observed
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
                context=RunContext({"card": dict(card), "inputs": start_inputs})
                if start_inputs and action_id is None
                else RunContext.initial(card),
                dry_run=dry_run,
                observed=observed,
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
            await self.history.apply_rules(session, changes)
            # The last word before the run is real: STOP (ADR-076) is read in this very transaction, so a start that is
            # on its way when the switch goes on either sees it here (nothing is written) or is a run that the switch
            # aborts, because ``set_stop`` waits for the starts on their way before it looks for runs.
            if self._stopped or (await stop_switch.load(session))[0]:
                raise ArtifactError(409, stop_switch.MESSAGE, stop_switch.CODE)
            await session.commit()
            result = await self.read(session, run)
            execution_id = execution.id
        self._bus.publish("run.updated", result.model_dump(mode="json"))
        self.history.publish(changes)
        self._jobs[task_id] = asyncio.create_task(self._execute(task_id, execution_id))
        return result

    async def check_start(
        self,
        task_id: str,
        pipeline_id: str,
        stage_id: str | None = None,
        action_id: str | None = None,
        inputs: Mapping[str, Any] | None = None,
        version: str | None = None,
    ) -> list[str]:
        """What would refuse a dry run started like this, in plain words (empty: nothing found). Reads only and starts nothing: the same
        build of the snapshot, the same choice of the start, the same check of the inputs as :meth:`start`, and for the draft the check
        before publishing (ADR-082) of every graph the run would use, so the editor can say it before the click (ADR-086)."""
        if version not in (None, "draft", "published"):
            return ["version is draft or published"]
        async with self._session() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise ArtifactError(404, "Artifact not found")
            try:
                pipeline = await load_pipeline(session, pipeline_id)
                snapshot = await build_snapshot(session, pipeline, draft=version == "draft")
                chain = pipeline_chain(snapshot["nodes"], snapshot["edges"])
                pick_start(chain, stage_id, action_id)
            except (TargetError, NestingError) as error:
                return [str(error)]
            found: list[str] = []
            if inputs is not None:
                try:
                    self._entry_inputs(snapshot, inputs, action_id)
                except ArtifactError as error:
                    found.append(error.message)
            try:
                check_card(await card_of(session, task))
            except ContextError as error:
                found.append(str(error))
            if version == "draft":
                used = [pipeline_id, *snapshot["definitions"], *snapshot["pipelines"]]
                for graph_id in dict.fromkeys(used):
                    for finding in await preflight.check(session, graph_id):
                        # the values given for the entry action stand in for what its placement maps (they are checked above)
                        given = finding.code == "input_not_given" and finding.node_id == action_id
                        if finding.level == "error" and not (given and inputs is not None):
                            found.append(f"{finding.node_name}: {finding.message}")
            return found

    @staticmethod
    def _entry_inputs(
        snapshot: dict[str, Any], inputs: Mapping[str, Any], action_id: str | None
    ) -> dict[str, Any]:
        """The values a dry run was given for the inputs of its entry, checked like a mapping (ADR-086, ADR-083): of the action it starts at
        when one is named (kept in the snapshot, used by that action once), else of the pipeline's own Trigger (returned, they become the
        inputs of the context). 422 when the entry declares no inputs, a name is unknown, a required input is missing or a value does not fit."""
        try:
            if action_id is not None:
                node = next((n for n in snapshot["nodes"] if n["id"] == action_id), None)
                definition = snapshot["definitions"].get((node or {}).get("definition_id") or "")
                if definition is None:
                    raise ContextError("that action has no definition to give inputs to")
                declared = _declared(definition, NodeKind.TRIGGER, "inputs")
                if not declared:
                    raise ContextError(f"{definition['name']} declares no inputs")
                bound = bind_given(definition["name"], declared, inputs)
                snapshot["entry_inputs"] = {"action_id": action_id, "values": bound}
                return bound
            declared = _declared(snapshot, NodeKind.TRIGGER, "inputs")
            if not declared:
                raise ContextError(f"{snapshot['name']} declares no inputs")
            return bind_given(snapshot["name"], declared, inputs)
        except ContextError as error:
            raise ArtifactError(422, str(error)) from error

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

    async def stop(self, task_id: str, note: str = "stopped") -> RunRead:
        """Stop a running artifact; it stays at its stage and action and can be started again.

        ``note`` is what the run and its execution say about the end (the emergency stop gives its own).
        """
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
            run.note = note
            await self._pause_running_stages(session, run.id)
            changes = await self._close_execution(session, run)
            await session.commit()
            result = await self.read(session, run)
        self._bus.publish("run.updated", result.model_dump(mode="json"))
        self.history.publish(changes)
        return result

    # ── the emergency stop (ADR-076) ─────────────────────────────────────

    async def stop_active(self) -> bool:
        """Whether the emergency stop is on (read from the database; this also refreshes what the process remembers)."""
        async with self._session() as session:
            self._stopped = (await stop_switch.load(session))[0]
        return self._stopped

    async def running_count(self) -> int:
        """How many executions run now."""
        async with self._session() as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(PipelineRun)
                    .where(PipelineRun.status == RunStatus.RUNNING)
                )
                or 0
            )

    async def set_stop(self, active: bool) -> int:
        """Switch the emergency stop on or off; on: abort every execution that runs. Returns how many were aborted.

        Order matters for the race with a start that is on its way: the state is written first, then the process
        remembers it, then the starts that have not finished are waited for (each of them either refuses itself or
        has registered its run), and only then the runs are looked for and stopped.
        """
        async with self._session() as session:
            await stop_switch.store(session, active, utcnow())
            await session.commit()
        self._stopped = active
        if not active:
            return 0
        deadline = time.monotonic() + _START_WAIT_SECONDS
        while self._starting and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        async with self._session() as session:
            running = set(
                (
                    await session.execute(
                        select(PipelineRun.task_id).where(PipelineRun.status == RunStatus.RUNNING)
                    )
                ).scalars()
            )
        aborted = 0
        for task_id in sorted(running | set(self._jobs)):
            try:
                await self.stop(task_id, note=stop_switch.NOTE)
                aborted += 1
            except ArtifactError:  # it ended by itself in the meantime
                continue
        return aborted

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
                run.note = INTERRUPTED_NOTE
                await self._pause_running_stages(session, run.id)
                await self._close_execution(session, run)
            # executions that no run points to any more (a crash in between) are closed the same way
            await session.execute(
                update(Execution)
                .where(Execution.status == RunStatus.RUNNING)
                .values(status=RunStatus.STOPPED, note=INTERRUPTED_NOTE, finished_at=utcnow())
            )
            await session.commit()
        await (
            self.stop_active()
        )  # STOP survives the restart: the switch stays on until somebody switches it off

    async def _close_execution(self, session: AsyncSession, run: PipelineRun) -> Changes:
        """Bring the run's execution in line with the run, then apply the retention policy."""
        changes = Changes()
        await self.history.close(session, run, changes)
        task = await session.get(Task, run.task_id)
        if task is not None:
            await self.history.prune(session, task, changes)
        await self.history.apply_rules(session, changes)
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

    # ── guards (ADR-060) ──────────────────────────────────────────────

    def _monitor(self, walk: _Walk) -> Monitor:
        """The guard monitor of an execution: the frozen guards, the engine's effects, the run's variables."""

        async def enabled(guard_id: str) -> bool:
            async with self._session() as session:
                return bool(
                    await session.scalar(
                        select(GuardAttachment.enabled).where(GuardAttachment.id == guard_id)
                    )
                )

        async def board() -> dict[str, int]:
            """The artifacts in each lane (``lane.<lane>`` facts): looked up only when a guard's condition names one."""
            async with self._session() as session:
                rows = await session.execute(
                    select(Task.status, func.count()).group_by(Task.status)
                )
                return {f"lane.{status}": count for status, count in rows}

        telemetry = self._telemetry
        return Monitor(
            list(walk.snapshot.get("guards", [])),
            _GuardHooks(self, walk),
            self.guard_settings,
            variables=lambda: walk.context.vars,
            enabled=enabled,
            agent=(lambda: telemetry.facts(walk.execution_id)) if telemetry else dict,
            board=board,
        )

    @staticmethod
    async def _guarded(verdict_of: Awaitable[Verdict]) -> None:
        """Wait for the guards of an event in the flow and do what they decided."""
        verdict = await verdict_of
        if verdict.kind == "pause":
            raise _RunPausedError(verdict.note)
        if verdict.kind == "abort":
            raise _RunFailedError(verdict.note)

    async def _pause(self, task_id: str, note: str) -> None:
        """A guard paused the run: it is stopped with the reason and stays where it is, to be started again."""
        async with self._session() as session:
            run = await self._run_of(session, task_id)
            if run is None:
                return
            run.status = RunStatus.STOPPED
            run.note = note
            await self._pause_running_stages(session, run.id)
            changes = await self._close_execution(session, run)
            await session.commit()
        await self._publish(task_id)
        self.history.publish(changes)

    async def heartbeat(self, execution_id: str, note: str | None) -> dict[str, Any]:
        """An agent or tool says the execution still makes progress: its stall clock starts again (ADR-060)."""
        held = self.monitors.get(execution_id)
        if held is None:
            async with self._session() as session:
                found = await session.scalar(
                    select(Execution.status).where(Execution.id == execution_id)
                )
            if found is None:
                raise ArtifactError(404, "Execution not found")
            if found != RunStatus.RUNNING:
                raise ArtifactError(409, "The execution is not running")
            # it has just started and its guards are not watching yet: nothing to restart
            return {"execution_id": execution_id, "at": utcnow(), "count": 0}
        _, monitor = held
        last = (monitor.heartbeat or {}).get("at")
        spacing = self.guard_settings.heartbeat_spacing_seconds
        if last and (utcnow() - datetime.fromisoformat(last)).total_seconds() < spacing:
            raise ArtifactError(429, f"At most one heartbeat per {spacing:g} s")
        monitor.progress(note, heartbeat=True)
        await self._store_guard_state(execution_id, monitor.dump())
        heartbeat = monitor.heartbeat or {}
        return {"execution_id": execution_id, "at": heartbeat["at"], "count": heartbeat["count"]}

    async def _store_guard_state(self, execution_id: str | None, state: str) -> None:
        if execution_id is None:
            return
        async with self._session() as session:
            await session.execute(
                update(Execution).where(Execution.id == execution_id).values(guard_state=state)
            )
            await session.commit()

    def preview_guard(self, guard: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
        """Which running scopes a guard would fire on now (its condition only): how many run, and the matches."""
        from openartifact.guards.schemas import GuardGroup
        from openartifact.rules import tree

        when = GuardGroup.model_validate(guard["when"])
        running, matches = 0, []
        for execution_id, (task_id, monitor) in list(self.monitors.items()):
            for scope in monitor.active():
                if scope.type != guard["scope_type"] or scope.id != guard.get("scope_id"):
                    continue
                running += 1
                facts = monitor.facts(scope)
                count = monitor.counts.get(f"{guard.get('id') or ''}|{scope.key}")
                facts["guard.runs"] = count.runs if count else 0
                if tree.evaluate(when, facts):
                    matches.append(
                        {
                            "task_id": task_id,
                            "execution_id": execution_id,
                            "scope_name": scope.name,
                            "facts": facts,
                        }
                    )
        return running, matches

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
                walk.limits = RunLimits.of_snapshot(walk.snapshot)
                walk.storage = StorageLimits.of_snapshot(walk.snapshot)
                walk.dry_run = bool(run.dry_run)
                walk.observed = bool(run.observed)
                walk.entry_inputs = walk.snapshot.get("entry_inputs")
                stage_id, action_id, run_pipeline = run.stage_id, run.action_id, run.pipeline_id
                walk.context = RunContext.loads(
                    await session.scalar(
                        select(Execution.context).where(Execution.id == execution_id)
                    )
                )
                walk.index = NodeIndex.of_snapshot(walk.snapshot)
            walk.monitor = self._monitor(walk)
            self.monitors[execution_id] = (task_id, walk.monitor)
            chain = pipeline_chain(walk.snapshot["nodes"], walk.snapshot["edges"])
            start = next(i for i, s in enumerate(chain) if s["id"] == stage_id)
            minutes = walk.limits.time_limit_minutes
            deadline = asyncio.timeout(minutes * SECONDS_PER_MINUTE if minutes else None)
            try:
                async with (
                    deadline
                ):  # when it expires, the running node is cancelled like a stopped run's
                    root = walk.snapshot
                    await self._guarded(walk.monitor.enter("pipeline", root["id"], root["name"]))
                    await self._walk(walk, walk.snapshot, chain, start, action_id, 0, run_pipeline)
                    await self._guarded(walk.monitor.leave("pipeline", root["id"]))
            except TimeoutError:
                if not deadline.expired():
                    raise  # a timeout of something inside, not the run's: the handler below decides
                raise _RunFailedError(
                    f"The execution took longer than its time limit of {minutes} minutes "
                    "(Settings > Run limits)"
                ) from None
            # it rests where it ended, even inside a called pipeline
            await self._save(task_id, status=RunStatus.DONE)
        except asyncio.CancelledError:
            interrupt = walk.interrupt if walk else None
            current = asyncio.current_task()
            if interrupt is None or current is None:
                raise
            current.uncancel()  # an interval guard stopped the running node: the run ends as it decided
            if interrupt.kind == "pause":
                await self._pause(task_id, interrupt.note)
            else:
                await self._fail(task_id, interrupt.note, walk)
        except (
            _ObservationEndedError
        ) as end:  # not a failure: what could be observed was observed (ADR-088)
            await self._save(task_id, status=RunStatus.DONE, note=str(end))
        except _RunPausedError as paused:
            await self._pause(task_id, str(paused))
        except _RunFailedError as failure:
            if walk is not None and walk.monitor is not None:
                await walk.monitor.fail()
            await self._fail(task_id, str(failure), walk)
        except Exception:
            logger.exception("Run of artifact %s failed", task_id)
            await self._fail(task_id, "Internal error", walk)
        finally:
            if walk is not None and walk.monitor is not None:
                await walk.monitor.close()
            self.monitors.pop(execution_id, None)
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
                await self._check_called_observation(entry["pipeline_id"])
                inner = pipeline_chain(called["nodes"], called["edges"])
                outer, walk.path = walk.path, f"{walk.path}/{entry['id']}"
                monitor = cast(Monitor, walk.monitor)
                await self._guarded(
                    monitor.enter("pipeline", called["id"], called["name"], walk.path)
                )
                await self._walk_called(walk, graph, entry, called, inner, depth)
                await self._guarded(monitor.leave("pipeline", called["id"], walk.path))
                walk.path = outer
            else:
                first = action_id or entry["first_action_id"]
                action_id = None
                walk.stage_id, walk.pipeline_id, walk.depth = entry["id"], pipeline_id, depth
                await self._save(
                    walk.task_id, stage_id=entry["id"], action_id=first, stage_state=running
                )
                monitor = cast(Monitor, walk.monitor)
                await self._guarded(monitor.enter("stage", entry["id"], entry["name"], walk.path))
                await self._run_actions(walk, graph, first, entry)
                await self._guarded(monitor.leave("stage", entry["id"], walk.path))
            if top:
                await self._save(walk.task_id, stage_state=(entry["id"], StageStatus.PASSED))

    async def _check_called_observation(self, pipeline_id: str | None) -> None:
        """A called pipeline whose observation has ended waits for the owner's decision like a start does (ADR-088): the call fails with that
        reason. Its own mode is not read otherwise: a called pipeline follows the run that calls it."""
        if not pipeline_id:
            return
        async with self._session() as session:
            graph = await session.get(Graph, pipeline_id)
            if graph is None:
                return
            setting = await observe_state.published_setting(session, graph)
            found = observe_state.status_of(graph, setting) if setting is not None else None
        if found is not None and found["ended"]:
            raise _RunFailedError(str(found["reason"]))

    async def _walk_called(
        self,
        walk: _Walk,
        graph: dict[str, Any],
        entry: dict[str, Any],
        called: dict[str, Any],
        inner: list[dict[str, Any]],
        depth: int,
    ) -> None:
        """Run a called pipeline (ADR-083): with a contract its inputs are the ones the pipeline node maps, its Complete's outputs are the
        result of the pipeline node; without one it is walked as it always was."""
        declared_in = _declared(called, NodeKind.TRIGGER, "inputs")
        declared_out = _declared(called, NodeKind.COMPLETE, "outputs")
        if not declared_in and not declared_out:
            await self._walk(walk, called, inner, 0, None, depth + 1, entry["pipeline_id"])
            return
        node = next((n for n in graph["nodes"] if n["id"] == entry["id"]), entry)
        view = RunView(walk.context, walk.index, walk.task_id, walk.execution_id, walk.dry_run)
        try:
            bound = bind_inputs(node, called["name"], declared_in, view)
        except ContextError as error:
            if walk.observed and depends_on_skipped(str(error)):
                raise _not_observable(node["name"]) from error
            await self._place_result(walk, node, False, str(error), None)
            raise _RunFailedError(str(error)) from error
        earlier, walk.context.inputs = walk.context.inputs, bound
        try:
            await self._walk(walk, called, inner, 0, None, depth + 1, entry["pipeline_id"])
            outputs = build_outputs(
                declared_out, view
            )  # where the pipeline ends, with its own inputs
        except ContextError as error:
            if walk.observed and depends_on_skipped(str(error)):
                raise _not_observable(node["name"]) from error
            await self._place_result(walk, node, False, str(error), None)
            raise _RunFailedError(str(error)) from error
        finally:
            walk.context.inputs = earlier
        await self._place_result(walk, node, True, "", outputs)

    async def _run_actions(
        self,
        walk: _Walk,
        graph: dict[str, Any],
        action: str | None,
        stage: dict[str, Any] | None = None,
    ) -> None:
        """Run the actions of a stage from ``action`` on, along *On Pass* / *On Error*, until the
        flow leaves the stage. A loop back to the stage's entry action enters the stage again (its guards
        count a round)."""
        nodes = {n["id"]: n for n in graph["nodes"]}
        monitor = cast(Monitor, walk.monitor)
        first = True
        while action is not None:
            walk.step()
            node = nodes[action]
            if stage is not None and not first and action == stage.get("first_action_id"):
                await self._guarded(monitor.enter("stage", stage["id"], stage["name"], walk.path))
            first = False
            walk.action_id = action
            await self._save(walk.task_id, action_id=action)
            await self._guarded(monitor.enter("action", action, node["label"], walk.path))
            # the guards of the action's definition watch it wherever it is used: their counters are keyed by the
            # action node that runs it (the path), so two stages that use one definition count apart
            definition_id = node.get("definition_id")
            inside = f"{walk.path}>{action}"
            watched = bool(definition_id) and monitor.watches("definition", str(definition_id))
            if watched:
                await self._guarded(
                    monitor.enter("definition", str(definition_id), node["label"], inside)
                )
            (passed, reason), earlier = await tried(
                partial(self._run_action, node, walk),
                lambda r: None if r[0] else (r[1] or "The action failed"),
                retry_of(node) if node.get("definition_id") else None,  # Retry on fail (ADR-073)
            )
            if earlier and not passed:
                reason = (
                    f"{reason} (after {len(earlier) + 1} tries)"
                    if reason
                    else f"after {len(earlier) + 1} tries"
                )
            await self._guarded(
                monitor.ended(action, passed, str(definition_id) if watched else None)
            )
            if watched:
                await self._guarded(monitor.leave("definition", str(definition_id), inside))
            await self._guarded(monitor.leave("action", action, walk.path))
            port = Ports.PASS
            if not passed:
                port = self._action_failed(node, reason, walk)
            edge = edge_from(graph["edges"], action, port)
            if edge is None:
                raise _RunFailedError(
                    f'"{node["label"]}" has no On Pass connection'
                    if port == Ports.PASS
                    else _failed_message(node, reason)
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

    async def _run_action(self, node: dict[str, Any], walk: _Walk) -> tuple[bool, str]:
        """Run an action's definition from its trigger: (passed, the reason of the last node).

        Every node on the way is recorded as a step of the run. A node that has an executor is run and
        leaves by the port of its outcome (or by the port it chose itself). An action that is not linked to a definition is an empty
        shell and passes at once (and has no steps).
        """
        if not node["definition_id"]:
            return True, ""
        definition = walk.snapshot["definitions"][node["definition_id"]]
        declared_in = _declared(definition, NodeKind.TRIGGER, "inputs")
        declared_out = _declared(definition, NodeKind.OUTPUT, "outputs")
        if (
            not declared_in and not declared_out
        ):  # no contract: the nodes read the run context as before
            return await self._run_definition(node["definition_id"], definition, walk, None)
        view = RunView(walk.context, walk.index, walk.task_id, walk.execution_id, walk.dry_run)
        try:
            given = walk.entry_inputs
            if given is not None and given["action_id"] == node["id"]:
                bound = dict(
                    given["values"]
                )  # a dry run's own values for the entry action, used once
                walk.entry_inputs = None
            else:
                bound = bind_inputs(node, definition["name"], declared_in, view)
        except ContextError as error:
            if walk.observed and depends_on_skipped(str(error)):
                raise _not_observable(node["name"]) from error
            await self._place_result(walk, node, False, str(error), None)
            return False, str(error)
        earlier, walk.context.inputs, walk.outputs = walk.context.inputs, bound, None
        try:
            passed, reason = await self._run_definition(
                node["definition_id"], definition, walk, None
            )
            outputs = walk.outputs if passed else None
        finally:
            walk.context.inputs, walk.outputs = earlier, None
        await self._place_result(walk, node, passed, reason, outputs)
        return passed, reason

    async def _place_result(
        self,
        walk: _Walk,
        node: dict[str, Any],
        passed: bool,
        reason: str,
        outputs: dict[str, Any] | None,
    ) -> None:
        """Store the result of an action node that runs a definition with a contract (ADR-083): its outputs are the ``data``, read by the
        node's id (``${node:ID.data.name}``); the context is written at once, a later step may be far away."""
        result = NodeResult(
            "pass" if passed else "fail", reason=None if passed else (reason or None), data=outputs
        )
        walk.context.record(node, result, Ports.PASS if passed else Ports.FAIL)
        if walk.execution_id is not None:
            async with self._session() as session:
                await session.execute(
                    update(Execution)
                    .where(Execution.id == walk.execution_id)
                    .values(context=walk.context.dumps())
                )
                await session.commit()

    def _action_failed(self, node: dict[str, Any], reason: str, walk: _Walk) -> str:
        """The connector a failed action leaves by, by its setting *If the action fails* (ADR-061): ``fail`` stops the
        run (a failure is raised), ``continue`` goes on through On Pass, ``error_output`` through On Error. The failure is kept
        in the run context as the action's data (``${(Action).data.error}``) except when the run stops."""
        mode = (node.get("config") or {}).get("on_failure") or FailureMode.FAIL
        if mode == FailureMode.FAIL:
            raise _RunFailedError(_failed_message(node, reason))
        port = Ports.PASS if mode == FailureMode.CONTINUE else Ports.ERROR
        error = {"message": reason or "The action failed", "mode": mode, "node": node["name"]}
        walk.context.record(node, NodeResult("fail", reason=reason, data={"error": error}), port)
        return port

    async def _run_definition(
        self,
        definition_id: str,
        definition: dict[str, Any],
        walk: _Walk,
        view: RunView | None,
    ) -> tuple[bool, str]:
        """Walk an action definition from its trigger to its output: (passed, the reason of the last node).

        With ``view`` it is a guard's own action (ADR-060): it reads and writes that view's context, its steps are not
        recorded and count against a limit of their own, not the run's."""
        record = view is None
        run_view = view or RunView(
            walk.context, walk.index, walk.task_id, walk.execution_id, walk.dry_run
        )
        nodes = {n["id"]: n for n in definition["nodes"]}
        current = next(n for n in definition["nodes"] if n["kind"] == NodeKind.TRIGGER)
        now = datetime.now(UTC)
        if record:
            await self._record(walk, definition_id, current, "pass", Ports.OUT, None, now)
        port = Ports.OUT
        reason = ""
        own_steps = 0
        while True:
            if record:
                walk.step()
            else:
                own_steps += 1
                if own_steps > walk.limits.max_steps:
                    raise RuntimeError(
                        f"the guard's action took more than {walk.limits.max_steps} steps"
                    )
            edge = edge_from(definition["edges"], current["id"], port)
            if edge is None:
                return False, reason  # a dead end: the action did not come to its output
            current = nodes[edge["target_id"]]
            started = datetime.now(UTC)
            if current["kind"] == NodeKind.OUTPUT:
                passed = edge["target_port"] == Ports.PASS
                if record and passed:
                    try:  # what the action hands back (ADR-083): worked out where it ends, inside its own inputs
                        walk.outputs = build_outputs(
                            _declared(definition, NodeKind.OUTPUT, "outputs"), run_view
                        )
                    except ContextError as error:
                        if walk.observed and depends_on_skipped(str(error)):
                            raise _not_observable(current["name"]) from error
                        passed, reason = False, str(error)
                outcome = "pass" if passed else "fail"
                if record:
                    await self._record(walk, definition_id, current, outcome, None, None, started)
                return bool(passed), reason
            executor = EXECUTORS.get(NodeKind(current["kind"]))
            if executor is None:
                port = Ports.OUT
                if record:
                    await self._record(walk, definition_id, current, "pass", port, None, started)
                continue
            monitor = walk.monitor if record else None  # a guard's own action is not watched
            inside = f"{walk.path}>{walk.action_id}"
            node_watched = monitor is not None and monitor.watches("node", current["id"])
            if node_watched:
                assert monitor is not None
                await self._guarded(
                    monitor.enter(
                        "node", current["id"], current["name"], inside, definition["name"]
                    )
                )
            timer = time.monotonic()
            runner = executor.run
            mock_used = run_view.dry_run and executor.by_outcome and dry_run.has_mock(current)
            if mock_used:
                runner = dry_run.mocked  # the stored result stands in; nothing is run (ADR-087)
            elif run_view.dry_run and writes(str(current["kind"]), current.get("config")):
                runner = (
                    dry_run.skipped
                )  # what writes is not run; the step says what it would have done (ADR-086)
            result, earlier = await tried(
                partial(runner, current, self._limits, run_view),
                lambda r: (r.reason or "The node failed") if r.outcome == "fail" else None,
                retry_of(current)
                if executor.by_outcome and not mock_used
                else None,  # Retry on fail (ADR-073)
            )
            result.attempts = len(earlier) + 1
            if earlier:  # the failed tries before the last: what only the step shows
                result.detail = {**(result.detail or {}), "tries": earlier}
            result.duration_ms = int(
                (time.monotonic() - timer) * 1000
            )  # the result contract (ADR-072)
            if (
                record
                and walk.observed
                and result.outcome == "fail"
                and depends_on_skipped(result.reason)
            ):  # it needed what a skipped write would have produced: an observed run ends here as done (ADR-088)
                result = NodeResult(
                    "pass",
                    reason=f"Not observable from here: {result.reason}",
                    data={"not_observable": True},
                    attempts=result.attempts,
                    duration_ms=result.duration_ms,
                )
                await self._record(walk, definition_id, current, "pass", None, result, started)
                raise _not_observable(current["name"])
            if result.outcome == "pass" and result.variables:
                try:
                    run_view.context.set_vars(result.variables)
                except ContextError as error:
                    result = replace(result, outcome="fail", reason=f"Invalid vars: {error}")
            port = result.port or (
                (Ports.PASS if result.outcome == "pass" else Ports.FAIL)
                if executor.by_outcome
                else Ports.OUT
            )
            if port == Ports.FAIL:
                result, port = _node_failed(current, result)
            reason = result.reason or (result.output or "").strip()[-200:]
            if record:
                await self._record(
                    walk, definition_id, current, result.outcome, port, result, started
                )
            if node_watched:
                assert monitor is not None
                await self._guarded(
                    monitor.node_ended(current["id"], inside, result.outcome == "pass")
                )
                await self._guarded(monitor.leave("node", current["id"], inside))
            if run_view.context is not walk.context:
                run_view.context.record(current, result, port)

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
        step_limit = min(
            walk.storage.step_output_chars, RESULT_OUTPUT_LIMIT_CHARS
        )  # the user's limit never exceeds the hard one
        if result is not None and len(result.output) > step_limit:
            result = _cut(
                result, step_limit
            )  # never silently: the text, the data and the reason say so
        if result is not None and result.detail:
            detail, cut = cut_detail(result.detail, step_limit)
            if (
                cut
            ):  # a long text of the step's details (a prompt, a tool result) is cut and says so
                result = replace(
                    result, detail=detail, data={**(result.data or {}), "detail_truncated": cut}
                )
        output = result.output if result else ""
        changes: dict[str, Any] = {"step_count": Execution.step_count + 1}
        if result is not None:  # the context is the node's result, as it is stored (masked, capped)
            walk.context.record(node, result, port)
            changes["context"] = walk.context.dumps()
        if walk.monitor is not None:  # every step is progress for the guards' stall clock
            walk.monitor.progress()
            cost = (result.data or {}).get("cost") if result is not None else None
            if isinstance(cost, int | float) and not isinstance(cost, bool):
                walk.monitor.add_cost(float(cost))
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
                    detail=result.detail if result else None,
                    attempts=result.attempts if result else 1,
                    started_at=started,
                    finished_at=datetime.now(UTC),
                )
            )
            await session.flush()
            await session.execute(
                update(Execution).where(Execution.id == walk.execution_id).values(**changes)
            )
            if output and walk.execution_id is not None:
                await self._trim_outputs(
                    session,
                    walk.execution_id,
                    min(walk.storage.run_output_chars, RUN_OUTPUT_LIMIT_CHARS),
                )
            await session.commit()
        if result is not None:  # the steps without output show up with the next save of the run
            await self._publish(walk.task_id)

    @staticmethod
    async def _trim_outputs(
        session: AsyncSession, execution_id: str, limit: int = RUN_OUTPUT_LIMIT_CHARS
    ) -> None:
        """Keep all outputs of the execution within ``limit`` (today's ``RUN_OUTPUT_LIMIT_CHARS`` or the user's lower one): the oldest go first."""
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
            if total <= limit:
                break
            total -= len(row.output) - len(REMOVED_OUTPUT)
            row.output = REMOVED_OUTPUT
        if total > limit:  # the newest alone is too long (cannot be: it is bounded)
            rows[-1].output = rows[-1].output[:limit]
