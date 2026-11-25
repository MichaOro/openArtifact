"""Card rules: an artifact can be archived (ADR-071); the lanes that draw their cards as finished get the rule that does it.

Revision ID: 0058
Revises: 0057
Create Date: 2026-11-25

``tasks.archived_at`` (UTC, empty = visible). The number 0055 is reserved for the event log (card #100). Every lane with the style
``finished`` gets one rule *Set card as done* without a condition in ``app_settings`` (key ``cards.rules``), so what the lane did
before it still does. The downgrade drops the column and leaves the rules (a version before this one does not read them).
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEY = "cards.rules"
RULE = {
    "when": {"type": "group", "mode": "all", "items": []},
    "action": "set_done",
    "name": None,
    "enabled": True,
    "params": {},
}


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_tasks_archived_at", ["archived_at"])
    connection = op.get_bind()
    finished = [
        row[0]
        for row in connection.execute(
            sa.text("SELECT key FROM lanes WHERE style = 'finished' ORDER BY position")
        )
    ]
    if not finished:
        return
    stored = connection.execute(
        sa.text("SELECT value FROM app_settings WHERE key = :key"), {"key": KEY}
    ).scalar()
    data = json.loads(stored) if stored else {}
    data.setdefault("board", [])
    lanes = data.setdefault("lanes", {})
    for key in finished:
        lanes.setdefault(key, []).insert(0, RULE)
    value = json.dumps(data)
    if stored is None:
        connection.execute(
            sa.text(
                "INSERT INTO app_settings (key, value, updated_at) VALUES (:key, :value, CURRENT_TIMESTAMP)"
            ),
            {"key": KEY, "value": value},
        )
    else:
        connection.execute(
            sa.text("UPDATE app_settings SET value = :value WHERE key = :key"),
            {"key": KEY, "value": value},
        )


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_index("ix_tasks_archived_at")
        batch.drop_column("archived_at")
