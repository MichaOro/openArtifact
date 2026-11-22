"""Artifact types and card parameters.

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-22

``artifact_types`` and ``artifact_type_fields`` hold what the user defines (a type and its typed
parameters); ``tasks.type_id`` (``NULL``: untyped, as before) and ``tasks.parameters`` (JSON object
text) hold what an artifact has. A type that artifacts use cannot be deleted (``RESTRICT``), the
fields go with their type (``CASCADE``). Existing artifacts stay untyped with ``{}``.

The downgrade drops the column pair and both tables: types, fields and parameter values are lost.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_NAME = "fk_tasks_type_id"
INDEX_NAME = "ix_tasks_type_id"


def upgrade() -> None:
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
        batch.add_column(sa.Column("type_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("parameters", sa.Text(), nullable=False, server_default="{}"))
        batch.create_foreign_key(
            FK_NAME, "artifact_types", ["type_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_index(INDEX_NAME, ["type_id"])


def downgrade() -> None:
    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.drop_index(INDEX_NAME)
        batch.drop_constraint(FK_NAME, type_="foreignkey")
        batch.drop_column("parameters")
        batch.drop_column("type_id")
    op.drop_table("artifact_type_fields")
    op.drop_table("artifact_types")
