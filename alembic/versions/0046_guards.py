"""Guards: scoped, event or interval driven specialised actions (ADR-060).

Revision ID: 0046
Revises: 0045
Create Date: 2026-11-24

``guards``: one row per guard, attached to a scope of a pipeline (the pipeline itself, a stage or an action: node
ids, no foreign key to the node, a guard whose node is gone watches nothing), with its trigger, its condition tree
(``when``), its consequence, the fallback, the escalation steps (JSON) and its own action (``definition_id``, an action
definition, ``SET NULL`` when that is deleted). Rows go with their pipeline (``ON DELETE CASCADE``).

``executions.guard_state``: the counters of the run per scope and per guard, the last heartbeat and the guard
firings (JSON text, ``{}`` for every existing execution). Plain ``ADD COLUMN``: no table is rebuilt (the NOCASE
collations of other tables stay untouched, see 0043). The downgrade drops the column and the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guards",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "pipeline_id",
            sa.String(36),
            sa.ForeignKey("graphs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.String(36), nullable=True),
        sa.Column("trigger", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("condition", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("consequence", sa.String(16), nullable=False, server_default="pause"),
        sa.Column("fallback", sa.String(16), nullable=False, server_default="pause"),
        sa.Column("escalation", sa.Text(), nullable=False, server_default="[]"),
        sa.Column(
            "definition_id",
            sa.String(36),
            sa.ForeignKey("graphs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_guards_pipeline_id", "guards", ["pipeline_id"])
    op.add_column(
        "executions",
        sa.Column("guard_state", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("executions", "guard_state")
    op.drop_index("ix_guards_pipeline_id", table_name="guards")
    op.drop_table("guards")
