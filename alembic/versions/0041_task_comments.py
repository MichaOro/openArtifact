"""Comments on artifacts (ADR-055).

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-23

``task_comments``: plain text with who wrote it (a kind and a name) and, for a pipeline node, the execution. They go
with their artifact (``ON DELETE CASCADE``). The downgrade drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_comments",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author_kind", sa.String(16), nullable=False),
        sa.Column("author", sa.String(64), nullable=False),
        sa.Column("execution_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_task_comments_task_created", "task_comments", ["task_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_task_comments_task_created", table_name="task_comments")
    op.drop_table("task_comments")
