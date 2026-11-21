"""Parent / child relation between tasks — ``tasks.parent_id``.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-21

A task has at most one parent; a task can be the parent of any number of tasks (a tree).
The foreign key follows in 0007 (SQLite needs a table rebuild for it).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add tasks.parent_id."""

    op.add_column("tasks", sa.Column("parent_id", sa.String(length=36), nullable=True))
    op.create_index("ix_tasks_parent_id", "tasks", ["parent_id"])


def downgrade() -> None:
    """Drop tasks.parent_id."""

    op.drop_index("ix_tasks_parent_id", table_name="tasks")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("parent_id")
