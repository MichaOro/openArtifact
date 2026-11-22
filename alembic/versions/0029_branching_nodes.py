"""Branching nodes: the If and Switch kinds.

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-22

The kind check of ``graph_nodes`` gains ``if`` and ``switch``. Their settings live in the existing
``config`` column, so nothing else changes. The downgrade deletes If and Switch nodes (with their
connections) because the old kind check cannot hold them.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "'trigger', 'stage', 'action', 'complete', 'output', 'timer', 'pipeline', 'code', 'http'"
)
NEW_KINDS = f"{OLD_KINDS}, 'if', 'switch'"
CHECK = "ck_graph_nodes_kind"


def upgrade() -> None:
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, f"kind IN ({NEW_KINDS})")


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM graph_nodes WHERE kind IN ('if', 'switch')"))
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, f"kind IN ({OLD_KINDS})")
