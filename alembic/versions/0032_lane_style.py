"""How a lane draws its cards: ``lanes.style``.

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-22

``style`` is ``normal`` (the default) or ``finished`` (card titles struck through and dimmed, set in the
lane's settings). Existing lanes get ``normal``. The service validates the value; the database keeps
a CHECK as the safety net.

Downgrade: the column is dropped, the lanes keep everything else.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK_NAME = "ck_lanes_style"


def upgrade() -> None:
    with op.batch_alter_table("lanes") as batch:
        batch.add_column(
            sa.Column("style", sa.String(length=16), nullable=False, server_default="normal")
        )
        batch.create_check_constraint(CHECK_NAME, "style IN ('normal', 'finished')")


def downgrade() -> None:
    with op.batch_alter_table("lanes") as batch:
        batch.drop_constraint(CHECK_NAME, type_="check")
        batch.drop_column("style")
