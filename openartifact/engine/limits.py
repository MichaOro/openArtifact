"""Run limits: how many steps and how much time one execution may take (ADR-039).

The values are settings users change on *Settings > Run limits* (rows of ``app_settings``); a value that was
never set has its default, which is what the engine did before: 1000 steps, no time limit. An execution reads
them once, when it starts, and keeps them in its snapshot (``snapshot["limits"]``): changing a limit affects the
executions that start afterwards, never a running one. A snapshot of before ADR-039 has no limits and gets the
defaults.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models import AppSetting
from openartifact.schemas_common import UtcDateTime

MAX_STEPS_DEFAULT, MAX_STEPS_MIN, MAX_STEPS_MAX = 1000, 10, 100_000
TIME_LIMIT_DEFAULT, TIME_LIMIT_MIN, TIME_LIMIT_MAX = 0, 0, 7 * 24 * 60
_KEYS = {"max_steps": "run.max_steps", "time_limit_minutes": "run.time_limit_minutes"}


@dataclass(frozen=True)
class RunLimits:
    """The limits of one execution. ``time_limit_minutes`` 0: no time limit."""

    max_steps: int = MAX_STEPS_DEFAULT
    time_limit_minutes: int = TIME_LIMIT_DEFAULT

    def to_data(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def of_snapshot(cls, snapshot: dict[str, Any]) -> RunLimits:
        """The limits an execution froze at its start; the defaults for an older snapshot."""
        data = snapshot.get("limits")
        if not isinstance(data, dict):
            return cls()
        return cls(
            int(data.get("max_steps", MAX_STEPS_DEFAULT)),
            int(data.get("time_limit_minutes", TIME_LIMIT_DEFAULT)),
        )


class RunLimitsWrite(BaseModel):
    """New limits; a field that is left out keeps its value."""

    model_config = ConfigDict(extra="forbid")

    max_steps: int | None = Field(default=None, ge=MAX_STEPS_MIN, le=MAX_STEPS_MAX)
    time_limit_minutes: int | None = Field(default=None, ge=TIME_LIMIT_MIN, le=TIME_LIMIT_MAX)


class RunLimitsRead(BaseModel):
    """The limits in effect for executions that start now, their bounds, and the limit of parallel runs,
    which is a setting of the operator (``OPENARTIFACT_MAX_CONCURRENT_RUNS``) and read-only here."""

    max_steps: int
    time_limit_minutes: int
    max_steps_bounds: tuple[int, int] = (MAX_STEPS_MIN, MAX_STEPS_MAX)
    time_limit_bounds: tuple[int, int] = (TIME_LIMIT_MIN, TIME_LIMIT_MAX)
    max_concurrent_runs: int
    updated_at: UtcDateTime | None


async def load_limits(session: AsyncSession) -> tuple[RunLimits, Any]:
    """The limits in effect and when they were last changed (``None``: never)."""
    rows = {
        r.key: r
        for r in await session.scalars(select(AppSetting).where(AppSetting.key.in_(_KEYS.values())))
    }
    values: dict[str, int] = {}
    for field, key in _KEYS.items():
        if key in rows:
            values[field] = int(json.loads(rows[key].value))
    changed = max((r.updated_at for r in rows.values()), default=None)
    return RunLimits(**values), changed


async def save_limits(session: AsyncSession, data: RunLimitsWrite) -> None:
    """Store the fields that were sent (the caller commits)."""
    for field in data.model_fields_set:
        value = getattr(data, field)
        if value is None:
            continue
        key = _KEYS[field]
        row = await session.get(AppSetting, key)
        if row is None:
            session.add(AppSetting(key=key, value=json.dumps(value)))
        else:
            row.value = json.dumps(value)
