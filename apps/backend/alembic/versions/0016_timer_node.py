"""A timer node for action definitions.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-21

A timer pauses the run for ``seconds`` before it goes on; it is the first piece of business logic an
action definition can hold.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "kind IN ('trigger', 'stage', 'action', 'complete', 'output'{})"


def upgrade() -> None:
    with op.batch_alter_table("workflow_nodes") as batch:
        batch.add_column(sa.Column("seconds", sa.Integer, nullable=True))
        batch.drop_constraint("ck_workflow_nodes_kind", type_="check")
        batch.create_check_constraint("ck_workflow_nodes_kind", _KINDS.format(", 'timer'"))


def downgrade() -> None:
    for table in ("workflow_edges",):
        op.execute(
            f"DELETE FROM {table} WHERE source_id IN (SELECT id FROM workflow_nodes WHERE kind = 'timer') "
            f"OR target_id IN (SELECT id FROM workflow_nodes WHERE kind = 'timer')"
        )
    op.execute("DELETE FROM workflow_nodes WHERE kind = 'timer'")
    with op.batch_alter_table("workflow_nodes") as batch:
        batch.drop_constraint("ck_workflow_nodes_kind", type_="check")
        batch.create_check_constraint("ck_workflow_nodes_kind", _KINDS.format(""))
        batch.drop_column("seconds")
