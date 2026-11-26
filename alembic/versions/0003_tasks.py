"""Kanban tasks — the ``tasks`` table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-20

Minimal table backing task creation on the board. Lane values are stored as
lowercase strings and enforced by a CHECK constraint.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the tasks table."""

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'backlog'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        # Declared inline: SQLite cannot ALTER constraints onto an existing table.
        sa.CheckConstraint(
            "status IN ('backlog', 'in_progress', 'done')",
            name="ck_tasks_status",
        ),
    )
    op.create_index("ix_tasks_status_created_at", "tasks", ["status", "created_at"])


def downgrade() -> None:
    """Drop the tasks table."""

    op.drop_table("tasks")
