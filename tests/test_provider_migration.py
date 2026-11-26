"""Migration 0037: ``allow_private`` of a provider becomes ``allow_http`` (any address is fine now)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from alembic import command
from tests.helpers import alembic_config

INSERT = (
    "INSERT INTO llm_providers (id, kind, name, base_url, allow_private, is_default, created_at, updated_at) "
    "VALUES (?, 'openai_compatible', ?, ?, ?, 0, '2026-01-01', '2026-01-01')"
)


def test_a_provider_on_http_keeps_working_after_the_upgrade_and_the_downgrade_restores_the_switch(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0036")
    with sqlite3.connect(db) as conn:
        conn.execute(INSERT, ("p1", "Plain", "http://10.0.0.5:4000/v1", 1))
        conn.execute(INSERT, ("p2", "Secure", "https://llm.example/v1", 0))
        conn.execute(INSERT, ("p3", "Mixed", "HTTP://host/v1", 0))
    command.upgrade(alembic_config(), "0037")
    with sqlite3.connect(db) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(llm_providers)")}
        assert "allow_http" in columns and "allow_private" not in columns
        # an http address is confirmed by the upgrade (it worked before), an https one needs nothing
        assert dict(conn.execute("SELECT name, allow_http FROM llm_providers")) == {
            "Plain": 1,
            "Secure": 0,
            "Mixed": 1,
        }
        # the rest of the table stays as it was: names are still unique without regard to case
        found = conn.execute("SELECT id FROM llm_providers WHERE name = 'plain'").fetchall()
        assert found == [("p1",)]
    command.downgrade(alembic_config(), "0036")
    with sqlite3.connect(db) as conn:
        assert dict(conn.execute("SELECT name, allow_private FROM llm_providers")) == {
            "Plain": 1,
            "Secure": 0,
            "Mixed": 1,
        }
    command.upgrade(alembic_config(), "head")
