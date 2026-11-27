"""Retry on fail: a step knows how many tries its node took (ADR-073).

Revision ID: 0059
Revises: 0058
Create Date: 2026-11-26

``run_node_results.attempts`` (1 for every step that exists: a node that ran once). The failed tries before the last one of a node that
was tried again are in the step's ``detail`` (``tries``), which needs no column. The downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("run_node_results") as batch:
        batch.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    with op.batch_alter_table("run_node_results") as batch:
        batch.drop_column("attempts")
