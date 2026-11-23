"""The credential store's table (ADR-024) and the metadata of managed credentials (ADR-051)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from openartifact.database import Base


class Secret(Base):
    """A named secret for execution nodes, encrypted at rest (see ``credentials/crypto.py``).

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


class Credential(Base):
    """What every managed credential has (ADR-051): a name, a type of the registry (``credentials/types.py``), its
    category (``internal``: a token OpenArtifact makes; ``external``: a value a user gives for another system), the
    state and where the value lives.

    An external credential's value stays in the credential store (``backend`` ``secret_store``, ``backend_ref`` the
    secret's name, which is the name pipelines write as ``${secret:NAME}``); an internal one has no value at all, only
    hashes of its tokens. Everything that only one category has is in its own table.
    """

    __tablename__ = "credentials"
    __table_args__ = (Index("ux_credentials_name", "name", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(64, collation="NOCASE"))
    category: Mapped[str] = mapped_column(String(16))
    type: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    backend: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    backend_ref: Mapped[str | None] = mapped_column(String(200), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class InternalCredential(Base):
    """The lifecycle of an internal credential: when it ends (``expires_at``), when it was revoked (for good) and
    when a token of it was last used."""

    __tablename__ = "internal_credentials"

    credential_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("credentials.id", ondelete="CASCADE"), primary_key=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)


class InternalToken(Base):
    """One token of an internal credential, by its public identifier (the lookup key) and the SHA-256 of the whole
    token. A rotation adds a token and gives the old one a ``valid_until`` (the grace period); the history stays."""

    __tablename__ = "internal_tokens"
    __table_args__ = (Index("ux_internal_tokens_public_id", "public_id", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    credential_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("credentials.id", ondelete="CASCADE"), index=True
    )
    public_id: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    valid_until: Mapped[datetime | None] = mapped_column(nullable=True, default=None)


class ExternalCredential(Base):
    """What an external credential has besides its value: the type's fields that are not secret (``settings``, JSON)
    and the outcome of the last connection test (never set by anything but a test that ran)."""

    __tablename__ = "external_credentials"

    credential_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("credentials.id", ondelete="CASCADE"), primary_key=True
    )
    settings: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    last_test_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    last_test_message: Mapped[str | None] = mapped_column(String(300), nullable=True, default=None)


class CredentialEvent(Base):
    """An entry of the audit trail: what happened to which credential and when. It carries no value and no hash,
    and it outlives the credential (no foreign key)."""

    __tablename__ = "credential_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    credential_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(String(300), default="", server_default="")
    at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), index=True)
