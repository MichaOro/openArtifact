"""The emergency stop (ADR-076): one global switch that blocks every execution.

While it is on, no execution starts from any source (browser, API, MCP, anything automatic) and every execution that
runs is aborted at the moment it is switched on. Cards, pipelines, actions, guards and the history keep working; only
the execution is blocked. The state is one row of ``app_settings`` (``execution.stop``), so it survives a restart: a new
system has no row, which means off.

Whether the switch is *offered* (the button, the API and the MCP tools) is a personal setting (``show_stop_switch``);
that is the service's business (``tasks/service.py``), this module only stores and reads the state.
"""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models.settings import AppSetting

KEY = "execution.stop"
#: The machine word of a refused start (``code`` of the 409 answer).
CODE = "stopped"
MESSAGE = (
    "The emergency stop is on: pipeline processing is stopped. Switch it off to start executions."
)
#: The note of an execution that the switch aborted (shown in the list and the history).
NOTE = "EMERGENCY STOP"


class StopState(BaseModel):
    """What the switch says now."""

    #: Whether the emergency stop is on.
    active: bool
    #: Since when (UTC) while it is on, else ``None``.
    since: datetime | None = None
    #: Whether the feature is switched on in the personal settings (``show_stop_switch``): the button, the API and the MCP set it only then.
    available: bool = False
    #: How many executions run right now (what switching the emergency stop on would abort).
    running: int = 0
    #: How many executions this change aborted (only in the answer of a change to on).
    aborted: int = 0


async def load(session: AsyncSession) -> tuple[bool, datetime | None]:
    """Whether the emergency stop is on and since when; no row, or a row that does not read, is off."""
    row = await session.get(AppSetting, KEY)
    if row is None:
        return False, None
    try:
        data = json.loads(row.value)
        active = data["active"] is True
        since = datetime.fromisoformat(data["since"]) if active and data.get("since") else None
    except (ValueError, KeyError, TypeError):
        return False, None
    return active, since


async def store(session: AsyncSession, active: bool, now: datetime) -> None:
    """Write the state (the caller commits)."""
    value = json.dumps({"active": active, "since": now.isoformat() if active else None})
    row = await session.get(AppSetting, KEY)
    if row is None:
        session.add(AppSetting(key=KEY, value=value))
    else:
        row.value = value
