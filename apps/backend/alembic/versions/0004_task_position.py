"""Manual order of tasks inside a lane — ``tasks.position``.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-21

Adds a fractional sort key per lane. Existing rows are numbered 0, 1, 2 … in the order
the board showed them so far (newest first), so nothing visibly changes.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add tasks.position and backfill it from the previous ordering."""

    op.add_column(
        "tasks",
        sa.Column("position", sa.Float(), nullable=False, server_default=sa.text("0")),
    )
    # rank within the lane: newest first, ties by id (the old ORDER BY)
    op.execute(
        """
        UPDATE tasks SET position = (
            SELECT COUNT(*) FROM tasks AS other
            WHERE other.status = tasks.status
              AND (other.created_at > tasks.created_at
                   OR (other.created_at = tasks.created_at AND other.id < tasks.id))
        )
        """
    )
    op.create_index("ix_tasks_status_position", "tasks", ["status", "position"])


def downgrade() -> None:
    """Drop tasks.position."""

    op.drop_index("ix_tasks_status_position", table_name="tasks")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("position")
