"""Guard library: guard definitions and their attachments (ADR-060 addendum).

Revision ID: 0047
Revises: 0046
Create Date: 2026-11-24

``guards`` (0046) held one row per guard *and* place: what the guard is and where it watches. It is split into
``guard_definitions`` (the library: name, the scopes it may watch, trigger, condition, escalation, consequence,
fallback and its own action ``action_id``) and ``guard_attachments`` (a definition on a scope of a pipeline, switched on
or off). Every existing guard becomes one definition and one attachment that **keep its id** (two tables, so the same
id names both), with the same settings and the same on/off state: a run started after the migration freezes exactly
what it froze before. An attachment whose stage or action no longer exists watched nothing and is not carried over
(its definition is, so nothing that was written is lost); its node cannot come back, and the library could not
detach it.

Plain CREATE TABLE, INSERT .. SELECT and DROP TABLE: no table with a NOCASE collation is rebuilt (see 0043). The
downgrade recreates ``guards`` from the attachments joined with their definitions (a definition without attachments
has no place in the old table and is dropped; one used in several places becomes several rows, each with its
attachment's id).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALL_SCOPES = '["pipeline", "stage", "action"]'


def upgrade() -> None:
    op.create_table(
        "guard_definitions",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("scope_types", sa.Text(), nullable=False, server_default=ALL_SCOPES),
        sa.Column("trigger", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("condition", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("consequence", sa.String(16), nullable=False, server_default="pause"),
        sa.Column("fallback", sa.String(16), nullable=False, server_default="pause"),
        sa.Column("escalation", sa.Text(), nullable=False, server_default="[]"),
        sa.Column(
            "action_id",
            sa.String(36),
            sa.ForeignKey("graphs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "guard_attachments",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "guard_id",
            sa.String(36),
            sa.ForeignKey("guard_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "pipeline_id",
            sa.String(36),
            sa.ForeignKey("graphs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.String(36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_guard_attachments_guard_id", "guard_attachments", ["guard_id"])
    op.create_index("ix_guard_attachments_pipeline_id", "guard_attachments", ["pipeline_id"])
    op.execute(
        f"""
        INSERT INTO guard_definitions (id, name, description, scope_types, trigger, condition, consequence,
                                       fallback, escalation, action_id, created_at, updated_at)
        SELECT id, name, '', '{ALL_SCOPES}', trigger, condition, consequence, fallback, escalation,
               definition_id, created_at, updated_at
        FROM guards
        """
    )
    # a pipeline guard watches its own pipeline; a stage or action guard only a node that still exists
    op.execute(
        """
        INSERT INTO guard_attachments (id, guard_id, pipeline_id, scope_type, scope_id, enabled, created_at)
        SELECT g.id, g.id, g.pipeline_id, g.scope_type, COALESCE(g.scope_id, g.pipeline_id), g.enabled, g.created_at
        FROM guards AS g
        WHERE g.scope_type = 'pipeline'
           OR EXISTS (SELECT 1 FROM graph_nodes AS n
                      WHERE n.id = g.scope_id AND n.graph_id = g.pipeline_id AND n.kind = g.scope_type)
        """
    )
    op.drop_index("ix_guards_pipeline_id", table_name="guards")
    op.drop_table("guards")


def downgrade() -> None:
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
    op.execute(
        """
        INSERT INTO guards (id, pipeline_id, name, scope_type, scope_id, trigger, condition, consequence,
                            fallback, escalation, definition_id, enabled, created_at, updated_at)
        SELECT a.id, a.pipeline_id, d.name, a.scope_type, a.scope_id, d.trigger, d.condition, d.consequence,
               d.fallback, d.escalation, d.action_id, a.enabled, a.created_at, d.updated_at
        FROM guard_attachments AS a JOIN guard_definitions AS d ON d.id = a.guard_id
        """
    )
    op.drop_index("ix_guard_attachments_pipeline_id", table_name="guard_attachments")
    op.drop_index("ix_guard_attachments_guard_id", table_name="guard_attachments")
    op.drop_table("guard_attachments")
    op.drop_table("guard_definitions")
