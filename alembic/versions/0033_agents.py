"""Agents, LLM providers and the detail of a step.

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-22

``llm_providers`` and ``llm_models`` hold where agents send their requests and which models may be
chosen; ``agents`` and ``agent_versions`` hold the reusable agent definitions (an editable draft and the
published versions, which are never changed). ``run_node_results.detail`` keeps what only a step shows
(an agent's prompts and attempts); it goes with its execution like every other column of the row. The
kind check of ``graph_nodes`` gains ``agent``.

The downgrade deletes agent nodes (with their connections, the old kind check cannot hold them), drops
the column and the four tables: agents, versions, providers, models and step details are lost.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "'trigger', 'stage', 'action', 'complete', 'output', 'timer', 'pipeline', 'code', 'http', "
    "'if', 'switch'"
)
NEW_KINDS = f"{OLD_KINDS}, 'agent'"
CHECK = "ck_graph_nodes_kind"


def upgrade() -> None:
    op.create_table(
        "llm_providers",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(60, collation="NOCASE"), nullable=False, unique=True),
        sa.Column("base_url", sa.String(500), nullable=True),
        sa.Column("secret_name", sa.String(64), nullable=True),
        sa.Column("allow_private", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_model", sa.String(200), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("check_ok", sa.Boolean(), nullable=True),
        sa.Column("check_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "llm_models",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "provider_id",
            sa.String(36),
            sa.ForeignKey("llm_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("label", sa.String(200), nullable=False, server_default=""),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("available", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("provider_id", "model_id", name="ux_llm_models_provider"),
    )
    op.create_index("ix_llm_models_provider_id", "llm_models", ["provider_id"])
    op.create_table(
        "agents",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(100, collation="NOCASE"), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("draft", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("published_number", sa.Integer(), nullable=True),
        sa.Column("version_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "agent_id",
            sa.String(36),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("source_number", sa.Integer(), nullable=True),
        sa.Column("published_via", sa.String(16), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("agent_id", "number", name="ux_agent_versions_number"),
    )
    op.create_index("ix_agent_versions_agent_id", "agent_versions", ["agent_id"])
    op.add_column("run_node_results", sa.Column("detail", sa.JSON(), nullable=True))
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, f"kind IN ({NEW_KINDS})")


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM graph_nodes WHERE kind = 'agent'"))
    with op.batch_alter_table("graph_nodes", recreate="always") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, f"kind IN ({OLD_KINDS})")
    with op.batch_alter_table("run_node_results") as batch:
        batch.drop_column("detail")
    op.drop_index("ix_agent_versions_agent_id", "agent_versions")
    op.drop_table("agent_versions")
    op.drop_table("agents")
    op.drop_index("ix_llm_models_provider_id", "llm_models")
    op.drop_table("llm_models")
    op.drop_table("llm_providers")
