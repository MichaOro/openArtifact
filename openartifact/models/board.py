"""The board: artifacts (``Task``), their lanes, the number counter and the artifact fields every artifact has."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

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
        execution_seq: The last execution number handed out for this artifact (never reused).
        archived_from_status: The lane it was archived from (migration 0058).
        archived_at: When it was archived (migration 0058, ADR-071); ``None`` while it is visible.
        field_values: The values of the artifact fields by name (JSON object text, migration 0038; a
            field without a value reads as its default); see ``openartifact/artifact_fields``.
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
    execution_seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    field_values: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    #: A technical card (migration 0068, ADR-089): the hidden card the dry runs of a graph that was started without a card belong to. It is
    #: in no list, count or rule of the board (``tasks/technical.py``); its executions are like any card's.
    technical: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    #: When a card rule (or the user) archived it: it is then left out of the board's list (ADR-071); ``None``: visible.
    archived_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None, index=True)
    #: The lane key the card was in when it was archived (no foreign key: the lane may be gone when it comes back).
    archived_from_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default=None
    )
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
    #: The id of the lane in the interfaces (migration 0069, ADR-090): never changes, says nothing, survives a rename. ``key`` stays the
    #: storage value of ``tasks.status`` and is generated once from the first title: after a rename it no longer matches the title.
    uuid: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()), server_default="")
    title: Mapped[str] = mapped_column(String(40, collation="NOCASE"))
    position: Mapped[int] = mapped_column(Integer)
    #: How the lane draws its cards: ``normal`` or ``finished`` (migration 0032, ``LANE_STYLES``).
    style: Mapped[str] = mapped_column(String(16), default="normal", server_default="normal")
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), server_default=func.current_timestamp()
    )


Index("ux_lanes_title", Lane.title, unique=True)
Index("ux_lanes_uuid", Lane.uuid, unique=True)


class TaskNumberSeq(Base):
    """The counter behind ``Task.number`` (one row, ``id = 1``): numbers are never reused."""

    __tablename__ = "task_number_seq"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last: Mapped[int] = mapped_column(Integer)


class ArtifactField(Base):
    """A field every artifact has (ADR-044): ``kind`` is ``text``, ``number``, ``boolean`` or ``choice``.

    ``name`` is what pipelines read (``${card.NAME}``), ``label`` what the user sees. ``default_json`` is the
    default as JSON text (it pre-fills new artifacts and stands in for a value that is not set),
    ``options_json`` the allowed values of a choice (a JSON list of text). ``max_length`` applies to text,
    ``min_value``/``max_value``/``integer_only`` to numbers. ``position`` is the order of the list.
    """

    __tablename__ = "artifact_fields"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(16))
    default_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    options_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    max_length: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    integer_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    #: A choice that holds several of its values (ADR-050).
    multiple: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    position: Mapped[int] = mapped_column(Integer, default=0)


class TaskComment(Base):
    """A comment on an artifact (ADR-055, migration 0041): plain text, written by a person, a script, an agent or a run.

    Attributes:
        body: The text (at most 64 KiB), shown with its line breaks, never as markup.
        author_kind: ``user`` (the browser), ``api``, ``mcp``, ``run`` (a pipeline node) or ``system``.
        author: Who, as a name (at most 64 characters): "You", the name of a managed token, a node's name.
        execution_id: For ``run``: the execution that wrote it (no foreign key: the history may be pruned).
    """

    __tablename__ = "task_comments"
    __table_args__ = (Index("ix_task_comments_task_created", "task_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(Text)
    author_kind: Mapped[str] = mapped_column(String(16))
    author: Mapped[str] = mapped_column(String(64))
    execution_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class TaskActivity(Base):
    """What changed on an artifact and who did it (ADR-058, migration 0044), or the trace of a deleted execution.

    Attributes:
        kind: ``created``, ``lane``, ``title``, ``description``, ``parent``, ``field``, ``pipeline``, ``stage``,
            ``action``, ``run`` (the trace of one delete action on executions: who, which numbers), ``comment`` (a comment's
            id, never its text) or ``comment_deleted``.
        actor_kind, actor_name: Who, as for comments (ADR-055).
        execution_id: For ``run`` (one execution): the deleted execution; for ``comment`` by a run: its execution (no foreign key).
        data: A small JSON object that depends on the kind (names at the time, never the text of a description).
        created_at: When it happened (for ``run`` and ``comment_deleted``: when it was deleted).
    """

    __tablename__ = "task_activity"
    __table_args__ = (Index("ix_task_activity_task_created", "task_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    actor_kind: Mapped[str] = mapped_column(String(16))
    actor_name: Mapped[str] = mapped_column(String(64))
    execution_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    data: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
