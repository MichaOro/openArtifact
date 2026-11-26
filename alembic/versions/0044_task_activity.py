"""The activity of artifacts: what changed and who did it (ADR-058).

Revision ID: 0044
Revises: 0043
Create Date: 2026-11-24

``task_activity``: one row per change of an artifact (created, lane, title, description, parent, field, pipeline,
stage, action) and one trace per execution that was deleted (kind ``run``: pipeline, number, status, duration). Rows go
with their artifact (``ON DELETE CASCADE``); the application keeps at most 500 per artifact. Every existing artifact gets
a ``created`` row at its creation time (nothing older is known, so nothing is invented). The downgrade drops the table.
"""

import json
import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Who created an artifact, as the (kind, name) of an actor.
_CREATORS = {
    "user": ("user", "You"),
    "api": ("api", "api"),
    "mcp": ("mcp", "mcp"),
    "action": ("run", "action"),
}


def upgrade() -> None:
    table = op.create_table(
        "task_activity",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("actor_kind", sa.String(16), nullable=False),
        sa.Column("actor_name", sa.String(64), nullable=False),
        sa.Column("execution_id", sa.String(36), nullable=True),
        sa.Column("data", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_task_activity_task_created", "task_activity", ["task_id", "created_at"])
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT t.id, t.created_by, t.created_at, l.title AS lane "
            "FROM tasks t LEFT JOIN lanes l ON l.key = t.status"
        )
    ).all()
    op.bulk_insert(
        table,
        [
            {
                "id": str(uuid.uuid4()),
                "task_id": row.id,
                "kind": "created",
                "actor_kind": _CREATORS.get(row.created_by, ("system", "system"))[0],
                "actor_name": _CREATORS.get(row.created_by, ("system", "system"))[1],
                "execution_id": None,
                "data": json.dumps({"lane": row.lane} if row.lane else {}),
                "created_at": _when(row.created_at),
            }
            for row in rows
        ],
    )


def _when(value: object) -> object:
    """The stored timestamp as a datetime (SQLite returns text for a raw query)."""
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def downgrade() -> None:
    op.drop_index("ix_task_activity_task_created", table_name="task_activity")
    op.drop_table("task_activity")
