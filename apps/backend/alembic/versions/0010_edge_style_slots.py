"""Edge style and the attachment slot on a stage.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-21

An edge is drawn curved, straight or as a rounded elbow. A stage offers three attachment points
(slots 0-2, top to bottom) on each side; the edge remembers which one it uses at either end.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_edges") as batch:
        batch.add_column(sa.Column("style", sa.String(16), nullable=False, server_default="curved"))
        batch.add_column(sa.Column("source_slot", sa.Integer, nullable=False, server_default="0"))
        batch.add_column(sa.Column("target_slot", sa.Integer, nullable=False, server_default="0"))
        batch.create_check_constraint(
            "ck_workflow_edges_style", "style IN ('curved', 'straight', 'elbow')"
        )
        batch.create_check_constraint(
            "ck_workflow_edges_slots", "source_slot BETWEEN 0 AND 2 AND target_slot BETWEEN 0 AND 2"
        )


def downgrade() -> None:
    with op.batch_alter_table("workflow_edges") as batch:
        batch.drop_constraint("ck_workflow_edges_slots", type_="check")
        batch.drop_constraint("ck_workflow_edges_style", type_="check")
        batch.drop_column("target_slot")
        batch.drop_column("source_slot")
        batch.drop_column("style")
