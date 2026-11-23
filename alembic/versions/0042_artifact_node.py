"""The Artifact node (ADR-055).

Revision ID: 0042
Revises: 0041
Create Date: 2026-11-23

The kind check of ``graph_nodes`` gains ``artifact``. Its settings live in ``config``. The downgrade deletes the nodes of
this kind with their edges (the code of before does not know the kind).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "'trigger', 'stage', 'action', 'complete', 'output', 'timer', 'pipeline', 'code', 'http', "
    "'if', 'switch', 'agent', 'set', 'mcp_tool', 'http_tool', 'code_tool', 'github', 'postgres', "
    "'postgres_tool'"
)
NEW_KINDS = f"{OLD_KINDS}, 'artifact'"
CHECK = "ck_graph_nodes_kind"


def upgrade() -> None:
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, f"kind IN ({NEW_KINDS})")


def downgrade() -> None:
    gone = "SELECT id FROM graph_nodes WHERE kind = 'artifact'"
    op.execute(
        sa.text(f"DELETE FROM graph_edges WHERE source_id IN ({gone}) OR target_id IN ({gone})")
    )
    op.execute(sa.text("DELETE FROM graph_nodes WHERE kind = 'artifact'"))
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, f"kind IN ({OLD_KINDS})")
