"""Human-readable artifact numbers — ``tasks.number`` (#1, #2, …).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-21

Numbers are handed out from a counter table, so a number is never reused after its artifact
was deleted (references like ``#12`` in other artifacts must not silently change meaning).
Existing artifacts are numbered oldest first.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add tasks.number, backfill it and create the counter."""

    op.add_column("tasks", sa.Column("number", sa.Integer(), nullable=True))
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id FROM tasks ORDER BY created_at, id")).fetchall()
    for n, (task_id,) in enumerate(rows, start=1):
        bind.execute(
            sa.text("UPDATE tasks SET number = :n WHERE id = :id"), {"n": n, "id": task_id}
        )
    op.create_index("ux_tasks_number", "tasks", ["number"], unique=True)
    op.create_table(
        "task_number_seq",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last", sa.Integer(), nullable=False),
    )
    bind.execute(
        sa.text("INSERT INTO task_number_seq (id, last) VALUES (1, :last)"), {"last": len(rows)}
    )


def downgrade() -> None:
    """Drop the counter and tasks.number."""

    op.drop_table("task_number_seq")
    op.drop_index("ux_tasks_number", table_name="tasks")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("number")
