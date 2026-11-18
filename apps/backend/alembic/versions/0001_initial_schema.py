"""Initial migration — migration tracking infrastructure only.

This migration establishes the schema version tracking table (alembic_version).
No domain tables are included — they will be added when domain models are defined
in WP-05.

Revision ID: 0001
Revises:
Create Date: 2026-11-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Initialize migration tracking schema."""
    # The alembic_version table is created automatically by Alembic.
    # No custom tables are created in this migration.
    pass


def downgrade() -> None:
    """Remove migration tracking schema."""
    pass
