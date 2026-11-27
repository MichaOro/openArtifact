"""The restart note says ``Interrupted by restart`` (ADR-013).

Revision ID: 0064
Revises: 0063
Create Date: 2026-11-26

A run that was still running when the application restarted was closed ``stopped`` with the bare word ``interrupted``. The note is stored
text that the list, the history, the API and MCP show as it is, so the stored rows are rewritten once instead of mapped on every read: the
runs (``pipeline_runs.note``) and their executions (``executions.note``). Only the exact old text changes. The downgrade writes it back.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0064"
down_revision: str | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "interrupted"
NEW = "Interrupted by restart"
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
