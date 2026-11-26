"""Dry run: a run and its execution know that nothing was written outside them (ADR-086).

Revision ID: 0066
Revises: 0065
Create Date: 2026-11-27

``executions.dry_run`` and ``pipeline_runs.dry_run`` (false for every row that exists: the runs before were real). The downgrade drops the
columns, and with them the memory of which executions were dry runs.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0066"
down_revision: str | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("executions", "pipeline_runs")


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("0"))
            )


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("dry_run")
