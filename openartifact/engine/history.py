"""The execution history of artifacts: recording, closing, retention and deleting.

One ``Execution`` row exists per start of an artifact. The engine opens it in the transaction that
claims the run and closes it whenever the run stops, fails or ends; this class does the database part
and publishes ``execution.updated`` / ``execution.deleted`` (the callers do that *after* their commit).

Retention (``prune``) is evaluated per artifact over its executions, newest number first, at ``now``:

* the only per-artifact limit is the operator's guard against unbounded growth: the newest
  ``execution_history_default_keep`` executions are kept (``0`` = unlimited). There is no per-artifact policy any
  more (ADR-057): what to keep for how long is the business of the global retention rules (``apply_rules``);
* a running execution is never deleted but counts toward the number kept;
* the newest execution (rank 1) is never deleted by retention, so an artifact always shows what happened
  last. Deleting it by hand is possible.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.activity.recorder import record
from openartifact.activity.schemas import ActivityRead
from openartifact.comments.schemas import Author
from openartifact.engine import retention
from openartifact.engine.context import RunContext
from openartifact.engine.schemas import ExecutionRead
from openartifact.events import EventBus
from openartifact.models import Execution, PipelineRun, RunNodeResult, RunStatus, Task

#: Rows per ``IN`` list when deleting (SQLite limits the number of variables of a statement).
_CHUNK = 500


def utcnow() -> datetime:
    """The clock of the age check (a single place, so tests can set it)."""
    return datetime.now(UTC)


def labels_of(snapshot: dict[str, Any]) -> dict[str, str]:
    """Node id -> display name for the nodes of a snapshot and of the pipelines it contains."""
    graphs = [snapshot, *snapshot.get("pipelines", {}).values()]
    return {n["id"]: n["label"] for graph in graphs for n in graph["nodes"]}


def _utc(moment: datetime) -> datetime:
    """A timestamp read from the database (naive, UTC) as an aware one."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


#: Who deletes when nobody asked: the operator's per-artifact guard and the global retention rules (ADR-058).
GUARD = Author("system", "operator guard")
RULES = Author("system", "retention rule")
#: A trace of many deleted executions names at most this many numbers; ``count`` has the rest.
TRACE_NUMBERS = 50


async def _trace(
    session: AsyncSession, task_id: str, gone: list[tuple[str, int, datetime]], actor: Author
) -> ActivityRead:
    """The ONE entry a delete action leaves for an artifact: who deleted which executions, and when (now).

    One execution: ``number`` and ``started_at``. Several: ``numbers`` (the first ``TRACE_NUMBERS``) and ``count``.
    Nothing else of them is kept: they cannot be opened any more (ADR-058).
    """
    gone = sorted(gone, key=lambda e: e[1])
    if len(gone) == 1:
        data: dict[str, Any] = {"number": gone[0][1], "started_at": _utc(gone[0][2]).isoformat()}
        execution_id: str | None = gone[0][0]
    else:
        data = {"numbers": [e[1] for e in gone[:TRACE_NUMBERS]], "count": len(gone)}
        execution_id = None
    return await record(session, task_id, "run", actor, data, execution_id=execution_id)


@dataclass
class Changes:
    """What a transaction did to the history; ``ExecutionHistory.publish`` announces it after the commit."""

    updated: list[ExecutionRead] = field(default_factory=list)
    deleted: dict[str, list[str]] = field(default_factory=dict)  # task id -> execution ids
    traces: list[ActivityRead] = field(default_factory=list)  # what deleted executions leave behind


