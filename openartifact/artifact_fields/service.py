"""Artifact fields: the one list of fields every artifact has, for every way in (ADR-044).

:class:`ArtifactFieldService` reads and replaces the list. The functions below it are what
:class:`~openartifact.tasks.service.ArtifactService` and the run engine use: they check the field values of
an artifact when it is saved and hand a run its ``card``. A refusal is an ``ArtifactError`` (422 for a value
or definition that is wrong, 409 when stored values would no longer fit).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.artifact_fields import rules
from openartifact.artifact_fields.rules import FieldSpec
from openartifact.artifact_fields.schemas import (
    ArtifactFieldsRead,
    ArtifactFieldsWrite,
    FieldRead,
    FieldWrite,
)
from openartifact.database import SessionOpener
from openartifact.events import EventBus
from openartifact.exceptions import ArtifactError
from openartifact.models import ArtifactField, Task

CHANGED = "artifact_fields.changed"


def _spec_of(row: ArtifactField) -> FieldSpec:
    return FieldSpec(
        name=row.name,
        label=row.label,
        kind=row.kind,
        default=json.loads(row.default_json) if row.default_json is not None else None,
        options=tuple(json.loads(row.options_json)) if row.options_json else (),
        max_length=row.max_length,
        min_value=row.min_value,
        max_value=row.max_value,
        integer_only=row.integer_only,
        multiple=row.multiple,
    )


def _spec_of_write(item: FieldWrite) -> FieldSpec:
    return FieldSpec(
        name=item.name,
        label=item.label.strip(),
        kind=item.kind,
        default=None if rules.is_blank(item.default) else item.default,
        options=tuple(item.options),
        max_length=item.max_length,
        min_value=item.min_value,
        max_value=item.max_value,
        integer_only=item.integer_only,
        multiple=item.multiple,
    )


def _row_of(position: int, spec: FieldSpec) -> ArtifactField:
    return ArtifactField(
        name=spec.name,
        label=spec.label,
        kind=spec.kind,
        default_json=None if spec.default is None else json.dumps(spec.default),
        options_json=json.dumps(list(spec.options)) if spec.options else None,
        max_length=spec.max_length,
        min_value=spec.min_value,
        max_value=spec.max_value,
        integer_only=spec.integer_only,
        multiple=spec.multiple,
        position=position,
    )


def _read_field(spec: FieldSpec, count: int) -> FieldRead:
    return FieldRead(
        name=spec.name,
        label=spec.label,
        kind=spec.kind,
        default=spec.default,
        options=list(spec.options),
        max_length=spec.max_length,
        min_value=spec.min_value,
        max_value=spec.max_value,
        integer_only=spec.integer_only,
        multiple=spec.multiple,
        artifact_count=count,
    )


async def field_specs(session: AsyncSession) -> list[FieldSpec]:
    """The fields in their order."""
    rows = await session.scalars(select(ArtifactField).order_by(ArtifactField.position))
    return [_spec_of(r) for r in rows]


def stored_values(task: Task) -> dict[str, Any]:
    """The field values stored with an artifact."""
    try:
        data = json.loads(task.field_values or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _text(values: dict[str, Any]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _carried(
    before: FieldSpec | None, after: FieldSpec, value: Any, renames: dict[str, str]
) -> Any:
    """A stored value of a choice after its field changed (ADR-050): renamed allowed values follow, removed ones
    go, and a single value becomes a list of one (and back, when one is left). Other kinds are left as they are."""
    if before is None or before.kind != "choice" or after.kind != "choice":
        return value
    items = value if isinstance(value, list) else [value]
    kept = [renames.get(v, v) for v in items if isinstance(v, str)]
    kept = [v for v in kept if v in after.options]
    if after.multiple:
        return kept or None
    if not kept:
        return None
    return (
        kept[0] if len(kept) == 1 else kept
    )  # several values: left to the check (it does not fit)


def _plural(count: int) -> str:
    return "1 artifact has" if count == 1 else f"{count} artifacts have"


class ArtifactFieldService:
    """Read and replace the list of artifact fields; publishes ``artifact_fields.changed``."""

    def __init__(self, session: SessionOpener, bus: EventBus) -> None:
        self._session = session
        self._bus = bus

    @staticmethod
    async def _read(session: AsyncSession) -> ArtifactFieldsRead:
        specs = await field_specs(session)
        counts = dict.fromkeys((s.name for s in specs), 0)
        for raw in await session.scalars(select(Task.field_values)):
            try:
                values = json.loads(raw or "{}")
            except ValueError:
                continue
            for name in values if isinstance(values, dict) else ():
                if name in counts:
                    counts[name] += 1
        return ArtifactFieldsRead(fields=[_read_field(s, counts[s.name]) for s in specs])

    async def list_fields(self) -> ArtifactFieldsRead:
        async with self._session() as session:
            return await self._read(session)

    async def replace(self, data: ArtifactFieldsWrite) -> ArtifactFieldsRead:
        """Replace the whole list. A removed field takes its values with it; a changed field is refused
        (409) when stored values no longer fit it."""
        specs = [_spec_of_write(item) for item in data.fields]
        if problems := rules.check_definitions(specs):
            raise ArtifactError(422, "\n".join(problems))
        renames = {item.name: item.renamed_options for item in data.fields}
        async with self._session() as session:
            before = {s.name: s for s in await field_specs(session)}
            tasks = (await session.scalars(select(Task))).all()
            misfits: dict[str, int] = {}
            updated: list[tuple[Task, str]] = []
            for task in tasks:
                old = stored_values(task)
                kept = {
                    spec.name: _carried(
                        before.get(spec.name), spec, old[spec.name], renames[spec.name]
                    )
                    for spec in specs
                    if spec.name in old
                }
                stored, problems = rules.validate_values(specs, kept)
                for problem in problems:
                    field = problem.removeprefix("Field ").split(":", 1)[0]
                    misfits[field] = misfits.get(field, 0) + 1
                if not problems and stored != old:
                    updated.append((task, _text(stored)))
            if misfits:
                raise ArtifactError(
                    409,
                    "\n".join(
                        f"Field {name}: {_plural(count)} a value that does not fit the new definition"
                        for name, count in misfits.items()
                    ),
                )
            for task, text in updated:
                task.field_values = text
            await session.execute(delete(ArtifactField))
            session.add_all(_row_of(position, spec) for position, spec in enumerate(specs))
            await session.commit()
            read = await self._read(session)
        self._bus.publish(CHANGED, read.model_dump(mode="json"))
        return read


# ── what artifacts and runs use ──────────────────────────────────────


async def values_of_new(session: AsyncSession, given: dict[str, Any]) -> str:
    """The field values of a new artifact as JSON text: the given ones checked, defaults for the rest."""
    specs = await field_specs(session)
    stored, problems = rules.validate_values(specs, rules.with_defaults(specs, given))
    if problems:
        raise ArtifactError(422, "\n".join(problems))
    return _text(stored)


async def values_of_update(session: AsyncSession, task: Task, changes: dict[str, Any]) -> str:
    """The field values after a change: merged into the stored ones (``null`` clears one)."""
    stored, problems = rules.validate_values(
        await field_specs(session), {**stored_values(task), **changes}
    )
    if problems:
        raise ArtifactError(422, "\n".join(problems))
    return _text(stored)


async def card_of(session: AsyncSession, task: Task) -> dict[str, Any]:
    """The ``card`` a run starts with (ADR-064): what every artifact has (``id``, ``number``, ``title``,
    ``body``; ``${card.text}`` is derived from them when it is read) and then every field with its value,
    else its default, else ``None``. A copy: it is not refreshed while the run goes on."""
    card: dict[str, Any] = {
        "id": task.id,
        "number": task.number,
        "title": task.title,
        "body": task.body or "",
    }
    fields = rules.card_values(await field_specs(session), stored_values(task))
    card.update({name: value for name, value in fields.items() if name not in rules.BUILT_IN_NAMES})
    return card
