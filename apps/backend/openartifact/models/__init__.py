"""Domain models for OpenArtifact.

Defines the core entities used by the Project Workspace MVP:

- ``Project`` — a container for related work items.
- ``WorkItem`` — an individual task belonging to a project.
- ``WorkItemStatus`` — the board status of a work item.
- ``Task`` — a card on the Kanban board (``TaskStatus`` = its lane).

The four status values describe the *board* state only. They are deliberately
decoupled from any future pipeline or execution stages so that the board can
be reconfigured without touching the execution layer.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from openartifact.database import Base

if TYPE_CHECKING:
    pass


class WorkItemStatus(enum.StrEnum):
    """Board status of a work item.

    Values are stored as their string identifier in the database so that the
    enum can evolve (new labels, renamed labels) without a schema migration.
    """

    BACKLOG = "BACKLOG"
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    REVIEW = "REVIEW"


# Ordered list of board lanes — used for UI rendering and default sorting.
BOARD_STATUSES: tuple[WorkItemStatus, ...] = (
    WorkItemStatus.BACKLOG,
    WorkItemStatus.TODO,
    WorkItemStatus.IN_PROGRESS,
    WorkItemStatus.REVIEW,
)


class Project(Base):
    """A project groups related work items.

    Attributes:
        id: Unique project identifier (UUID string).
        name: Human-readable project name.
        description: Optional project description.
        created_at: Creation timestamp (UTC).
        updated_at: Last modification timestamp (UTC).
    """

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Project(id={self.id!r}, name={self.name!r})>"


class WorkItem(Base):
    """An individual work item belonging to a project.

    Attributes:
        id: Unique work item identifier (UUID string).
        project_id: Foreign key to the owning project.
        title: Short title of the work item.
        description: Optional longer description.
        status: Current board status (see :class:`WorkItemStatus`).
        position: Sort order within a lane. Lower values appear first.
        created_at: Creation timestamp (UTC).
        updated_at: Last modification timestamp (UTC).
    """

    __tablename__ = "work_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[WorkItemStatus] = mapped_column(
        default=WorkItemStatus.BACKLOG,
    )
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WorkItem(id={self.id!r}, project_id={self.project_id!r}, status={self.status!r})>"


class TaskStatus(enum.StrEnum):
    """Lane of a board task. The value is what is stored in ``tasks.status``."""

    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class Task(Base):
    """A card on the Kanban board.

    Intentionally minimal (see migration 0003). It is independent of
    ``WorkItem``, which is bound to the not-yet-built project workspace.

    Attributes:
        id: Unique task identifier (UUID string).
        title: Short title (required).
        body: Optional longer description.
        status: Lane of the task (see :class:`TaskStatus`).
        number: Human-readable artifact number (#1, #2 …), unique and never reused (see
            migration 0006).
        parent_id: Optional parent artifact (a tree: one parent, any number of children). Kept
            acyclic by the repository; the database keeps it referentially intact (foreign key,
            ``ON DELETE SET NULL``).
        position: Sort key inside the lane, ascending (see migration 0004). Fractional so a task
            can be dropped between two others without renumbering the lane.
        created_at: Creation timestamp (UTC).
        updated_at: Last modification timestamp (UTC).
    """

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Plain string column; the allowed values are enforced by TaskStatus (API)
    # and a CHECK constraint (database).
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.BACKLOG.value)
    number: Mapped[int] = mapped_column(Integer, nullable=True, unique=True)
    position: Mapped[float] = mapped_column(Float, default=0.0)
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Task(id={self.id!r}, status={self.status!r})>"


class NodeKind(enum.StrEnum):
    """Kinds of nodes in a workflow definition."""

    TRIGGER = "trigger"
    STAGE = "stage"
    ACTION = "action"
    COMPLETE = "complete"
    OUTPUT = "output"
    TIMER = "timer"


class Workflow(Base):
    """A workflow definition: a graph of a trigger, stages (containing actions) and endings.

    Attributes:
        id: Unique identifier (UUID string).
        name: Display name.
        status: Lifecycle of the definition (only ``draft`` exists so far).
        kind: ``workflow``, or ``action`` for the definition of what an action does.
        slug: Readable URL name, unique per kind (follows the name).
        created_at: Creation timestamp (UTC).
        updated_at: Last modification timestamp (UTC).
    """

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    kind: Mapped[str] = mapped_column(String(16), default="workflow", server_default="workflow")
    slug: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class WorkflowNode(Base):
    """A node of a workflow. Actions live inside a stage and are positioned relative to it.

    Attributes:
        kind: See :class:`NodeKind`.
        stage_id: The stage an action belongs to (``None`` for all other kinds).
        x, y: Position on the canvas; for an action relative to its stage.
        width, height: Size of a stage (``None`` for other kinds).
        fail_enabled: Whether an output node offers *On Fail* besides *On Pass*.
        seconds: How long a timer pauses the run.
        definition_id: The action definition an action is linked to (``None``: an empty shell).
    """

    __tablename__ = "workflow_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    stage_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflow_nodes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    x: Mapped[float] = mapped_column(Float, default=0.0)
    y: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[float | None] = mapped_column(Float, nullable=True)
    height: Mapped[float | None] = mapped_column(Float, nullable=True)
    fail_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    definition_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class WorkflowEdge(Base):
    """A connection from an output port of one node to an input port of another.

    An output port has at most one edge (unique ``source_id`` + ``source_port``). ``style`` is how
    it is drawn; the slots say which of a stage's three attachment points per side it uses.
    """

    __tablename__ = "workflow_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_nodes.id", ondelete="CASCADE")
    )
    source_port: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_nodes.id", ondelete="CASCADE"), index=True
    )
    target_port: Mapped[str] = mapped_column(String(16))
    style: Mapped[str] = mapped_column(String(16), default="curved", server_default="curved")
    source_slot: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    target_slot: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class PipelineRun(Base):
    """The processing of one artifact in a pipeline (at most one per artifact).

    Attributes:
        status: ``running``, ``stopped``, ``done`` or ``failed``.
        started_by: ``user`` or ``system``; the business logic is the same for both.
        stage_id, action_id: Where the run is (node ids of the frozen pipeline).
        note: Why it stopped or failed.
        snapshot: JSON copy of the pipeline and the action definitions it uses, taken at the start.
    """

    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), unique=True
    )
    workflow_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16))
    started_by: Mapped[str] = mapped_column(String(16))
    stage_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


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
