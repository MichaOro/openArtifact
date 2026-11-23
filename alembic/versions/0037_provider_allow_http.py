"""LLM providers: any address is fine, only http needs the owner's confirmation.

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-23

``llm_providers.allow_private`` (a private address needed the provider's switch and the operator's) is replaced by
``allow_http``: a provider on any address works, and an ``http://`` address needs this confirmation that the
unencrypted connection is fine. A provider that uses http now keeps working: it is confirmed by the upgrade. The
downgrade restores ``allow_private`` from ``allow_http`` (a local address needed it).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Plain ALTER TABLE: a batch rebuild of the table would lose the case-insensitive collation of ``name``
# (SQLite's own ADD COLUMN and DROP COLUMN leave the rest of the table as it is).


def upgrade() -> None:
    op.execute(
        sa.text("ALTER TABLE llm_providers ADD COLUMN allow_http BOOLEAN NOT NULL DEFAULT 0")
    )
    op.execute(
        sa.text("UPDATE llm_providers SET allow_http = 1 WHERE lower(base_url) LIKE 'http://%'")
    )
    op.execute(sa.text("ALTER TABLE llm_providers DROP COLUMN allow_private"))


def downgrade() -> None:
    op.execute(
        sa.text("ALTER TABLE llm_providers ADD COLUMN allow_private BOOLEAN NOT NULL DEFAULT 0")
    )
    op.execute(sa.text("UPDATE llm_providers SET allow_private = allow_http"))
    op.execute(sa.text("ALTER TABLE llm_providers DROP COLUMN allow_http"))
