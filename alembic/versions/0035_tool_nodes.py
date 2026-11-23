"""Tool nodes of agents: the MCP Client Tool, the HTTP Request Tool and the Code Tool.

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-23

The kind check of ``graph_nodes`` gains ``mcp_tool``, ``http_tool`` and ``code_tool`` (ADR-040). Their settings live
in ``config`` and their attachment to an Agent node is an ordinary edge, so nothing else changes; the agent setting
``max_iterations`` lives in the JSON of drafts, versions and agent nodes. The downgrade deletes tool nodes with their
edges and removes ``max_iterations`` again (the code of before refuses a key it does not know).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "'trigger', 'stage', 'action', 'complete', 'output', 'timer', 'pipeline', 'code', 'http', "
    "'if', 'switch', 'agent', 'set'"
)
NEW_KINDS = f"{OLD_KINDS}, 'mcp_tool', 'http_tool', 'code_tool'"
CHECK = "ck_graph_nodes_kind"


def upgrade() -> None:
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, f"kind IN ({NEW_KINDS})")


TOOLS = "SELECT id FROM graph_nodes WHERE kind IN ('mcp_tool', 'http_tool', 'code_tool')"


def downgrade() -> None:
    # migrations run without foreign keys: the edges of tool nodes are deleted by hand
    op.execute(
        sa.text(f"DELETE FROM graph_edges WHERE source_id IN ({TOOLS}) OR target_id IN ({TOOLS})")
    )
    op.execute(
        sa.text("DELETE FROM graph_nodes WHERE kind IN ('mcp_tool', 'http_tool', 'code_tool')")
    )
    # max_iterations came with the tools: the agents of before refuse a key they do not know
    op.execute(sa.text("UPDATE agents SET draft = json_remove(draft, '$.max_iterations')"))
    op.execute(
        sa.text("UPDATE agent_versions SET config = json_remove(config, '$.max_iterations')")
    )
    op.execute(
        sa.text(
            "UPDATE graph_nodes SET config = json_remove(config, '$.max_iterations') "
            "WHERE kind = 'agent' AND json_valid(config)"
        )
    )
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, f"kind IN ({OLD_KINDS})")
