"""Managed credentials: metadata for internal tokens and external secrets (ADR-051).

Revision ID: 0040
Revises: 0039
Create Date: 2026-11-23

``credentials`` (every managed credential), ``internal_credentials`` and ``internal_tokens`` (what OpenArtifact makes:
only hashes), ``external_credentials`` (what a user gives: its non-secret fields and the last connection test) and
``credential_events`` (the audit trail). Every secret that exists is adopted as an external credential of the type
``generic_api_key`` with the same id and name, so nothing has to be entered again and ``${secret:NAME}`` keeps working.
The downgrade drops the tables; the secrets themselves are untouched.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credentials",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(64, collation="NOCASE"), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("backend", sa.String(32), nullable=True),
        sa.Column("backend_ref", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ux_credentials_name", "credentials", ["name"], unique=True)
    op.create_table(
        "internal_credentials",
        sa.Column(
            "credential_id",
            sa.String(36),
            sa.ForeignKey("credentials.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "internal_tokens",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "credential_id",
            sa.String(36),
            sa.ForeignKey("credentials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("public_id", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_internal_tokens_credential_id", "internal_tokens", ["credential_id"])
    op.create_index("ux_internal_tokens_public_id", "internal_tokens", ["public_id"], unique=True)
    op.create_table(
        "external_credentials",
        sa.Column(
            "credential_id",
            sa.String(36),
            sa.ForeignKey("credentials.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("settings", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("last_test_at", sa.DateTime(), nullable=True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_test_message", sa.String(300), nullable=True),
    )
    op.create_table(
        "credential_events",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("credential_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("detail", sa.String(300), nullable=False, server_default=""),
        sa.Column("at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_credential_events_credential_id", "credential_events", ["credential_id"])
    op.create_index("ix_credential_events_at", "credential_events", ["at"])
    # the secrets that exist become external credentials: same id, same name, nothing to enter again
    op.execute(
        sa.text(
            "INSERT INTO credentials (id, name, category, type, description, enabled, backend, backend_ref, "
            "created_at, updated_at) SELECT id, name, 'external', 'generic_api_key', '', 1, 'secret_store', name, "
            "created_at, updated_at FROM secrets"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO external_credentials (credential_id, settings) SELECT id, '{}' FROM secrets"
        )
    )


def downgrade() -> None:
    op.drop_table("credential_events")
    op.drop_table("external_credentials")
    op.drop_table("internal_tokens")
    op.drop_table("internal_credentials")
    op.drop_table("credentials")
