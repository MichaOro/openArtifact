"""A custom artifact field may not take a name the card has by itself (ADR-064).

Revision ID: 0051
Revises: 0050
Create Date: 2026-11-24

Every artifact is a source of its run as ``${card.title}``, ``${card.body}``, ``${card.number}``, ``${card.id}`` and
``${card.text}``. From now on a custom field cannot be named like one of them. A field that already is gets the suffix
``_field`` (``title`` becomes ``title_field``, another number is added when that name is taken), in three places:

* ``artifact_fields.name`` (the field list),
* the keys of ``tasks.field_values`` (the values of the artifacts),
* the references ``${card.title}`` in the settings of the nodes (``graph_nodes.config`` text), which meant the field.

Only values and text change, no table is rebuilt (see 0043). The executions that ran before keep what they recorded.
The downgrade takes the suffix off again where the plain name is free.
"""

import json
import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RESERVED = ("title", "body", "number", "id", "text")
SUFFIX = "_field"


def _rename_everywhere(bind: sa.engine.Connection, pairs: dict[str, str]) -> None:
    if not pairs:
        return
    for old, new in pairs.items():
        bind.execute(
            sa.text("UPDATE artifact_fields SET name = :new WHERE name = :old"),
            {"new": new, "old": old},
        )
    for task_id, raw in bind.execute(
        sa.text("SELECT id, field_values FROM tasks WHERE field_values != '{}'")
    ).fetchall():
        values = json.loads(raw or "{}")
        if not isinstance(values, dict) or not any(key in values for key in pairs):
            continue
        renamed = {pairs.get(key, key): value for key, value in values.items()}
        bind.execute(
            sa.text("UPDATE tasks SET field_values = :values WHERE id = :id"),
            {"values": json.dumps(renamed, ensure_ascii=False), "id": task_id},
        )
    for node_id, raw in bind.execute(
        sa.text("SELECT id, config FROM graph_nodes WHERE config LIKE '%${card.%'")
    ).fetchall():
        text = raw if isinstance(raw, str) else json.dumps(raw)
        changed = text
        for old, new in pairs.items():
            changed = re.sub(r"\$\{card\." + re.escape(old) + r"\}", "${card." + new + "}", changed)
        if changed != text:
            bind.execute(
                sa.text("UPDATE graph_nodes SET config = :config WHERE id = :id"),
                {"config": changed, "id": node_id},
            )


def upgrade() -> None:
    bind = op.get_bind()
    taken = {r[0] for r in bind.execute(sa.text("SELECT name FROM artifact_fields")).fetchall()}
    pairs: dict[str, str] = {}
    for old in RESERVED:
        if old not in taken:
            continue
        new, n = old + SUFFIX, 1
        while new in taken or new in pairs.values():
            n += 1
            new = f"{old}{SUFFIX}{n}"
        pairs[old] = new
    _rename_everywhere(bind, pairs)


def downgrade() -> None:
    bind = op.get_bind()
    taken = {r[0] for r in bind.execute(sa.text("SELECT name FROM artifact_fields")).fetchall()}
    pairs = {old + SUFFIX: old for old in RESERVED if old + SUFFIX in taken and old not in taken}
    _rename_everywhere(bind, pairs)
