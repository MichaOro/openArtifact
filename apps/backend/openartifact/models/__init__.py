"""Database models and the value sets stored in their string columns.

Live: ``Task`` (an artifact, a card on the board; ``status`` is the key of its ``Lane``), ``Lane``, ``Graph``,
``GraphNode`` and ``GraphEdge`` (a pipeline or an action definition and what it is made of) and
``PipelineRun`` with ``RunStage`` (the current processing of a task) and ``Execution`` (the history: one
row per start, with the steps it recorded in ``RunNodeResult``). ``TaskNumberSeq`` is the counter that
numbers tasks.

The indexes and constraints declared here are the ones the migrations create; ``alembic check``
(tests/test_migrations.py) fails when the two drift apart.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from openartifact.database import Base


class Task(Base):
    """A card on the Kanban board.

    Intentionally minimal (see migration 0003).

    Attributes:
        id: Unique task identifier (UUID string).
        title: Short title (required).
        body: Optional longer description.
        status: Key of the task's lane (``lanes.key``, foreign key ``ON DELETE RESTRICT``, migration 0029).
        number: Human-readable artifact number (#1, #2 …), unique and never reused (see
            migration 0006).
        parent_id: Optional parent artifact (a tree: one parent, any number of children). Kept
            acyclic by the repository; the database keeps it referentially intact (foreign key,
            ``ON DELETE SET NULL``).
        pipeline_id, stage_id, action_id: The pipeline, stage and action the artifact starts with
            (migration 0019); ``None`` until a pipeline is chosen.
        created_by: How it was created: ``user``, ``api``, ``mcp`` or ``action``.
        history_keep_last, history_keep_hours: The retention policy of the execution history (migration
            0023): keep at most this many executions and/or none older than this many hours; both
            ``None``: the application default applies. See ``engine/history.py``.
        execution_seq: The last execution number handed out for this artifact (never reused).
        position: Sort key inside the lane, ascending (see migration 0004). Fractional so a task
            can be dropped between two others without renumbering the lane.
        created_at: Creation timestamp (UTC).
        updated_at: Last modification timestamp (UTC).
    """

    __tablename__ = "tasks"
    __table_args__ = (
        Index("ux_tasks_number", "number", unique=True),
        Index("ix_tasks_parent_id", "parent_id"),
        Index("ix_tasks_status_position", "status", "position"),
        Index("ix_tasks_status_created_at", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), ForeignKey("lanes.key", ondelete="RESTRICT", name="fk_tasks_status_lanes")
    )
    number: Mapped[int] = mapped_column(Integer, nullable=True)
    position: Mapped[float] = mapped_column(Float, default=0.0)
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, default=None
    )
    pipeline_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("graphs.id", ondelete="SET NULL"), nullable=True, default=None
    )
    stage_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    action_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    created_by: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
    history_keep_last: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    history_keep_hours: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    execution_seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Task(id={self.id!r}, status={self.status!r})>"


class Lane(Base):
    """A column of the board (migration 0029).

    ``key`` is what artifacts carry in ``tasks.status``: generated from the first title, never
    changed. ``position`` orders the lanes on the board. Titles are unique ignoring case (``NOCASE`` folds ASCII letters; the service compares with ``casefold``).
    """

    __tablename__ = "lanes"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(40, collation="NOCASE"))
    position: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), server_default=func.current_timestamp()
    )


Index("ux_lanes_title", Lane.title, unique=True)


class TaskNumberSeq(Base):
    """The counter behind ``Task.number`` (one row, ``id = 1``): numbers are never reused."""

    __tablename__ = "task_number_seq"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last: Mapped[int] = mapped_column(Integer)


class CreatedBy(enum.StrEnum):
    """How a task came to be (``tasks.created_by``)."""

    USER = "user"
    API = "api"
    MCP = "mcp"
    ACTION = "action"


class StartedBy(enum.StrEnum):
    """How a run was started (``pipeline_runs.started_by``, ``executions.started_by``); the business
    logic is the same for all of them, the history shows the way."""

    USER = "user"  # the browser
    API = "api"  # the REST integration API
    MCP = "mcp"  # the MCP server
    SYSTEM = "system"  # the application itself


class RunStatus(enum.StrEnum):
    """State of a run (``pipeline_runs.status``)."""

    RUNNING = "running"
    STOPPED = "stopped"
    DONE = "done"
    FAILED = "failed"


class StageStatus(enum.StrEnum):
    """State of one stage of a run (``run_stages.status``)."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class GraphKind(enum.StrEnum):
    """What a ``graphs`` row is: a pipeline, or the definition of what an action does."""

    PIPELINE = "pipeline"
    ACTION = "action"


