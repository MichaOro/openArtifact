"""Workflow definitions — ``workflows``, ``workflow_nodes`` and ``workflow_edges``.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-21

A workflow is a graph: nodes (trigger, stage, action, complete) and edges between their ports.
Deleting a workflow or a node cascades to what hangs off it.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    """Create the three workflow tables."""

    op.create_table(
        "workflows",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_table(
        "workflow_nodes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.String(length=36),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "stage_id",
            sa.String(length=36),
            sa.ForeignKey("workflow_nodes.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("x", sa.Float(), nullable=False, server_default="0"),
        sa.Column("y", sa.Float(), nullable=False, server_default="0"),
        sa.Column("width", sa.Float(), nullable=True),
        sa.Column("height", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.CheckConstraint(
            "kind IN ('trigger', 'stage', 'action', 'complete')", name="ck_workflow_nodes_kind"
        ),
    )
    op.create_index("ix_workflow_nodes_workflow_id", "workflow_nodes", ["workflow_id"])
    op.create_index("ix_workflow_nodes_stage_id", "workflow_nodes", ["stage_id"])
    op.create_table(
        "workflow_edges",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.String(length=36),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.String(length=36),
            sa.ForeignKey("workflow_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_port", sa.String(length=16), nullable=False),
        sa.Column(
            "target_id",
            sa.String(length=36),
            sa.ForeignKey("workflow_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_port", sa.String(length=16), nullable=False),
        sa.UniqueConstraint("source_id", "source_port", name="ux_workflow_edges_output"),
    )
    op.create_index("ix_workflow_edges_workflow_id", "workflow_edges", ["workflow_id"])
    op.create_index("ix_workflow_edges_target_id", "workflow_edges", ["target_id"])


def downgrade() -> None:
    """Drop the workflow tables."""

    op.drop_table("workflow_edges")
    op.drop_table("workflow_nodes")
    op.drop_table("workflows")
