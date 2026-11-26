"""The OpenArtifact MCP Tool node: a tool node of an agent that works with the board through the application's own tools (ADR-079).

Revision ID: 0060
Revises: 0059
Create Date: 2026-11-26

The kind check of ``graph_nodes`` gains ``openartifact_tool``. Its settings live in ``config``. The downgrade deletes the nodes of
this kind with their edges (the code of before does not know the kind).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "'trigger', 'stage', 'action', 'complete', 'output', 'timer', 'pipeline', 'code', 'http', "
    "'if', 'switch', 'agent', 'set', 'mcp_tool', 'http_tool', 'code_tool', 'github', 'postgres', "
    "'postgres_tool', 'artifact', 'github_tool', 'sqlite', 'sqlite_tool'"
)
NEW_KINDS = f"{OLD_KINDS}, 'openartifact_tool'"
CHECK = "ck_graph_nodes_kind"


def upgrade() -> None:
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, f"kind IN ({NEW_KINDS})")


def downgrade() -> None:
    gone = "SELECT id FROM graph_nodes WHERE kind = 'openartifact_tool'"
    op.execute(
        sa.text(f"DELETE FROM graph_edges WHERE source_id IN ({gone}) OR target_id IN ({gone})")
    )
    op.execute(sa.text("DELETE FROM graph_nodes WHERE kind = 'openartifact_tool'"))
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, f"kind IN ({OLD_KINDS})")
