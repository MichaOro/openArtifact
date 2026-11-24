"""Guards (ADR-060): a library of guard definitions, attached to scopes of pipelines and action definitions (0047, 0049).

A :class:`GuardDefinition` is what a guard *is* (its trigger, condition, escalation, consequence and own action); it is
defined once and reused. A :class:`GuardAttachment` says *where* it watches (a pipeline, one of its stages or one of
its actions; a whole action definition or one node of it) and whether it is switched on there. A change to a
definition acts on every place it is attached to.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from openartifact.database import Base

#: Every scope a guard can watch; the default of a definition's ``scope_types``.
ALL_SCOPES = '["pipeline", "stage", "action", "definition", "node"]'
#: What the column's default in the database says (migration 0047; a default cannot be changed without rebuilding the
#: table, and the ORM always writes ``ALL_SCOPES``).
STORED_DEFAULT_SCOPES = '["pipeline", "stage", "action"]'


class GuardDefinition(Base):
    """A guard of the library.

    Attributes:
        name, description: How it is shown (the name is required, not unique).
        scope_types: JSON list: the kinds of scope it may be attached to (``pipeline``, ``stage``, ``action``,
            ``definition``, ``node``).
        trigger: JSON: ``{"type": "event", "events": [...]}`` or ``{"type": "interval", "every_seconds",
            "for_seconds", "cooldown_seconds"}``.
        condition: JSON: the condition tree (``when``, the ``guard`` schema of ``rules/catalog.py``).
        consequence: ``pause``, ``abort``, ``continue`` or ``run_action`` (``notify`` and ``handover`` are declared,
            not available yet).
        fallback: What follows when the guard's own action fails: ``pause``, ``abort`` or ``continue``.
        escalation: JSON list of steps ``{"from_firing", "every_runs" | "every_seconds"}``.
        action_id: The guard's own action (an action definition), run by ``run_action``.
    """

    __tablename__ = "guard_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    scope_types: Mapped[str] = mapped_column(
        Text, default=ALL_SCOPES, server_default=STORED_DEFAULT_SCOPES
    )
    trigger: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    condition: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    consequence: Mapped[str] = mapped_column(String(16), default="pause", server_default="pause")
    fallback: Mapped[str] = mapped_column(String(16), default="pause", server_default="pause")
    escalation: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    action_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("graphs.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class GuardAttachment(Base):
    """A guard definition attached to a scope of a pipeline or of an action definition.

    Attributes:
        guard_id: The definition (a definition with attachments cannot be deleted).
        graph_id: The graph that holds the scope: a pipeline (``pipeline``, ``stage``, ``action``) or an action
            definition (``definition``, ``node``). The attachment goes with it.
        scope_type, scope_id: What it watches: ``pipeline`` or ``definition`` (``scope_id`` is the graph's id),
            ``stage`` or ``action`` (a node id of the pipeline), ``node`` (a node id of the action definition); the
            attachment goes with the node.
        enabled: Off: it does not watch (acts at once on running executions).
    """

    __tablename__ = "guard_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guard_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("guard_definitions.id", ondelete="CASCADE"), index=True
    )
    graph_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("graphs.id", ondelete="CASCADE"), index=True
    )
    scope_type: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[str] = mapped_column(String(36))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
