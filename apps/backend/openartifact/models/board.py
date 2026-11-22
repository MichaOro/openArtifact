"""The board: artifacts (``Task``), their lanes, the number counter and artifact types with their parameters."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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
        status: Key of the task's lane (``lanes.key``, foreign key ``ON DELETE RESTRICT``, migration 0030).
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
        type_id, parameters: The artifact type (``None``: untyped) and the values of its parameters
            (JSON object text, migration 0031); see ``openartifact/artifact_types``.
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
        Index("ix_tasks_type_id", "type_id"),
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
    type_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("artifact_types.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    parameters: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Task(id={self.id!r}, status={self.status!r})>"


class Lane(Base):
    """A column of the board (migration 0030).

    ``key`` is what artifacts carry in ``tasks.status``: generated from the first title, never
    changed. ``position`` orders the lanes on the board. Titles are unique ignoring case (``NOCASE`` folds ASCII letters; the service compares with ``casefold``).
    """

    __tablename__ = "lanes"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(40, collation="NOCASE"))
    position: Mapped[int] = mapped_column(Integer)
    #: How the lane draws its cards: ``normal`` or ``finished`` (migration 0032, ``LANE_STYLES``).
    style: Mapped[str] = mapped_column(String(16), default="normal", server_default="normal")
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), server_default=func.current_timestamp()
    )


Index("ux_lanes_title", Lane.title, unique=True)


class TaskNumberSeq(Base):
    """The counter behind ``Task.number`` (one row, ``id = 1``): numbers are never reused."""

    __tablename__ = "task_number_seq"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last: Mapped[int] = mapped_column(Integer)


class ArtifactType(Base):
    """A kind of artifact the user defines, with its own parameters (``artifact_type_fields``).

    The name is unique ignoring case. A type that artifacts use cannot be deleted (``RESTRICT``).
    """

    __tablename__ = "artifact_types"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(60, collation="NOCASE"), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class ArtifactTypeField(Base):
    """One parameter of an artifact type: ``kind`` is ``text``, ``number``, ``boolean`` or ``choice``.

    ``default_json`` is the default value as JSON text, ``options_json`` the allowed values of a choice
    (a JSON list of text). ``max_length`` applies to text, ``min_value``/``max_value``/``integer_only`` to
    numbers. ``position`` is the order of the type's fields.
    """

    __tablename__ = "artifact_type_fields"

    type_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("artifact_types.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(16))
    required: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    default_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    options_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    max_length: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    integer_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    position: Mapped[int] = mapped_column(Integer, default=0)
