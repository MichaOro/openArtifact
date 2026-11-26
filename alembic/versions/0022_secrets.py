"""Credential store: the ``secrets`` table.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-22

A secret is a name (capitals, digits, underscores) and a value encrypted with AES-GCM under a key derived
from ``OPENARTIFACT_SECRET_KEY`` (see ``secret_crypto.py``). Execution nodes refer to secrets by name.
The downgrade drops the table with every stored secret; nodes that refer to a name keep the reference
(it then fails at run time with "Secret NAME does not exist").
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "secrets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("value", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ux_secrets_name", "secrets", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_secrets_name", table_name="secrets")
    op.drop_table("secrets")
