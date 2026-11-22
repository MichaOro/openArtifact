"""A run records whether the API or the MCP server started it.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-22

``started_by`` of a run (and so of its execution) was ``user`` or ``system``; the REST API and the MCP
server were both recorded as ``system``. They get their own values, ``api`` and ``mcp``, so the history
shows how each execution was started. ``system`` stays for starts the application itself makes.
Rows written before this migration keep ``system``: the way they were started was not recorded.

The downgrade maps ``api`` and ``mcp`` back to ``system``.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK_NAME = "ck_pipeline_runs_started_by"


def upgrade() -> None:
    with op.batch_alter_table("pipeline_runs", recreate="always") as batch:
        batch.drop_constraint(CHECK_NAME, type_="check")
        batch.create_check_constraint(CHECK_NAME, "started_by IN ('user', 'api', 'mcp', 'system')")


def downgrade() -> None:
    op.execute("UPDATE pipeline_runs SET started_by = 'system' WHERE started_by IN ('api', 'mcp')")
    op.execute("UPDATE executions SET started_by = 'system' WHERE started_by IN ('api', 'mcp')")
    with op.batch_alter_table("pipeline_runs", recreate="always") as batch:
        batch.drop_constraint(CHECK_NAME, type_="check")
        batch.create_check_constraint(CHECK_NAME, "started_by IN ('user', 'system')")
