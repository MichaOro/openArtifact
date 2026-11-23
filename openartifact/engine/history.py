"""The execution history of artifacts: recording, closing, retention and deleting.

One ``Execution`` row exists per start of an artifact. The engine opens it in the transaction that
claims the run and closes it whenever the run stops, fails or ends; this class does the database part
and publishes ``execution.updated`` / ``execution.deleted`` (the callers do that *after* their commit).

Retention (``prune``) is evaluated per artifact over its executions, newest number first, at ``now``:

* the policy is the artifact's ``history_keep_last`` and ``history_keep_hours``; when neither is set,
  the application default (``execution_history_default_keep``, ``0`` = unlimited) acts as ``keep_last``;
* an execution is kept only if it satisfies every limit that is set (logical AND): its rank among the
  artifact's executions is at most ``keep_last`` and its age (``now - started_at``) is at most
  ``keep_hours`` (exactly on the limit is still kept);
* a running execution is never deleted but counts toward ``keep_last``;
* the newest execution (rank 1) is never deleted by retention, whatever the policy says, so an
  artifact always shows what happened last. Deleting it by hand is possible.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.engine import retention
from openartifact.engine.context import RunContext
from openartifact.engine.schemas import ExecutionRead, HistoryPolicy
from openartifact.events import EventBus
from openartifact.models import Execution, PipelineRun, RunNodeResult, RunStatus, Task
from openartifact.schemas_common import as_utc

#: Rows per ``IN`` list when deleting (SQLite limits the number of variables of a statement).
_CHUNK = 500


def utcnow() -> datetime:
    """The clock of the age check (a single place, so tests can set it)."""
    return datetime.now(UTC)


def labels_of(snapshot: dict[str, Any]) -> dict[str, str]:
    """Node id -> display name for the nodes of a snapshot and of the pipelines it contains."""
    graphs = [snapshot, *snapshot.get("pipelines", {}).values()]
    return {n["id"]: n["label"] for graph in graphs for n in graph["nodes"]}


@dataclass
class Changes:
    """What a transaction did to the history; ``ExecutionHistory.publish`` announces it after the commit."""

    updated: list[ExecutionRead] = field(default_factory=list)
    deleted: dict[str, list[str]] = field(default_factory=dict)  # task id -> execution ids


class ExecutionHistory:
    """Opens, closes and prunes executions; see the module docstring for the retention rules."""

    def __init__(self, bus: EventBus, default_keep: int = 50) -> None:
        self._bus = bus
        self.default_keep = default_keep

    # ── policy ────────────────────────────────────────────────────────

    def policy_of(self, task: Task) -> HistoryPolicy:
        return HistoryPolicy(
            keep_last=task.history_keep_last,
            keep_hours=task.history_keep_hours,
            effective_default_keep=self.default_keep,
        )

    def _limits(self, task: Task) -> tuple[int | None, int | None]:
        keep_last, keep_hours = task.history_keep_last, task.history_keep_hours
        if keep_last is None and keep_hours is None and self.default_keep > 0:
            keep_last = self.default_keep
        return keep_last, keep_hours

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
        """Delete the executions the artifact's policy no longer keeps; returns how many."""
        keep_last, keep_hours = self._limits(task)
        if keep_last is None and keep_hours is None:
            return 0
        rows = (
            await session.execute(
                select(Execution.id, Execution.status, Execution.started_at)
                .where(Execution.task_id == task.id)
                .order_by(Execution.number.desc())
            )
        ).all()
        now = utcnow()
        oldest = None if keep_hours is None else now - timedelta(hours=keep_hours)
        doomed = []
        for rank, row in enumerate(rows, start=1):
            if rank == 1 or row.status == RunStatus.RUNNING:
                continue
            too_many = keep_last is not None and rank > keep_last
            too_old = oldest is not None and as_utc(row.started_at) < oldest
            if too_many or too_old:
                doomed.append(row.id)
        await self.remove(session, task.id, doomed, changes)
        return len(doomed)

    async def apply_rules(self, session: AsyncSession, changes: Changes) -> int:
        """Delete the finished executions the global retention rules match (see ``engine/retention.py``)."""
        rules = await retention.load_rules(session)
        found = await retention.matching_ids(session, rules, utcnow())
        by_task: dict[str, list[str]] = {}
        for task_id, execution_id in found:
            by_task.setdefault(task_id, []).append(execution_id)
        for task_id, ids in by_task.items():
            await self.remove(session, task_id, ids, changes)
        return len(found)

    @staticmethod
    async def remove(session: AsyncSession, task_id: str, ids: list[str], changes: Changes) -> None:
        """Delete executions with their steps in this transaction (never a running one: the callers check)."""
        for i in range(0, len(ids), _CHUNK):
            chunk = ids[i : i + _CHUNK]
            await session.execute(
                delete(RunNodeResult).where(RunNodeResult.execution_id.in_(chunk))
            )
            await session.execute(
                update(PipelineRun)
                .where(PipelineRun.execution_id.in_(chunk))
                .values(execution_id=None)
            )
            await session.execute(delete(Execution).where(Execution.id.in_(chunk)))
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
