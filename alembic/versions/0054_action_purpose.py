"""The purpose of an action definition: for pipelines or for guards (ADR-067).

Revision ID: 0054
Revises: 0053
Create Date: 2026-11-25

``graphs.purpose`` (``pipeline`` or ``guard``). The kind check of ``graph_nodes`` also gains ``sqlite`` and ``sqlite_tool`` (the SQLite
node and tool, ADR-068, which only a guard action may hold). Every graph starts as ``pipeline``. An action definition that a guard runs
(``guard_definitions.action_id``) becomes ``guard``, unless a stage of a pipeline uses it too: that one stays ``pipeline`` (it
cannot be both) and keeps working; the guard editor then asks for a guard action when the guard is saved the next time. The
downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

OLD_KINDS = (
    "'trigger', 'stage', 'action', 'complete', 'output', 'timer', 'pipeline', 'code', 'http', "
    "'if', 'switch', 'agent', 'set', 'mcp_tool', 'http_tool', 'code_tool', 'github', 'postgres', "
    "'postgres_tool', 'artifact', 'github_tool'"
)
NEW_KINDS = f"{OLD_KINDS}, 'sqlite', 'sqlite_tool'"
CHECK = "ck_graph_nodes_kind"

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("graphs") as batch:
        batch.add_column(
            sa.Column("purpose", sa.String(16), nullable=False, server_default="pipeline")
        )
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, f"kind IN ({NEW_KINDS})")
    op.execute(
        sa.text(
            "UPDATE graphs SET purpose = 'guard' WHERE kind = 'action' "
            "AND id IN (SELECT action_id FROM guard_definitions WHERE action_id IS NOT NULL) "
            "AND id NOT IN (SELECT definition_id FROM graph_nodes WHERE kind = 'action' AND definition_id IS NOT NULL)"
        )
    )


def downgrade() -> None:
    gone = "SELECT id FROM graph_nodes WHERE kind IN ('sqlite', 'sqlite_tool')"
    op.execute(
        sa.text(f"DELETE FROM graph_edges WHERE source_id IN ({gone}) OR target_id IN ({gone})")
    )
    op.execute(sa.text("DELETE FROM graph_nodes WHERE kind IN ('sqlite', 'sqlite_tool')"))
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, f"kind IN ({OLD_KINDS})")
    with op.batch_alter_table("graphs") as batch:
        batch.drop_column("purpose")
