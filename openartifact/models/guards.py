"""Guards (ADR-060): specialised actions attached to a scope of a pipeline (migration 0046)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from openartifact.database import Base


class Guard(Base):
    """A guard of a pipeline.

    Attributes:
        pipeline_id: The pipeline the guard belongs to (it goes with it).
        scope_type, scope_id: What it watches: ``pipeline`` (``scope_id`` is the pipeline's id), ``stage`` or
            ``action`` (a node id of the pipeline). A guard on a guard does not exist.
        trigger: JSON: ``{"type": "event", "events": [...]}`` or ``{"type": "interval", "every_seconds",
            "for_seconds", "cooldown_seconds"}``.
        condition: JSON: the condition tree (``when``, the ``guard`` schema of ``rules/catalog.py``).
        consequence: ``pause``, ``abort``, ``continue`` or ``run_action`` (``notify`` and ``handover`` are declared,
            not available yet).
        fallback: What follows when the guard's own action fails: ``pause``, ``abort`` or ``continue``.
        escalation: JSON list of steps ``{"from_firing", "every_runs" | "every_seconds"}``.
        definition_id: The guard's own action (an action definition), run by ``run_action``.
    """

    __tablename__ = "guards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pipeline_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("graphs.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    scope_type: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trigger: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    condition: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    consequence: Mapped[str] = mapped_column(String(16), default="pause", server_default="pause")
    fallback: Mapped[str] = mapped_column(String(16), default="pause", server_default="pause")
    escalation: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    definition_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("graphs.id", ondelete="SET NULL"), nullable=True, default=None
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
