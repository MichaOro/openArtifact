"""The per-artifact history policy is gone (ADR-057).

Revision ID: 0043
Revises: 0042
Create Date: 2026-11-23

``tasks.history_keep_last`` and ``tasks.history_keep_hours`` (migration 0023) are dropped: the global retention rules
(ADR-052) replace them. Plain ``ALTER TABLE ... DROP COLUMN`` (no batch rebuild: ``tasks`` has indexes and keys a rebuild
must not touch). The downgrade adds the columns back, empty (the values are not kept).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE tasks DROP COLUMN history_keep_last"))
    op.execute(sa.text("ALTER TABLE tasks DROP COLUMN history_keep_hours"))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE tasks ADD COLUMN history_keep_last INTEGER"))
    op.execute(sa.text("ALTER TABLE tasks ADD COLUMN history_keep_hours INTEGER"))
