"""Guards on an action definition and on a node of it: the holder of an attachment is any graph (ADR-060 addendum).

Revision ID: 0049
Revises: 0048
Create Date: 2026-11-24

An attachment put a guard definition on a pipeline, a stage or an action node of a *pipeline* (``pipeline_id``). Now it
can also watch a whole action definition (``scope_type = definition``: wherever the action is used) and one node of an
action definition (``scope_type = node``). The graph that holds the scope is therefore not always a pipeline:
``guard_attachments.pipeline_id`` is renamed ``graph_id`` (the same values, the same foreign key and cascade: the
attachments go with their graph). Existing attachments are untouched.

"Can watch" is no longer a real restriction (it is hidden in the editor): a definition that allowed all of pipeline,
stage and action (every definition made before this, except the ones the Health template made for a stage) now also
allows ``definition`` and ``node``. A definition that was narrowed stays as it is.

Only ``ALTER TABLE .. RENAME COLUMN``, an index renamed and UPDATEs of the JSON text: no table is rebuilt (see 0043). The
downgrade removes the attachments of the two new kinds (they would not fit the old rule that the holder is a pipeline),
takes ``definition`` and ``node`` out of the allowed scopes and renames the column back.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = {"pipeline", "stage", "action"}
NEW = ("definition", "node")


def _scopes(raw: object) -> list[str]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else []
    except ValueError:
        return []
    return [s for s in value if isinstance(s, str)] if isinstance(value, list) else []


def upgrade() -> None:
    op.drop_index("ix_guard_attachments_pipeline_id", table_name="guard_attachments")
    op.execute("ALTER TABLE guard_attachments RENAME COLUMN pipeline_id TO graph_id")
    op.create_index("ix_guard_attachments_graph_id", "guard_attachments", ["graph_id"])
    bind = op.get_bind()
    for ident, raw in bind.execute(sa.text("SELECT id, scope_types FROM guard_definitions")).all():
        scopes = _scopes(raw)
        if set(scopes) >= OLD:
            widened = [*scopes, *(s for s in NEW if s not in scopes)]
            bind.execute(
                sa.text("UPDATE guard_definitions SET scope_types = :scopes WHERE id = :id"),
                {"scopes": json.dumps(widened), "id": ident},
            )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM guard_attachments WHERE scope_type IN ('definition', 'node')")
    )
    for ident, raw in bind.execute(sa.text("SELECT id, scope_types FROM guard_definitions")).all():
        scopes = _scopes(raw)
        kept = [s for s in scopes if s not in NEW]
        if kept != scopes:
            bind.execute(
                sa.text("UPDATE guard_definitions SET scope_types = :scopes WHERE id = :id"),
                {"scopes": json.dumps(kept or ["pipeline", "stage", "action"]), "id": ident},
            )
    op.drop_index("ix_guard_attachments_graph_id", table_name="guard_attachments")
    op.execute("ALTER TABLE guard_attachments RENAME COLUMN graph_id TO pipeline_id")
    op.create_index("ix_guard_attachments_pipeline_id", "guard_attachments", ["pipeline_id"])
