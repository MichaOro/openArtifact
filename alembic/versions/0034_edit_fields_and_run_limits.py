"""The Edit Fields node and the run limits.

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-23

The kind check of ``graph_nodes`` gains ``set`` (the Edit Fields node; its settings live in ``config``).
``app_settings`` holds settings users change at run time, one row per key with a JSON value; a key without a row
has its default, so an empty table means the limits of before (1000 steps, no time limit).

The downgrade deletes Edit Fields nodes (with their connections) and drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "'trigger', 'stage', 'action', 'complete', 'output', 'timer', 'pipeline', 'code', 'http', "
    "'if', 'switch', 'agent'"
)
NEW_KINDS = f"{OLD_KINDS}, 'set'"
CHECK = "ck_graph_nodes_kind"


def upgrade() -> None:
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, f"kind IN ({NEW_KINDS})")
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), primary_key=True, nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.execute(sa.text("DELETE FROM graph_nodes WHERE kind = 'set'"))
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, f"kind IN ({OLD_KINDS})")
