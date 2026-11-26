"""Lane titles the user changed.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-22

``lane_titles`` holds only overrides of the default titles in ``tasks/lanes.py``: a lane without a
row shows its default. The downgrade drops the table (the custom titles are lost).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lane_titles",
        sa.Column("status", sa.String(length=20), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=40), nullable=False),
        sa.CheckConstraint(
            "status IN ('backlog', 'in_progress', 'done')", name="ck_lane_titles_status"
        ),
    )


def downgrade() -> None:
    op.drop_table("lane_titles")
