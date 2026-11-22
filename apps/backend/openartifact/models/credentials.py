"""The credential store's table (ADR-024)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Index,
    LargeBinary,
    String,
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
