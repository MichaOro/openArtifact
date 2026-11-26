"""The emergency stop's note: executions it aborted say ``EMERGENCY STOP`` (ADR-076).

Revision ID: 0061
Revises: 0060
Create Date: 2026-11-26

The first version of the switch wrote the note ``STOP switch``; the name the user sees is *emergency stop*. A note is stored text that
the list, the history, the API and MCP all show as it is, so the stored rows are rewritten once instead of mapped on every read: the
runs (``pipeline_runs.note``) and their executions (``executions.note``). Only the exact old text changes. The downgrade writes it back.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "STOP switch"
NEW = "EMERGENCY STOP"
TABLES = ("pipeline_runs", "executions")


def _rewrite(old: str, new: str) -> None:
    for table in TABLES:
        op.get_bind().execute(
            sa.text(
                f"UPDATE {table} SET note = :new WHERE note = :old"
            ),  # the table names are the constants above
            {"old": old, "new": new},
        )


def upgrade() -> None:
    _rewrite(OLD, NEW)


def downgrade() -> None:
    _rewrite(NEW, OLD)
