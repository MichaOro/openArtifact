"""A pipeline node: a pipeline that calls another pipeline.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-21

A node of kind ``pipeline`` sits in the chain of stages like a stage does. ``definition_id`` points at
the pipeline it calls (a ``workflows`` row of kind ``workflow``); the called pipeline runs up to its
complete and then the calling one goes on.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "kind IN ('trigger', 'stage', 'action', 'complete', 'output', 'timer'{})"


def upgrade() -> None:
    with op.batch_alter_table("workflow_nodes") as batch:
        batch.drop_constraint("ck_workflow_nodes_kind", type_="check")
        batch.create_check_constraint("ck_workflow_nodes_kind", _KINDS.format(", 'pipeline'"))


def downgrade() -> None:
    nodes = "(SELECT id FROM workflow_nodes WHERE kind = 'pipeline')"
    op.execute(f"DELETE FROM workflow_edges WHERE source_id IN {nodes} OR target_id IN {nodes}")
    op.execute("DELETE FROM workflow_nodes WHERE kind = 'pipeline'")
    with op.batch_alter_table("workflow_nodes") as batch:
        batch.drop_constraint("ck_workflow_nodes_kind", type_="check")
        batch.create_check_constraint("ck_workflow_nodes_kind", _KINDS.format(""))
