"""Action definitions: workflows of kind ``action`` with an ``output`` node.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-21

An action definition is edited on the same canvas as a workflow: it starts at a trigger and ends
at an output node. The output always offers *On Pass*; *On Fail* is switched on per definition
(``fail_enabled``).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "kind IN ('trigger', 'stage', 'action', 'complete'{})"


def upgrade() -> None:
    with op.batch_alter_table("workflows") as batch:
        batch.add_column(
            sa.Column("kind", sa.String(16), nullable=False, server_default="workflow")
        )
        batch.create_check_constraint("ck_workflows_kind", "kind IN ('workflow', 'action')")
    with op.batch_alter_table("workflow_nodes") as batch:
        batch.add_column(
            sa.Column("fail_enabled", sa.Boolean, nullable=False, server_default=sa.false())
        )
        batch.drop_constraint("ck_workflow_nodes_kind", type_="check")
        batch.create_check_constraint("ck_workflow_nodes_kind", _KINDS.format(", 'output'"))


def downgrade() -> None:
    for table in ("workflow_edges", "workflow_nodes"):
        op.execute(
            f"DELETE FROM {table} WHERE workflow_id IN (SELECT id FROM workflows WHERE kind = 'action')"
        )
    op.execute("DELETE FROM workflows WHERE kind = 'action'")
    with op.batch_alter_table("workflow_nodes") as batch:
        batch.drop_constraint("ck_workflow_nodes_kind", type_="check")
        batch.create_check_constraint("ck_workflow_nodes_kind", _KINDS.format(""))
        batch.drop_column("fail_enabled")
    with op.batch_alter_table("workflows") as batch:
        batch.drop_constraint("ck_workflows_kind", type_="check")
        batch.drop_column("kind")
