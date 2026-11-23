"""Migration 0040 (ADR-051): the secrets that exist become external credentials; nothing has to be entered again."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from alembic import command
from tests.helpers import alembic_config


def test_existing_secrets_are_adopted_as_external_credentials_and_the_downgrade_leaves_them(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0039")
    with sqlite3.connect(db) as conn:
        for n, name in enumerate(("GITHUB_TOKEN", "API_KEY")):
            conn.execute(
                "INSERT INTO secrets (id, name, value, created_at, updated_at) VALUES (?, ?, ?, '2026-01-01', '2026-01-02')",
                (f"s{n}", name, b"blob"),
            )
    command.upgrade(alembic_config(), "0040")
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT id, name, category, type, enabled, backend, backend_ref FROM credentials ORDER BY name"
        ).fetchall()
        assert rows == [
            ("s1", "API_KEY", "external", "generic_api_key", 1, "secret_store", "API_KEY"),
            (
                "s0",
                "GITHUB_TOKEN",
                "external",
                "generic_api_key",
                1,
                "secret_store",
                "GITHUB_TOKEN",
            ),
        ]
        assert conn.execute("SELECT count(*) FROM external_credentials").fetchone() == (2,)
        assert conn.execute("SELECT count(*) FROM secrets").fetchone() == (
            2,
        )  # the secrets are untouched
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"internal_credentials", "internal_tokens", "credential_events"} <= names
        # names are unique ignoring case
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute(
                "INSERT INTO credentials (id, name, category, type, created_at, updated_at) "
                "VALUES ('x', 'api_key', 'internal', 'api_access_token', '2026-01-01', '2026-01-01')"
            )
            raise AssertionError("a name differing only in case was accepted")
        except sqlite3.IntegrityError:
            pass
    command.downgrade(alembic_config(), "0039")
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "credentials" not in tables and "internal_tokens" not in tables
        assert conn.execute("SELECT count(*) FROM secrets").fetchone() == (2,)
    command.upgrade(alembic_config(), "head")
