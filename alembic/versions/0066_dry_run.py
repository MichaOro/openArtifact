"""Dry run: a run and its execution know that nothing was written outside them (ADR-086).

Revision ID: 0066
Revises: 0065
Create Date: 2026-11-27

``executions.dry_run`` and ``pipeline_runs.dry_run`` (false for every row that exists: the runs before were real). The downgrade drops the
columns, and with them the memory of which executions were dry runs.

The views the guard actions read (``engine/guard_views.py``) stand on ``executions`` and are made again at every start, after the
migrations. SQLite refuses to rebuild a table that a view reads ("error in view v_guard_runs: no such table"), so both directions drop
them first; the next start makes them again.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0066"
down_revision: str | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("executions", "pipeline_runs")
GUARD_VIEWS = (
    "v_guard_runs",
    "v_guard_steps",
    "v_guard_tool_calls",
    "v_guard_artifacts",
    "v_guard_lanes",
)


def _drop_guard_views() -> None:
    for view in GUARD_VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {view}")


def upgrade() -> None:
    _drop_guard_views()
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("0"))
            )


def downgrade() -> None:
    _drop_guard_views()
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("dry_run")
