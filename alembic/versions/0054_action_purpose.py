"""The purpose of an action definition: for pipelines or for guards (ADR-066).

Revision ID: 0054
Revises: 0053
Create Date: 2026-11-25

``graphs.purpose`` (``pipeline`` or ``guard``). Every graph starts as ``pipeline``. An action definition that a guard runs
(``guard_definitions.action_id``) becomes ``guard``, unless a stage of a pipeline uses it too: that one stays ``pipeline`` (it
cannot be both) and keeps working; the guard editor then asks for a guard action when the guard is saved the next time. The
downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("graphs") as batch:
        batch.add_column(
            sa.Column("purpose", sa.String(16), nullable=False, server_default="pipeline")
        )
    op.execute(
        sa.text(
            "UPDATE graphs SET purpose = 'guard' WHERE kind = 'action' "
            "AND id IN (SELECT action_id FROM guard_definitions WHERE action_id IS NOT NULL) "
            "AND id NOT IN (SELECT definition_id FROM graph_nodes WHERE kind = 'action' AND definition_id IS NOT NULL)"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("graphs") as batch:
        batch.drop_column("purpose")
