"""Settings of the application that users change at run time (ADR-039), one row per key."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from openartifact.database import Base


class AppSetting(Base):
    """One setting: ``key`` (for example ``run.max_steps``) and its ``value`` as JSON text.

    A key without a row has its default (``engine/limits.py``); the service writes only what was set.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
