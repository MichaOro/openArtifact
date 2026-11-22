"""Board lanes as rows: the ``lanes`` table replaces the fixed set of three.

Revision ID: 0029
Revises: 0027
Create Date: 2026-11-22

``lanes`` holds the lanes of the board: ``key`` (the code artifacts carry in ``tasks.status``, never
changes), ``title`` (unique ignoring case), ``position`` (order on the board). The three lanes that
existed before are seeded with the titles in effect (the overrides of ``lane_titles`` are merged in,
then that table is dropped). ``tasks.status`` loses its CHECK constraint ``ck_tasks_status`` and gets
a foreign key to ``lanes.key`` with ``ON DELETE RESTRICT``: a lane that still holds an artifact
cannot disappear, and an artifact cannot be put into a lane that does not exist.

Downgrade: ``lane_titles`` and the CHECK constraint come back, the titles of the three default lanes
are restored (as overrides when they differ from the defaults), artifacts of custom lanes are moved to
``backlog``, and the custom lanes are lost.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0029"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULTS = (("backlog", "Backlog"), ("in_progress", "In Progress"), ("done", "Done"))
FK_NAME = "fk_tasks_status_lanes"
CHECK_NAME = "ck_tasks_status"
CHECK_SQL = "status IN ('backlog', 'in_progress', 'done')"


def upgrade() -> None:
    lanes = op.create_table(
        "lanes",
        sa.Column("key", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=40, collation="NOCASE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ux_lanes_title", "lanes", ["title"], unique=True)

    overrides: dict[str, str] = dict(
        op.get_bind().execute(sa.text("SELECT status, title FROM lane_titles")).all()
    )
    op.bulk_insert(
        lanes,
        [
            {"key": key, "title": overrides.get(key, title), "position": position}
            for position, (key, title) in enumerate(DEFAULTS)
        ],
    )
    op.drop_table("lane_titles")

    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.drop_constraint(CHECK_NAME, type_="check")
        batch.alter_column("status", existing_type=sa.String(32), server_default=None)
        batch.create_foreign_key(FK_NAME, "lanes", ["status"], ["key"], ondelete="RESTRICT")


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE tasks SET status = 'backlog' WHERE status NOT IN ('backlog', 'in_progress', 'done')"
        )
    )
    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.drop_constraint(FK_NAME, type_="foreignkey")
        batch.alter_column(
            "status", existing_type=sa.String(32), server_default=sa.text("'backlog'")
        )
        batch.create_check_constraint(CHECK_NAME, CHECK_SQL)

    titles = op.create_table(
        "lane_titles",
        sa.Column("status", sa.String(length=20), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=40, collation="NOCASE"), nullable=False),
        sa.CheckConstraint(
            "status IN ('backlog', 'in_progress', 'done')", name="ck_lane_titles_status"
        ),
    )
    current: dict[str, str] = dict(
        op.get_bind().execute(sa.text("SELECT key, title FROM lanes")).all()
    )
    op.bulk_insert(
        titles,
        [
            {"status": key, "title": current[key]}
            for key, default in DEFAULTS
            if key in current and current[key] != default
        ],
    )
    op.drop_table("lanes")
