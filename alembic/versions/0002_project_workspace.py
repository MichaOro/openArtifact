"""Project Workspace schema — projects and work items.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20

Creates the ``projects`` and ``work_items`` tables that back the
Project Workspace MVP. The four ``work_items.status`` values describe the
board state only and are NOT coupled to any pipeline or execution stage.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Board statuses — must stay in sync with WorkItemStatus in models.
# Stored as plain strings so the DB can evolve independently of the enum.
_BOARD_STATUSES = ("BACKLOG", "TODO", "IN_PROGRESS", "REVIEW")


def upgrade() -> None:
    """Create projects and work_items tables."""

    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), primary_key=False, nullable=False),
        sa.Column("description", sa.Text(), primary_key=False, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            primary_key=False,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            primary_key=False,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_projects_created_at",
        "projects",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "work_items",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            sa.String(length=36),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), primary_key=False, nullable=False),
        sa.Column("description", sa.Text(), primary_key=False, nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            primary_key=False,
            nullable=False,
            server_default=sa.text("'BACKLOG'"),
        ),
        sa.Column(
            "position",
            sa.Integer(),
            primary_key=False,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            primary_key=False,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            primary_key=False,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        # Constraints are declared inline: SQLite cannot ALTER constraints
        # onto an existing table.
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_work_items_project_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('BACKLOG', 'TODO', 'IN_PROGRESS', 'REVIEW')",
            name="ck_work_items_status",
        ),
    )
    op.create_index(
        "ix_work_items_project_id",
        "work_items",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_work_items_status",
        "work_items",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_work_items_project_status",
        "work_items",
        ["project_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_work_items_project_status_position",
        "work_items",
        ["project_id", "status", "position"],
        unique=False,
    )


def downgrade() -> None:
    """Drop projects and work_items tables."""

    op.drop_table("work_items")
    op.drop_table("projects")
