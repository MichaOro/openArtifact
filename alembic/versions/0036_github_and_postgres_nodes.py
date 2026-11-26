"""The GitHub node, the Postgres node and the Postgres Tool.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-23

The kind check of ``graph_nodes`` gains ``github``, ``postgres`` and ``postgres_tool`` (ADR-041). Their settings live in
``config`` and the attachment of the Postgres Tool to an Agent node is an ordinary edge, so nothing else changes. The
downgrade deletes the nodes of these kinds with their edges (the code of before does not know the kinds).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "'trigger', 'stage', 'action', 'complete', 'output', 'timer', 'pipeline', 'code', 'http', "
    "'if', 'switch', 'agent', 'set', 'mcp_tool', 'http_tool', 'code_tool'"
)
NEW_KINDS = f"{OLD_KINDS}, 'github', 'postgres', 'postgres_tool'"
CHECK = "ck_graph_nodes_kind"
GONE = "'github', 'postgres', 'postgres_tool'"


def upgrade() -> None:
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, f"kind IN ({NEW_KINDS})")


def downgrade() -> None:
    # migrations run without foreign keys: the edges of these nodes are deleted by hand
    gone = f"SELECT id FROM graph_nodes WHERE kind IN ({GONE})"
    op.execute(
        sa.text(f"DELETE FROM graph_edges WHERE source_id IN ({gone}) OR target_id IN ({gone})")
    )
    op.execute(sa.text(f"DELETE FROM graph_nodes WHERE kind IN ({GONE})"))
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, f"kind IN ({OLD_KINDS})")
