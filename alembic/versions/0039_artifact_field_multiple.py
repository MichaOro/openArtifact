"""Artifact fields: a choice may hold several values (multi select, ADR-050).

Revision ID: 0039
Revises: 0038
Create Date: 2026-11-23

``artifact_fields.multiple`` (false for every existing field: they stay single selects). The downgrade removes it;
a stored list of a multi select is then not a valid value of the single select it becomes, and the next change of the
field list says so.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text("ALTER TABLE artifact_fields ADD COLUMN multiple BOOLEAN NOT NULL DEFAULT 0")
    )


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE artifact_fields DROP COLUMN multiple"))
