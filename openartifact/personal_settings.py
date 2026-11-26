"""The personal settings of the (single) user: display preferences kept in ``app_settings`` under ``personal.<name>``.

What exists, its kind and its default is declared once, in the form manifest ``ui/forms/personal.yaml`` (ADR-062): this module
reads the defaults from there, the settings API (``api/settings.py``) and the artifact service read and write through it.
A key without a row has its default; only what was set is written.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models.settings import AppSetting
from openartifact.ui.forms import FORMS

FORM = "personal"
PREFIX = "personal."


def defaults() -> dict[str, Any]:
    """Every personal setting with its default, as the manifest declares them."""
    return {
        field.key: field.default for section in FORMS[FORM].sections for field in section.fields
    }


async def load(session: AsyncSession) -> dict[str, Any]:
    """The settings as stored, with the default for what was never set (keys of the manifest only)."""
    values = defaults()
    rows = await session.execute(select(AppSetting).where(AppSetting.key.like(f"{PREFIX}%")))
    for row in rows.scalars():
        name = row.key.removeprefix(PREFIX)
        if name in values:
            try:
                values[name] = json.loads(row.value)
            except ValueError:  # a hand-edited row: the default applies
                continue
    return values


async def save(session: AsyncSession, changes: Mapping[str, Any]) -> None:
    """Store the given settings (the caller has validated them); a name the manifest does not declare is refused."""
    known = defaults()
    for name, value in changes.items():
        if name not in known:
            raise KeyError(name)
        key = f"{PREFIX}{name}"
        stored = json.dumps(value)
        existing = await session.get(AppSetting, key)
        if existing is None:
            session.add(AppSetting(key=key, value=stored))
        else:
            existing.value = stored


async def marks_resolved_references(session: AsyncSession) -> bool:
    """Whether the text a ``${card.x}`` stands for is marked where artifacts are read (board card, artifact dialog)."""
    return bool((await load(session))["mark_resolved_references"])


async def stop_switch_available(session: AsyncSession) -> bool:
    """Whether the STOP switch is offered (the button, the API and MCP set it only then; ADR-076)."""
    return bool((await load(session))["show_stop_switch"])
