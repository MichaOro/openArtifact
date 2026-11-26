"""Versions of guard definitions (ADR-081).

Revision ID: 0065
Revises: 0063
Create Date: 2026-11-26

``guard_versions`` holds the published versions of a guard definition (a frozen copy, written once); ``guard_definitions.published_number``
points to the one executions use (``NULL``: never published, the guard watches nothing). Every guard that exists becomes published
version 1 with its current content, so nothing changes for a running installation. The downgrade drops the table and the column: the
definition's own columns stay and are what was the draft (the same content as before).

NOTE for the merge: ``down_revision`` is the head the branch had when this was written; set it to the newest migration (0064).
"""

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0065"
down_revision: str | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _loads(text: str | None, empty: object) -> object:
    try:
        return json.loads(text) if text else empty
    except ValueError:
        return empty


def upgrade() -> None:
    op.create_table(
        "guard_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "guard_id",
            sa.String(36),
            sa.ForeignKey("guard_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("source_number", sa.Integer(), nullable=True),
        sa.Column("published_via", sa.String(16), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("guard_id", "number", name="ux_guard_versions_number"),
    )
    op.create_index("ix_guard_versions_guard_id", "guard_versions", ["guard_id"])
    with op.batch_alter_table("guard_definitions") as batch:
        batch.add_column(sa.Column("published_number", sa.Integer(), nullable=True))
    conn = op.get_bind()
    now = datetime.now(UTC).replace(tzinfo=None)
    rows = conn.execute(
        sa.text(
            "SELECT id, name, description, scope_types, trigger, condition, consequence, fallback, escalation, action_id "
            "FROM guard_definitions"
        )
    ).all()
    for row in rows:
        content = {
            "name": row.name,
            "description": row.description or "",
            "scope_types": _loads(row.scope_types, []),
            "trigger": _loads(row.trigger, {}),
            "when": _loads(row.condition, {}),
            "consequence": row.consequence,
            "fallback": row.fallback,
            "escalation": _loads(row.escalation, []),
            "action_id": row.action_id,
        }
        text = json.dumps(content, sort_keys=True, default=str)
        conn.execute(
            sa.text(
                "INSERT INTO guard_versions (id, guard_id, number, content, fingerprint, source_number, published_via, "
                "published_at) VALUES (:id, :guard, 1, :content, :fingerprint, NULL, 'user', :at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "guard": row.id,
                "content": text,
                "fingerprint": hashlib.sha256(text.encode()).hexdigest(),
                "at": now,
            },
        )
        conn.execute(
            sa.text("UPDATE guard_definitions SET published_number = 1 WHERE id = :id"),
            {"id": row.id},
        )


def downgrade() -> None:
    with op.batch_alter_table("guard_definitions") as batch:
        batch.drop_column("published_number")
    op.drop_index("ix_guard_versions_guard_id", table_name="guard_versions")
    op.drop_table("guard_versions")
