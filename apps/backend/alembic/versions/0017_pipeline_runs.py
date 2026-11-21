"""Pipeline runs: what an artifact has gone through in a pipeline.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-21

One run per artifact (``task_id`` is unique) holds the state of its processing: the status, the
stage and action it is at, and a frozen copy of the pipeline (``snapshot``) so that editing the
pipeline does not change a run in flight. ``run_stages`` keeps the status of every stage of the run.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "workflow_id",
            sa.String(36),
            sa.ForeignKey("workflows.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_by", sa.String(16), nullable=False),
        sa.Column("stage_id", sa.String(36), nullable=True),
        sa.Column("action_id", sa.String(36), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("snapshot", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.CheckConstraint(
            "status IN ('running', 'stopped', 'done', 'failed')", name="ck_pipeline_runs_status"
        ),
        sa.CheckConstraint("started_by IN ('user', 'system')", name="ck_pipeline_runs_started_by"),
    )
    op.create_table(
        "run_stages",
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("stage_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'passed', 'failed', 'skipped')",
            name="ck_run_stages_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("run_stages")
    op.drop_table("pipeline_runs")