class NodeKind(enum.StrEnum):
    """Kinds of nodes in a graph."""

    TRIGGER = "trigger"
    STAGE = "stage"
    ACTION = "action"
    COMPLETE = "complete"
    OUTPUT = "output"
    TIMER = "timer"
    PIPELINE = "pipeline"
    CODE = "code"
    HTTP = "http"


class Graph(Base):
    """A graph, the stored form of a pipeline or an action definition: stages (containing actions) and endings.

    Attributes:
        id: Unique identifier (UUID string).
        name: Display name.
        status: Lifecycle of the definition (only ``draft`` exists so far).
        kind: ``pipeline``, or ``action`` for the definition of what an action does.
        slug: Readable URL name, unique per kind (follows the name).
        created_at: Creation timestamp (UTC).
        updated_at: Last modification timestamp (UTC).
    """

    __tablename__ = "graphs"
    __table_args__ = (Index("ux_graphs_kind_slug", "kind", "slug", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    kind: Mapped[str] = mapped_column(String(16), default="pipeline", server_default="pipeline")
    slug: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class GraphNode(Base):
    """A node of a graph. Actions live inside a stage and are positioned relative to it.

    Attributes:
        kind: See :class:`NodeKind`.
        stage_id: The stage an action belongs to (``None`` for all other kinds).
        x, y: Position on the canvas; for an action relative to its stage.
        width, height: Size of a stage (``None`` for other kinds).
        fail_enabled: Whether an output node offers *On Fail* besides *On Pass*.
        seconds: How long a timer pauses the run.
        config: The settings of kinds that keep them as one JSON object (Code, HTTP): only the keys that
            were set; the defaults of the kind fill in the rest (``NodeType.effective_config``).
        definition_id: What an action is linked to (an action definition; ``None``: an empty shell), or the
            pipeline a pipeline node calls.
    """

    __tablename__ = "graph_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    graph_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("graphs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    stage_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    x: Mapped[float] = mapped_column(Float, default=0.0)
    y: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[float | None] = mapped_column(Float, nullable=True)
    height: Mapped[float | None] = mapped_column(Float, nullable=True)
    fail_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    definition_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("graphs.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class GraphEdge(Base):
    """A connection from an output port of one node to an input port of another.

    An output port has at most one edge (unique ``source_id`` + ``source_port``). ``style`` is how
    it is drawn; the slots say which of a stage's three attachment points per side it uses.
    """

    __tablename__ = "graph_edges"
    __table_args__ = (UniqueConstraint("source_id", "source_port", name="ux_graph_edges_output"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    graph_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("graphs.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("graph_nodes.id", ondelete="CASCADE")
    )
    source_port: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("graph_nodes.id", ondelete="CASCADE"), index=True
    )
    target_port: Mapped[str] = mapped_column(String(16))
    style: Mapped[str] = mapped_column(String(16), default="curved", server_default="curved")
    source_slot: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    target_slot: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


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
    ``output`` (text only, bounded), ``reason`` and ``data``; the other nodes leave these empty.
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
    started_at: Mapped[datetime] = mapped_column()
    finished_at: Mapped[datetime] = mapped_column()


class Secret(Base):
    """A named secret for execution nodes, encrypted at rest (see ``secret_crypto.py``).

    Nodes refer to it by ``name`` only; ``value`` is ``version | nonce | AES-GCM ciphertext`` with the
    name as associated data. The API never returns it.
    """

    __tablename__ = "secrets"
    __table_args__ = (Index("ux_secrets_name", "name", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    value: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
