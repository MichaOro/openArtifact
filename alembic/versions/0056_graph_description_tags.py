"""A description and tags for pipeline and action definitions (the management pages, ADR-069).

Revision ID: 0056
Revises: 0054
Create Date: 2026-11-25

``graphs.description`` (text, empty by default) and ``graphs.tags`` (a JSON list of short labels, empty by default). The number 0055 is
reserved for the event log (card #100). The downgrade drops both columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0056"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("graphs") as batch:
        batch.add_column(sa.Column("description", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("graphs") as batch:
        batch.drop_column("tags")
        batch.drop_column("description")
