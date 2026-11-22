"""Pieces the read models share."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import PlainSerializer


def utc_iso(value: datetime) -> str:
    """ISO-8601 in UTC with a ``Z`` suffix. SQLite returns naive datetimes; they are always UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


#: A datetime that is written as ``utc_iso`` says, in every read model.
UtcDateTime = Annotated[datetime, PlainSerializer(utc_iso, return_type=str)]
