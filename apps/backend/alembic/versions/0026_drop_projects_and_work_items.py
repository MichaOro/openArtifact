"""Drop the unused ``work_items`` and ``projects`` tables.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-22

Both tables came with migration 0002 and were never used by the application: the board works on
``tasks``. ``work_items`` is dropped first, it refers to ``projects``. Rows are lost; there were none
the application could have written. The downgrade creates both tables again as migration 0002 did.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("work_items")
    op.drop_table("projects")


def downgrade() -> None:
    now = sa.text("CURRENT_TIMESTAMP")
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
    )
    op.create_index("ix_projects_created_at", "projects", ["created_at"], unique=False)

    op.create_table(
        "work_items",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default=sa.text("'BACKLOG'")
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        # Inline: SQLite cannot add constraints to an existing table.
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_work_items_project_id", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "status IN ('BACKLOG', 'TODO', 'IN_PROGRESS', 'REVIEW')", name="ck_work_items_status"
        ),
    )
    op.create_index("ix_work_items_project_id", "work_items", ["project_id"], unique=False)
    op.create_index("ix_work_items_status", "work_items", ["status"], unique=False)
    op.create_index(
        "ix_work_items_project_status", "work_items", ["project_id", "status"], unique=False
    )
    op.create_index(
        "ix_work_items_project_status_position",
        "work_items",
        ["project_id", "status", "position"],
        unique=False,
    )
