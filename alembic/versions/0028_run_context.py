"""The run context: variables and node results of a run, kept with its execution.

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-22

``executions.context`` holds the context of the execution (JSON text): the variables and the compact
results of the nodes that ran. The run that is current reads and writes it through
``pipeline_runs.execution_id``, so there is one copy, and deleting the execution deletes it. Existing
rows get ``{}``: executions of before this migration recorded no context.

The downgrade drops the column; the contexts are lost.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("executions") as batch:
        batch.add_column(sa.Column("context", sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("executions") as batch:
        batch.drop_column("context")
