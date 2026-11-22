"""Artifact types and the parameters of artifacts: the rules, once, for every way in (ADR-035).

:class:`ArtifactTypeService` is the CRUD of types. The functions below it are what
:class:`~openartifact.tasks.service.ArtifactService` and the run engine use: they check the type and
parameters of an artifact when it is saved and hand a run its ``card``. A refusal is an
``ArtifactError`` (422 for a value or definition that is wrong, 409 when the state forbids it).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.artifact_types import fields as rules
from openartifact.artifact_types.fields import FieldSpec
from openartifact.artifact_types.schemas import (
    MAX_TYPES,
    ArtifactTypeRead,
    ArtifactTypeWrite,
    FieldRead,
    FieldWrite,
)
from openartifact.database import SessionOpener
from openartifact.events import EventBus
from openartifact.exceptions import ArtifactError
from openartifact.models import ArtifactType, ArtifactTypeField, Task


def _plural(count: int) -> str:
    return "1 artifact uses" if count == 1 else f"{count} artifacts use"


def _spec_of(row: ArtifactTypeField) -> FieldSpec:
    return FieldSpec(
        name=row.name,
        label=row.label,
        kind=row.kind,
        required=row.required,
        default=json.loads(row.default_json) if row.default_json is not None else None,
        options=tuple(json.loads(row.options_json)) if row.options_json else (),
        max_length=row.max_length,
        min_value=row.min_value,
        max_value=row.max_value,
        integer_only=row.integer_only,
    )


def _spec_of_write(item: FieldWrite) -> FieldSpec:
    return FieldSpec(
        name=item.name,
        label=item.label.strip(),
        kind=item.kind,
        required=item.required,
        default=None if rules.is_blank(item.default) else item.default,
        options=tuple(item.options),
        max_length=item.max_length,
        min_value=item.min_value,
        max_value=item.max_value,
        integer_only=item.integer_only,
    )


def _row_of(type_id: str, position: int, spec: FieldSpec) -> ArtifactTypeField:
    return ArtifactTypeField(
        type_id=type_id,
        name=spec.name,
        label=spec.label,
        kind=spec.kind,
        required=spec.required,
        default_json=None if spec.default is None else json.dumps(spec.default),
        options_json=json.dumps(list(spec.options)) if spec.options else None,
        max_length=spec.max_length,
        min_value=spec.min_value,
        max_value=spec.max_value,
        integer_only=spec.integer_only,
        position=position,
    )


def _read_field(spec: FieldSpec) -> FieldRead:
    return FieldRead(
        name=spec.name,
        label=spec.label,
        kind=spec.kind,
        required=spec.required,
        default=spec.default,
        options=list(spec.options),
        max_length=spec.max_length,
        min_value=spec.min_value,
        max_value=spec.max_value,
        integer_only=spec.integer_only,
    )


async def _fields(session: AsyncSession, type_id: str) -> list[FieldSpec]:
    rows = await session.scalars(
        select(ArtifactTypeField)
        .where(ArtifactTypeField.type_id == type_id)
        .order_by(ArtifactTypeField.position)
    )
    return [_spec_of(r) for r in rows]


async def _find(session: AsyncSession, ref: str) -> ArtifactType | None:
    """A type by id or by name (ignoring case)."""
    found = await session.get(ArtifactType, ref)
    if found is None:
        found = await session.scalar(select(ArtifactType).where(ArtifactType.name == ref.strip()))
    return found


async def _count(session: AsyncSession, type_id: str) -> int:
    return await session.scalar(select(func.count()).where(Task.type_id == type_id)) or 0


class ArtifactTypeService:
    """List, create, replace and delete artifact types; publishes ``artifact_types.changed``."""

    def __init__(self, session: SessionOpener, bus: EventBus) -> None:
        self._session = session
        self._bus = bus

    async def _read_all(self, session: AsyncSession) -> list[ArtifactTypeRead]:
        types = (await session.scalars(select(ArtifactType).order_by(ArtifactType.name))).all()
        counts = dict(
            (
                await session.execute(
                    select(Task.type_id, func.count())
                    .where(Task.type_id.is_not(None))
                    .group_by(Task.type_id)
                )
            )
            .tuples()
            .all()
        )
        by_type: dict[str, list[FieldSpec]] = {t.id: [] for t in types}
        rows = await session.scalars(select(ArtifactTypeField).order_by(ArtifactTypeField.position))
        for row in rows:
            by_type[row.type_id].append(_spec_of(row))
        return [
            ArtifactTypeRead(
                id=t.id,
                name=t.name,
                fields=[_read_field(f) for f in by_type[t.id]],
                artifact_count=counts.get(t.id, 0),
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
            for t in types
        ]

    async def list_all(self) -> list[ArtifactTypeRead]:
        """All types by name, with their parameters and how many artifacts use each."""
        async with self._session() as session:
            return await self._read_all(session)

    async def get(self, ref: str) -> ArtifactTypeRead:
        """One type by id or name."""
        async with self._session() as session:
            found = await _find(session, ref)
            if found is None:
                raise ArtifactError(404, "Artifact type not found")
            return next(t for t in await self._read_all(session) if t.id == found.id)

    async def create(self, data: ArtifactTypeWrite) -> ArtifactTypeRead:
        """Create a type; 409 for a name that exists (ignoring case), 422 for a wrong definition."""
        specs = self._checked(data)
        async with self._session() as session:
            count = await session.scalar(select(func.count()).select_from(ArtifactType))
            if (count or 0) >= MAX_TYPES:
                raise ArtifactError(409, f"At most {MAX_TYPES} artifact types")
            await self._free_name(session, data.name)
            type_id = str(uuid.uuid4())
            session.add(ArtifactType(id=type_id, name=data.name))
            await session.flush()
            session.add_all(_row_of(type_id, i, s) for i, s in enumerate(specs))
            await session.commit()
            types = await self._read_all(session)
        self._publish(types)
        return next(t for t in types if t.id == type_id)

    async def replace(self, ref: str, data: ArtifactTypeWrite) -> ArtifactTypeRead:
        """Replace the name and the parameter list. While artifacts use the type, changes that could
        make their stored values invalid are refused with 409 (see ``fields.breaking_changes``)."""
        specs = self._checked(data)
        async with self._session() as session:
            found = await _find(session, ref)
            if found is None:
                raise ArtifactError(404, "Artifact type not found")
            if data.name.lower() != found.name.lower():
                await self._free_name(session, data.name)
            used = await _count(session, found.id)
            old = await _fields(session, found.id)
            if used and (broken := rules.breaking_changes(old, specs)):
                raise ArtifactError(
                    409, f"{_plural(used).capitalize()} this type. " + "\n".join(broken)
                )
            found.name = data.name
            for row in (
                await session.scalars(
                    select(ArtifactTypeField).where(ArtifactTypeField.type_id == found.id)
                )
            ).all():
                await session.delete(row)
            await session.flush()
            session.add_all(_row_of(found.id, i, s) for i, s in enumerate(specs))
            await session.commit()
            types = await self._read_all(session)
            type_id = found.id
        self._publish(types)
        return next(t for t in types if t.id == type_id)

    async def delete(self, ref: str) -> None:
        """Delete a type with its parameters; 409 while artifacts use it."""
        async with self._session() as session:
            found = await _find(session, ref)
            if found is None:
                raise ArtifactError(404, "Artifact type not found")
            used = await _count(session, found.id)
            if used:
                raise ArtifactError(
                    409,
                    f'Artifact type "{found.name}" cannot be deleted: {_plural(used)} it. '
                    "Change or delete those artifacts first.",
                )
            await session.delete(found)
            await session.commit()
            types = await self._read_all(session)
        self._publish(types)

    async def resolve_id(self, ref: str) -> str:
        """The id of the type a name or id stands for; 422 naming the types that exist otherwise."""
        async with self._session() as session:
            found = await _find(session, ref)
            if found is not None:
                return found.id
            names = ", ".join(t.name for t in await session.scalars(select(ArtifactType))) or "none"
        raise ArtifactError(422, f'Unknown artifact type "{ref[:60]}". Available: {names}')

    async def names(self) -> dict[str, str]:
        """The names of the types by id (for tools that show the name next to the id)."""
        async with self._session() as session:
            return {t.id: t.name for t in await session.scalars(select(ArtifactType))}

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _checked(data: ArtifactTypeWrite) -> list[FieldSpec]:
        if any(ord(c) < 32 for c in data.name):
            raise ArtifactError(422, "Name: no control characters")
        specs = [_spec_of_write(f) for f in data.fields]
        if problems := rules.check_definitions(specs):
            raise ArtifactError(422, "\n".join(problems))
        return specs

    @staticmethod
    async def _free_name(session: AsyncSession, name: str) -> None:
        if await session.scalar(select(ArtifactType.id).where(ArtifactType.name == name)):
            raise ArtifactError(409, f'An artifact type named "{name}" already exists')

    def _publish(self, types: list[ArtifactTypeRead]) -> None:
        self._bus.publish(
            "artifact_types.changed", {"types": [t.model_dump(mode="json") for t in types]}
        )


# ── what artifacts and runs use ──────────────────────────────────────

NO_TYPE = "This artifact has no type; choose a type before setting parameters"


@dataclass(frozen=True)
class Assignment:
    """The type and the parameters (JSON text) an artifact is to be saved with."""

    type_id: str | None
    values: dict[str, Any]

    @property
    def text(self) -> str:
        return json.dumps(self.values, ensure_ascii=False, separators=(",", ":"))


def stored_values(task: Task) -> dict[str, Any]:
    """The parameters stored with an artifact."""
    try:
        data = json.loads(task.parameters or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def _assign(
    session: AsyncSession, type_id: str | None, values: dict[str, Any], hint: str = ""
) -> Assignment:
    if type_id is None:
        if values:
            raise ArtifactError(422, NO_TYPE)
        return Assignment(None, {})
    found = await session.get(ArtifactType, type_id)
    if found is None:
        raise ArtifactError(422, "Artifact type not found")
    stored, problems = rules.validate_parameters(
        await _fields(session, type_id), values, type_name=found.name
    )
    if problems:
        raise ArtifactError(422, "\n".join(problems) + hint)
    return Assignment(type_id, stored)


async def assign_new(
    session: AsyncSession, type_id: str | None, values: dict[str, Any]
) -> Assignment:
    """Check the type and parameters of a new artifact (defaults filled in)."""
    return await _assign(session, type_id, values)


async def assign_update(
    session: AsyncSession,
    task: Task,
    *,
    type_id: str | None,
    type_sent: bool,
    values: dict[str, Any] | None,
    reset: bool,
) -> Assignment:
    """Check the change of an artifact's type and/or parameters.

    The sent values are merged into the stored ones (``null`` clears one back to its default).
    Changing the type keeps the stored values only if they are all valid for the new type; otherwise
    422, unless ``reset`` drops them first.
    """
    new_type = type_id if type_sent else task.type_id
    old = stored_values(task)
    keep = {} if reset else old
    merged = {**keep, **(values or {})}
    changing = new_type != task.type_id
    if new_type is None and merged:
        if values:
            raise ArtifactError(422, NO_TYPE)
        raise ArtifactError(
            422,
            f"Removing the type would drop the parameters {', '.join(merged)}. "
            "Send reset_parameters: true to drop them.",
        )
    hint = ""
    if changing and old and not reset:
        hint = "\nSend reset_parameters: true to change the type and drop the old values."
    return await _assign(session, new_type, merged, hint)


async def card_of(session: AsyncSession, task: Task) -> dict[str, Any]:
    """The ``card`` a run starts with: the artifact's parameters by name (empty without a type)."""
    if task.type_id is None:
        return {}
    return rules.card_values(await _fields(session, task.type_id), stored_values(task))
