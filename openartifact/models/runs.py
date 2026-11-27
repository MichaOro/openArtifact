"""Processing and its history: the current run of an artifact, its stages, every execution and its steps."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from openartifact.database import Base


class PipelineRun(Base):
    """The current processing of one artifact in a pipeline (at most one per artifact).

    The history of earlier starts is in ``Execution``; ``execution_id`` points to the current one.

    Attributes:
        status: ``running``, ``stopped``, ``done`` or ``failed``.
        started_by: ``user``, ``api``, ``mcp`` or ``system`` (see :class:`StartedBy`).
        stage_id, action_id: Where the run is (node ids of the frozen pipeline).
        note: Why it stopped or failed.
        snapshot: JSON copy of the pipeline and the action definitions it uses, taken at the start.
        created_at: When the current run began (the row is reused when the artifact is started again).
    """

    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), unique=True
    )
    pipeline_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("graphs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16))
    started_by: Mapped[str] = mapped_column(String(16))
    stage_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot: Mapped[str] = mapped_column(Text)
    execution_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("executions.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class Execution(Base):
    """One run attempt of an artifact: every start (and restart) of it in a pipeline, kept as history.

    Attributes:
        number: Per artifact, from 1, never reused (``tasks.execution_seq`` counts).
        pipeline_id, pipeline_name: The pipeline started in; the name is a copy (pipelines change and
            go away). No foreign key: the history outlives the pipeline.
        started_stage_*, started_action_*: Where it started (copies); ``None`` for executions that were
            backfilled from a run of before migration 0023, where this is not known.
        final_stage_name, final_action_name: Where the run was when the execution ended.
        status: ``running``, ``done``, ``failed`` or ``stopped`` (``RunStatus``).
        note: Why it stopped or failed.
        started_by: ``user``, ``api``, ``mcp`` or ``system``.
        step_count: Number of steps recorded in ``run_node_results``.
        snapshot: The frozen pipeline (JSON), so the execution can be shown as a graph later; deferred.
        context: The run context (JSON: variables and the results of the nodes that ran), written with
            every step; the only place it is kept (the run reads it through ``pipeline_runs.execution_id``); deferred.
        finished_at: ``None`` while it runs.
    """

    __tablename__ = "executions"
    __table_args__ = (
        Index("ux_executions_task_number", "task_id", "number", unique=True),
        # The global execution list: newest first, with or without a status filter (migration 0025).
        Index("ix_executions_started_at", "started_at", "id"),
        Index("ix_executions_status_started_at", "status", "started_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    pipeline_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pipeline_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    started_stage_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_stage_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_action_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    final_stage_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    final_action_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_by: Mapped[str] = mapped_column(String(16))
    step_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    snapshot: Mapped[str] = mapped_column(Text, default="{}", server_default="{}", deferred=True)
    context: Mapped[str] = mapped_column(Text, default="{}", server_default="{}", deferred=True)
    #: The guards' bookkeeping of the run (ADR-060, migration 0046): counters per scope and per guard, the last
    #: heartbeat and the firings (JSON); written while the run goes, kept with the execution; deferred.
    guard_state: Mapped[str] = mapped_column(Text, default="{}", server_default="{}", deferred=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    started_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)


class RunStage(Base):
    """The status of one stage in a run: ``pending``, ``running``, ``passed``, ``failed`` or ``skipped``."""

    __tablename__ = "run_stages"

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), primary_key=True
    )
    stage_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))


class RunNodeResult(Base):
    """One step of a run inside an action definition: every node the engine executed, in order.

    ``seq`` counts the steps of the execution from 1; ``port`` is the connector the run left the node by
    (``pass``, ``fail`` or ``out``; none for an output node, which ends the action, where
    ``outcome`` says which input was reached). Code and HTTP nodes also carry ``exit_code``,
    ``output`` (text only, bounded), ``reason`` and ``data``; the other nodes leave these empty. An agent
    node also has ``detail`` (the prompts as they were sent and every attempt), which goes with the row.
    The position is given by ``pipeline_id`` (the pipeline whose action this is: the run's own or a
    called one), ``depth`` (0 for the run's own), ``top_stage_id`` (the entry of the run's own
    pipeline it is inside), ``stage_id``, ``action_id`` and ``definition_id`` (the action
    definition ``node_id`` belongs to). Ids point into the frozen snapshot, so there are no foreign
    keys but ``run_id`` and ``execution_id``. A row belongs to the execution that recorded it (migration
    0023) and goes with it (retention, deleting it); a restart of the artifact leaves the rows of its
    earlier executions alone. ``run_id`` is kept for the run that recorded it.
    """

    __tablename__ = "run_node_results"
    __table_args__ = (
        Index("ux_run_node_results_execution_seq", "execution_id", "seq", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pipeline_runs.id", ondelete="CASCADE")
    )
    execution_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("executions.id", ondelete="CASCADE"), nullable=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    pipeline_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    top_stage_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    stage_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    definition_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    node_id: Mapped[str] = mapped_column(String(36))
    node_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    kind: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(8))
    port: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output: Mapped[str] = mapped_column(Text, default="", server_default="")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: What only the step itself shows (an agent's prompts and attempts, migration 0033): never part of
    #: the run context, loaded only when one step is read; deferred.
    detail: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, default=None, deferred=True
    )
    #: How many tries the node took (*Retry on fail*, ADR-073, migration 0059); the failed tries before the last are in ``detail["tries"]``.
    attempts: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    started_at: Mapped[datetime] = mapped_column()
    finished_at: Mapped[datetime] = mapped_column()
