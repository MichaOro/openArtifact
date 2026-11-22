"""Foreign key ``tasks.parent_id`` → ``tasks.id`` (``ON DELETE SET NULL``).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-21

SQLite cannot add a constraint to an existing table, so the table is rebuilt (batch mode).
Dangling parent references, if any, are cleared first.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_NAME = "fk_tasks_parent_id"


def upgrade() -> None:
    """Clear dangling parents, then add the foreign key."""

    op.execute(
        sa.text(
            "UPDATE tasks SET parent_id = NULL "
            "WHERE parent_id IS NOT NULL AND parent_id NOT IN (SELECT id FROM tasks)"
        )
    )
    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.create_foreign_key(FK_NAME, "tasks", ["parent_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    """Drop the foreign key."""

    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.drop_constraint(FK_NAME, type_="foreignkey")
