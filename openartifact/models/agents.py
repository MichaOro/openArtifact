"""Agents, their published versions, LLM providers and their models (ADR-037)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from openartifact.database import Base


class LlmProvider(Base):
    """A place agents send their requests to.

    Attributes:
        kind: See :class:`ProviderKind`. There is at most one ``openrouter`` row.
        base_url: The address of an OpenAI-compatible endpoint (``None`` for OpenRouter, whose address
            is fixed in the code).
        secret_name: The name of the secret that holds the API key (``None``: no key is sent). Never the
            key itself.
        allow_http: The owner's confirmation that an ``http://`` address is fine (the key and the prompts
            travel unencrypted): a local model server, or TLS in front of it. Any address may be local.
        default_model: The model used when neither the agent nor the node names one.
        is_default: The provider used when neither the agent nor the node names one (at most one row).
        checked_at, check_ok, check_message: The last connection test.
    """

    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(60, collation="NOCASE"), unique=True)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    secret_name: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    allow_http: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    default_model: Mapped[str | None] = mapped_column(String(200), nullable=True, default=None)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    checked_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
    check_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    check_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class LlmModel(Base):
    """A model of a provider: fetched from its ``/models`` or defined by hand.

    Only a model that is ``enabled`` and ``available`` can be chosen for an agent. A fetched model that
    the provider no longer lists stays, with ``available`` false, because configurations may name it.
    """

    __tablename__ = "llm_models"
    __table_args__ = (UniqueConstraint("provider_id", "model_id", name="ux_llm_models_provider"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("llm_providers.id", ondelete="CASCADE"), index=True
    )
    model_id: Mapped[str] = mapped_column(String(200))
    label: Mapped[str] = mapped_column(String(200), default="", server_default="")
    source: Mapped[str] = mapped_column(String(16))  # "fetched" or "manual"
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    available: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class Agent(Base):
    """A reusable agent definition: what an agent node refers to.

    ``draft`` is the editable configuration (JSON text, see ``agents/schemas.py``); it takes effect only
    when it is published, which copies it into a new ``AgentVersion``. ``published_number`` is the
    version executions use (``None``: never published); ``version_seq`` is the last number handed out.
    An inactive agent is not run.
    """

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100, collation="NOCASE"), unique=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    draft: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    published_number: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    version_seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class AgentVersion(Base):
    """A published configuration of an agent. Rows are written once and never changed.

    ``number`` counts per agent from 1 and is never reused. ``source_number`` is set when the version
    was made by publishing an earlier one again (a rollback): its content equals that version's.
    ``published_via`` is ``user`` (the browser) or ``api``.
    """

    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "number", name="ux_agent_versions_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    config: Mapped[str] = mapped_column(Text)
    source_number: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    published_via: Mapped[str] = mapped_column(String(16))
    published_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
