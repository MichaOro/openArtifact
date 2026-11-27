"""Lane ids: every lane gets a UUID, the address of a lane in the interfaces (ADR-090).

Revision ID: 0069
Revises: 0068
Create Date: 2026-11-27

``lanes.uuid`` (unique). Added with a plain ``ADD COLUMN``, never a rebuild of ``lanes``: ``tasks.status`` points at the lane's key with a foreign
key and a rebuild would take the cards with it. Every lane that exists gets a fresh uuid4. The views the guard actions read stand on ``lanes`` and
``tasks`` and are made again at every start, after the migrations; both directions drop them first (the lesson of 0066 to 0068).
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0069"
down_revision: str | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUARD_VIEWS = (
    "v_guard_runs",
    "v_guard_steps",
    "v_guard_tool_calls",
    "v_guard_artifacts",
    "v_guard_lanes",
)


def _drop_guard_views() -> None:
    for view in GUARD_VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {view}")


def upgrade() -> None:
    _drop_guard_views()
    # the empty default is only what a row written by hand gets; the application always sets a uuid, and the backfill below does for the old rows
    op.add_column("lanes", sa.Column("uuid", sa.String(36), nullable=False, server_default=""))
    bind = op.get_bind()
    for (key,) in bind.execute(sa.text("SELECT key FROM lanes")).fetchall():
        bind.execute(
            sa.text("UPDATE lanes SET uuid = :uuid WHERE key = :key"),
            {"uuid": str(uuid.uuid4()), "key": key},
        )
    op.create_index("ux_lanes_uuid", "lanes", ["uuid"], unique=True)


def downgrade() -> None:
    _drop_guard_views()
    op.drop_index("ux_lanes_uuid", table_name="lanes")
    op.execute("ALTER TABLE lanes DROP COLUMN uuid")