class ExecutionHistory:
    """Opens, closes and prunes executions; see the module docstring for the retention rules."""

    def __init__(self, bus: EventBus, default_keep: int = 50) -> None:
        self._bus = bus
        self.default_keep = default_keep

    # ── recording ─────────────────────────────────────────────────────

    @staticmethod
    async def open(
        session: AsyncSession,
        task: Task,
        *,
        pipeline_id: str,
        snapshot: dict[str, Any],
        stage_id: str | None,
        action_id: str | None,
        started_by: str,
        context: RunContext,
        dry_run: bool = False,
        observed: bool = False,
    ) -> Execution:
        """Add a running execution with the next number of the artifact and its first context (not committed)."""
        labels = labels_of(snapshot)
        now = utcnow()
        task.execution_seq += 1
        execution = Execution(
            id=str(uuid.uuid4()),
            task_id=task.id,
            number=task.execution_seq,
            pipeline_id=pipeline_id,
            pipeline_name=snapshot["name"],
            started_stage_id=stage_id,
            started_stage_name=labels.get(stage_id or ""),
            started_action_id=action_id,
            started_action_name=labels.get(action_id or ""),
            final_stage_name=labels.get(stage_id or ""),
            final_action_name=labels.get(action_id or ""),
            status=RunStatus.RUNNING,
            started_by=started_by,
            dry_run=dry_run,
            observed=observed,
            snapshot=json.dumps(snapshot),
            context=context.dumps(),
            created_at=now,
            started_at=now,
        )
        session.add(execution)
        await session.flush()
        return execution

    async def close(
        self,
        session: AsyncSession,
        run: PipelineRun,
        changes: Changes,
        *,
        status: str | None = None,
    ) -> None:
        """Bring the run's execution in line with the run (status, note, where it ended, steps).

        The first end of an execution sets ``finished_at``; it is not touched again.
        """
        if run.execution_id is None:
            return
        execution = await session.get(Execution, run.execution_id)
        if execution is None:
            return
        execution.status = status or run.status
        execution.note = run.note
        if execution.status == RunStatus.RUNNING:
            execution.finished_at = None
        elif execution.finished_at is None:
            execution.finished_at = utcnow()
        try:
            labels = labels_of(json.loads(run.snapshot))
        except (ValueError, KeyError):
            labels = {}
        execution.final_stage_name = labels.get(run.stage_id or "", execution.final_stage_name)
        execution.final_action_name = labels.get(run.action_id or "", execution.final_action_name)
        execution.step_count = (
            await session.scalar(
                select(func.count())
                .select_from(RunNodeResult)
                .where(RunNodeResult.execution_id == execution.id)
            )
            or 0
        )
        changes.updated.append(ExecutionRead.of(execution))

    # ── retention and deleting ────────────────────────────────────────

    async def prune(self, session: AsyncSession, task: Task, changes: Changes) -> int:
        """Delete the executions beyond the number kept per artifact (the user's setting *Executions kept per artifact*, else the
        operator's guard ``default_keep``; the newest stay); returns how many."""
        from openartifact.engine.storage import STORAGE_LIMIT, load_policy

        policy = await load_policy(session)
        keep_last = policy.keep(self.default_keep)
        if keep_last <= 0:
            return 0
        rows = (
            await session.execute(
                select(Execution.id, Execution.status, Execution.started_at)
                .where(Execution.task_id == task.id)
                .order_by(Execution.number.desc())
            )
        ).all()
        doomed = [
            row.id
            for rank, row in enumerate(rows, start=1)
            if rank > keep_last and rank != 1 and row.status != RunStatus.RUNNING
        ]
        await self.remove(
            session,
            task.id,
            doomed,
            changes,
            GUARD if policy.keep_executions is None else STORAGE_LIMIT,
        )
        return len(doomed)

    async def apply_rules(self, session: AsyncSession, changes: Changes) -> int:
        """Delete the finished executions the global retention rules match (see ``engine/retention.py``)."""
        rules = await retention.load_rules(session)
        found = await retention.matching_ids(session, rules, utcnow())
        by_task: dict[str, list[str]] = {}
        for task_id, execution_id in found:
            by_task.setdefault(task_id, []).append(execution_id)
        for task_id, ids in by_task.items():
            await self.remove(session, task_id, ids, changes, RULES)
        return len(found)

    @staticmethod
    async def remove(
        session: AsyncSession,
        task_id: str,
        ids: list[str],
        changes: Changes,
        actor: Author = RULES,
    ) -> None:
        """Delete executions with their steps in this transaction (never a running one: the callers check).

        The whole action leaves ONE trace in the artifact's activity (ADR-058): who deleted, which numbers, when.
        """
        gone: list[tuple[str, int, datetime]] = []
        for i in range(0, len(ids), _CHUNK):
            chunk = ids[i : i + _CHUNK]
            rows = await session.execute(
                select(Execution.id, Execution.number, Execution.started_at).where(
                    Execution.id.in_(chunk)
                )
            )
            gone.extend((row.id, row.number, row.started_at) for row in rows)
            await session.execute(
                delete(RunNodeResult).where(RunNodeResult.execution_id.in_(chunk))
            )
            await session.execute(
                update(PipelineRun)
                .where(PipelineRun.execution_id.in_(chunk))
                .values(execution_id=None)
            )
            await session.execute(delete(Execution).where(Execution.id.in_(chunk)))
        if gone:
            changes.traces.append(await _trace(session, task_id, gone, actor))
        if ids:
            changes.deleted.setdefault(task_id, []).extend(ids)

    # ── events ────────────────────────────────────────────────────────

    def publish(self, changes: Changes) -> None:
        """Announce what a committed transaction changed."""
        for execution in changes.updated:
            self._bus.publish(
                "execution.updated",
                {"task_id": execution.task_id, "execution": execution.model_dump(mode="json")},
            )
        for task_id, ids in changes.deleted.items():
            for execution_id in ids:
                self._bus.publish("execution.deleted", {"task_id": task_id, "id": execution_id})
        for trace in changes.traces:
            self._bus.publish("activity.created", trace.model_dump(mode="json"))
