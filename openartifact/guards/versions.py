"""The published versions of a guard definition (ADR-081): what a version holds, what tells a draft from it, and publishing.

A definition's own columns are its **draft**; a version is a frozen copy (``GuardVersion``). Only a published version is in effect:
an execution freezes the published version of every guard that applies to it when it starts (``engine/snapshot.py``), and a
definition that was never published watches nothing. Switching an attachment on or off is not part of a version: it acts at once.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.exceptions import ArtifactError
from openartifact.models import GuardDefinition, GuardVersion


def content_of(row: GuardDefinition) -> dict[str, Any]:
    """What a version holds: the definition with its JSON columns parsed (the keys of the API's ``when``, not of the column)."""
    return {
        "name": row.name,
        "description": row.description or "",
        "scope_types": json.loads(row.scope_types or "[]"),
        "trigger": json.loads(row.trigger or "{}"),
        "when": json.loads(row.condition or "{}"),
        "consequence": row.consequence,
        "fallback": row.fallback,
        "escalation": json.loads(row.escalation or "[]"),
        "action_id": row.action_id,
    }


def dump(content: dict[str, Any]) -> str:
    """The text a version stores (and its fingerprint hashes): the same for the same content."""
    return json.dumps(content, sort_keys=True, default=str)


def fingerprint(content: dict[str, Any]) -> str:
    """A hash of everything a definition holds: any difference between the draft and the published version shows."""
    return hashlib.sha256(dump(content).encode()).hexdigest()


def restore(row: GuardDefinition, content: dict[str, Any]) -> None:
    """Make the draft (the columns of ``row``) what a version holds."""
    row.name = str(content.get("name") or row.name)
    row.description = str(content.get("description") or "")
    row.scope_types = json.dumps(content.get("scope_types", []))
    row.trigger = json.dumps(content.get("trigger", {}))
    row.condition = json.dumps(content.get("when", {}))
    row.consequence = str(content.get("consequence") or "pause")
    row.fallback = str(content.get("fallback") or "pause")
    row.escalation = json.dumps(content.get("escalation", []))
    row.action_id = content.get("action_id")


async def versions_of(session: AsyncSession, guard_id: str) -> Sequence[GuardVersion]:
    """Every published version of a definition, newest first."""
    rows = await session.scalars(
        select(GuardVersion)
        .where(GuardVersion.guard_id == guard_id)
        .order_by(GuardVersion.number.desc())
    )
    return rows.all()


async def get_version(session: AsyncSession, guard_id: str, number: int) -> GuardVersion | None:
    return await session.scalar(
        select(GuardVersion).where(GuardVersion.guard_id == guard_id, GuardVersion.number == number)
    )


async def current_version(session: AsyncSession, row: GuardDefinition) -> GuardVersion | None:
    """The version executions use, or ``None`` (never published: the guard watches nothing)."""
    if row.published_number is None:
        return None
    return await get_version(session, row.id, row.published_number)


async def next_number(session: AsyncSession, guard_id: str) -> int:
    last = await session.scalar(
        select(GuardVersion.number)
        .where(GuardVersion.guard_id == guard_id)
        .order_by(GuardVersion.number.desc())
        .limit(1)
    )
    return (last or 0) + 1


async def draft_changed(session: AsyncSession, row: GuardDefinition) -> bool:
    """Whether the draft differs from the published version (``False`` while nothing is published)."""
    version = await current_version(session, row)
    if version is None:
        return False
    return fingerprint(content_of(row)) != version.fingerprint


async def published_numbers(session: AsyncSession) -> dict[str, int | None]:
    """The published version of every definition: ``{guard id: number or None}`` (one query)."""
    rows = await session.execute(select(GuardDefinition.id, GuardDefinition.published_number))
    return {guard_id: number for guard_id, number in rows.all()}


async def publish(session: AsyncSession, row: GuardDefinition, via: str) -> GuardVersion:
    """Publish the draft as a new version. 409 when it equals the published one (nothing would change)."""
    content = content_of(row)
    digest = fingerprint(content)
    current = await current_version(session, row)
    if current is not None and current.fingerprint == digest:
        raise ArtifactError(
            409, f"Nothing changed since version {current.number}: there is nothing new to publish"
        )
    version = GuardVersion(
        id=str(uuid.uuid4()),
        guard_id=row.id,
        number=await next_number(session, row.id),
        content=dump(content),
        fingerprint=digest,
        source_number=None,
        published_via=via,
    )
    session.add(version)
    row.published_number = version.number
    await session.flush()
    return version


async def republish(
    session: AsyncSession, row: GuardDefinition, number: int, via: str
) -> GuardVersion:
    """Publish an earlier version again (a rollback): a new version with that version's content; the history stays and the draft is
    not touched (it is shown as changed when it differs)."""
    source = await get_version(session, row.id, number)
    if source is None:
        raise ArtifactError(404, f"Version {number} does not exist")
    if row.published_number == number:
        raise ArtifactError(409, f"Version {number} is the published one already")
    version = GuardVersion(
        id=str(uuid.uuid4()),
        guard_id=row.id,
        number=await next_number(session, row.id),
        content=source.content,
        fingerprint=source.fingerprint,
        source_number=number,
        published_via=via,
    )
    session.add(version)
    row.published_number = version.number
    await session.flush()
    return version


async def discard_draft(session: AsyncSession, row: GuardDefinition) -> GuardVersion:
    """Throw the changes of the draft away: it becomes the published version again. 409 while nothing is published (there is no
    version to go back to) and when the draft equals the published version (nothing to discard)."""
    version = await current_version(session, row)
    if version is None:
        raise ArtifactError(409, "Nothing is published yet: there is no version to go back to")
    if fingerprint(content_of(row)) == version.fingerprint:
        raise ArtifactError(
            409, f"The draft equals version {version.number}: there is nothing to discard"
        )
    restore(row, json.loads(version.content))
    await session.flush()
    return version
