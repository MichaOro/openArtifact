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

from sqlalchemy import Float, ForeignKey, String, Text
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
        parent_id: Optional parent artifact (a tree: one parent, any number of children). Kept
            consistent by the repository (cycle check, children are detached on delete); there is
            deliberately no database foreign key (SQLite cannot add one to an existing table).
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
    position: Mapped[float] = mapped_column(Float, default=0.0)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Task(id={self.id!r}, status={self.status!r})>"
