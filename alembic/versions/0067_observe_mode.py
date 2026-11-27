"""Observe mode: a run knows that it was observed, and a pipeline keeps the state of its observation (ADR-088).

Revision ID: 0067
Revises: 0066
Create Date: 2026-11-27

``executions.observed`` and ``pipeline_runs.observed`` (false for every row that exists: the runs before were not observed; an observed run is
also a dry run), and ``graphs.observe_state`` (JSON, empty for every graph: the counters of an observation that is under way and what the
owner decided about its end; the setting itself is part of the published version, not of this column).

The views the guard actions read (``engine/guard_views.py``) stand on ``executions`` and are made again at every start, after the migrations.
SQLite refuses to rebuild a table that a view reads, so both directions drop them first (the lesson of 0066); the next start makes them again.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0067"
down_revision: str | None = "0066"
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
        # a start that failed on this migration before the views were dropped left the empty copy behind (SQLite does not roll DDL back)
        op.execute(f"DROP TABLE IF EXISTS _alembic_tmp_{table}")
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column("observed", sa.Boolean(), nullable=False, server_default=sa.text("0"))
            )
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_graphs")
    with op.batch_alter_table("graphs") as batch:
        batch.add_column(sa.Column("observe_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    _drop_guard_views()
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("observed")
    with op.batch_alter_table("graphs") as batch:
        batch.drop_column("observe_state")
