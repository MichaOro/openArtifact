"""Where an artifact is meant to go, and where it came from.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-21

``pipeline_id``, ``stage_id`` and ``action_id`` say which pipeline, stage and action the artifact
starts with (the first stage and its first action unless chosen), so an artifact can be set up
completely before it is started. ``created_by`` records the way it was created: the browser
(``user``), the REST API (``api``), the MCP server (``mcp``) or an action (``action``).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_NAME = "fk_tasks_pipeline_id"
CHECK_NAME = "ck_tasks_created_by"


def upgrade() -> None:
    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.add_column(sa.Column("pipeline_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("stage_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("action_id", sa.String(36), nullable=True))
        batch.add_column(
            sa.Column("created_by", sa.String(16), nullable=False, server_default="user")
        )
        batch.create_foreign_key(FK_NAME, "workflows", ["pipeline_id"], ["id"], ondelete="SET NULL")
        batch.create_check_constraint(CHECK_NAME, "created_by IN ('user', 'api', 'mcp', 'action')")


def downgrade() -> None:
    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.drop_constraint(CHECK_NAME, type_="check")
        batch.drop_constraint(FK_NAME, type_="foreignkey")
        batch.drop_column("created_by")
        batch.drop_column("action_id")
        batch.drop_column("stage_id")
        batch.drop_column("pipeline_id")
