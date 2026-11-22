"""Execution nodes: Code and HTTP kinds, node settings as JSON, results of nodes per run.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-22

``graph_nodes.config`` holds the settings of the new kinds as one JSON object (``seconds`` and
``fail_enabled`` stay columns). The kind check of ``graph_nodes`` gains ``code`` and ``http``.
``run_node_results`` records every node executed in an action definition during a run (in order,
with the position, the port left through and, for Code and HTTP nodes, exit code, output, reason and
data); its rows go with the run. The downgrade deletes Code and HTTP nodes (with their connections) because the old kind check
cannot hold them, then drops the table and the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = "'trigger', 'stage', 'action', 'complete', 'output', 'timer', 'pipeline'"
NEW_KINDS = f"{OLD_KINDS}, 'code', 'http'"
CHECK = "ck_graph_nodes_kind"


def upgrade() -> None:
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.add_column(sa.Column("config", sa.JSON(), nullable=False, server_default="{}"))
        batch.create_check_constraint(CHECK, f"kind IN ({NEW_KINDS})")
    op.create_table(
        "run_node_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("pipeline_id", sa.String(36), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("top_stage_id", sa.String(36), nullable=True),
        sa.Column("stage_id", sa.String(36), nullable=True),
        sa.Column("action_id", sa.String(36), nullable=True),
        sa.Column("definition_id", sa.String(36), nullable=True),
        sa.Column("node_id", sa.String(36), nullable=False),
        sa.Column("node_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(8), nullable=False),
        sa.Column("port", sa.String(16), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("output", sa.Text(), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ux_run_node_results_run_seq", "run_node_results", ["run_id", "seq"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ux_run_node_results_run_seq", table_name="run_node_results")
    op.drop_table("run_node_results")
    op.execute(sa.text("DELETE FROM graph_nodes WHERE kind IN ('code', 'http')"))
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.drop_column("config")
        batch.create_check_constraint(CHECK, f"kind IN ({OLD_KINDS})")
