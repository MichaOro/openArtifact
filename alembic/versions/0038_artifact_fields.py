"""Artifact fields: one list of fields every artifact has, instead of artifact types (ADR-044).

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-23

``artifact_types``, ``artifact_type_fields`` and ``tasks.type_id`` go; ``tasks.parameters`` becomes
``tasks.field_values`` and starts empty (the owner chose a clean model over keeping the values of types).
``artifact_fields`` holds the global list. The downgrade restores the empty structure of 0031.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_NAME = "fk_tasks_type_id"
INDEX_NAME = "ix_tasks_type_id"


def upgrade() -> None:
    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.drop_index(INDEX_NAME)
        batch.drop_constraint(FK_NAME, type_="foreignkey")
        batch.drop_column("type_id")
        batch.drop_column("parameters")
        batch.add_column(sa.Column("field_values", sa.Text(), nullable=False, server_default="{}"))
    op.drop_table("artifact_type_fields")
    op.drop_table("artifact_types")
    op.create_table(
        "artifact_fields",
        sa.Column("name", sa.String(32), primary_key=True, nullable=False),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("default_json", sa.Text(), nullable=True),
        sa.Column("options_json", sa.Text(), nullable=True),
        sa.Column("max_length", sa.Integer(), nullable=True),
        sa.Column("min_value", sa.Float(), nullable=True),
        sa.Column("max_value", sa.Float(), nullable=True),
        sa.Column("integer_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("position", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("artifact_fields")
    op.create_table(
        "artifact_types",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(60, collation="NOCASE"), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "artifact_type_fields",
        sa.Column(
            "type_id",
            sa.String(36),
            sa.ForeignKey("artifact_types.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(32), primary_key=True, nullable=False),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_json", sa.Text(), nullable=True),
        sa.Column("options_json", sa.Text(), nullable=True),
        sa.Column("max_length", sa.Integer(), nullable=True),
        sa.Column("min_value", sa.Float(), nullable=True),
        sa.Column("max_value", sa.Float(), nullable=True),
        sa.Column("integer_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.drop_column("field_values")
        batch.add_column(sa.Column("type_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("parameters", sa.Text(), nullable=False, server_default="{}"))
        batch.create_foreign_key(
            FK_NAME, "artifact_types", ["type_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_index(INDEX_NAME, ["type_id"])
