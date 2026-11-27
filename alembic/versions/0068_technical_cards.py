"""Technical cards: the hidden card a dry run without a card belongs to (ADR-089).

Revision ID: 0068
Revises: 0067
Create Date: 2026-11-27

``tasks.technical`` (false for every card that exists). Added with a plain ``ADD COLUMN``, never a rebuild of ``tasks``: executions, comments,
activity and runs point at it with ``ON DELETE CASCADE``. The views the guard actions read stand on ``tasks`` and are made again at every
start, after the migrations; both directions drop them first (the lesson of 0066 and 0067); the next start makes them again.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0068"
down_revision: str | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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
    # a plain ADD COLUMN: the table is not rebuilt (a rebuild of ``tasks`` would drop it with the executions, comments and runs that
    # point at it with ON DELETE CASCADE); the views are dropped anyway so that nothing reads the table while it changes
    _drop_guard_views()
    op.add_column(
        "tasks", sa.Column("technical", sa.Boolean(), nullable=False, server_default=sa.text("0"))
    )


def downgrade() -> None:
    _drop_guard_views()
    op.execute(
        "DELETE FROM tasks WHERE technical = 1"
    )  # the hidden cards and, by cascade, their executions
    op.execute("ALTER TABLE tasks DROP COLUMN technical")
