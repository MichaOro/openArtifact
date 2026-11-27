"""Pipelines and action definitions, stored as graphs of nodes and edges (ADR-012, ADR-015)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from openartifact.database import Base


class Graph(Base):
    """A graph, the stored form of a pipeline or an action definition: stages (containing actions) and endings.

    Attributes:
        id: Unique identifier (UUID string).
        name: Display name.
        status: Lifecycle of the definition (only ``draft`` exists so far).
        kind: ``pipeline``, or ``action`` for the definition of what an action does.
        purpose: What an action definition is for: ``pipeline`` (a stage uses it) or ``guard`` (only a guard uses it, ADR-067).
        slug: Readable URL name, unique per kind (follows the name).
        description: What it is for, in a sentence or two (empty when nobody wrote one).
        tags: Short labels to find it by (a JSON list of text).
        published_number: The version executions use (ADR-070); ``None``: nothing published, the draft runs.
        observe_state: The counters and the decisions of the observe mode of a pipeline (ADR-088).
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
    purpose: Mapped[str] = mapped_column(String(16), default="pipeline", server_default="pipeline")
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    published_number: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    #: The observation of a pipeline that is under way and what the owner decided about its end (ADR-088, migration 0067); the setting itself
    #: is part of the published version. ``None``: nothing is being observed.
    observe_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class GraphVersion(Base):
    """A published version of a pipeline or an action: a frozen copy of its graph (ADR-070). Rows are written once and never changed.

    ``number`` counts per graph from 1 and is never reused. ``content`` is the JSON of what ``graph_of`` returns (nodes, edges, name,
    kind). ``fingerprint`` hashes the parts that decide what runs. ``source_number`` is set when the version was made by publishing an
    earlier one again (a rollback). ``published_via`` is ``user`` (the browser) or ``api``.
    """

    __tablename__ = "graph_versions"
    __table_args__ = (UniqueConstraint("graph_id", "number", name="ux_graph_versions_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    graph_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("graphs.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64))
    source_number: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    published_via: Mapped[str] = mapped_column(String(16))
    published_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


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
