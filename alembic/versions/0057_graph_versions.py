"""Versions of pipelines and actions (ADR-070).

Revision ID: 0057
Revises: 0056
Create Date: 2026-11-25

``graph_versions`` holds the published versions of a graph (a frozen copy of its nodes and edges, written once); ``graphs.published_number``
points to the one executions use (``NULL``: nothing published, the draft runs as before). The number 0055 is reserved for the event log
(card #100). The downgrade drops the table and the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "graph_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("graph_id", sa.String(36), sa.ForeignKey("graphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("source_number", sa.Integer(), nullable=True),
        sa.Column("published_via", sa.String(16), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("graph_id", "number", name="ux_graph_versions_number"),
    )
    op.create_index("ix_graph_versions_graph_id", "graph_versions", ["graph_id"])
    with op.batch_alter_table("graphs") as batch:
        batch.add_column(sa.Column("published_number", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("graphs") as batch:
        batch.drop_column("published_number")
    op.drop_index("ix_graph_versions_graph_id", table_name="graph_versions")
    op.drop_table("graph_versions")
