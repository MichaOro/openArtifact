"""Tests for database migration management.

Tests cover Alembic initialization, fresh database setup,
sequential migration execution, and migration failure handling.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from openartifact.config import Settings
from openartifact.database import build_engine, dispose_engine


def _reset_engine() -> None:
    """Reset the global engine for test isolation."""
    import openartifact.database as db_mod

    if db_mod._engine is not None:
        import asyncio

        # Use asyncio.run() because get_event_loop() raises in Python 3.12+
        # when no event loop exists in the current thread
        asyncio.run(db_mod.dispose_engine())


@pytest.fixture(autouse=True)
def clean_engine() -> Generator[None, None, None]:
    """Ensure engine is reset between tests."""
    _reset_engine()
    yield
    _reset_engine()


async def test_fresh_database_connection(settings: Settings) -> None:
    """Fresh database connection succeeds without pre-existing files."""
    from sqlalchemy import text

    engine = build_engine(settings)
    assert engine is not None
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        row = result.fetchone()
        assert row is not None
        assert row[0] == 1


async def test_database_file_created(tmp_path: Path) -> None:
    """Database file is created on first connection."""
    from sqlalchemy import text

    settings = Settings(data_dir=tmp_path, database_filename="test.db")
    engine = build_engine(settings)
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    assert (tmp_path / "test.db").exists()


async def test_persistence_across_reconnect(settings: Settings) -> None:
    """Data persists across engine reconnection."""
    from sqlalchemy import text

    engine = build_engine(settings)
    async with engine.connect() as conn:
        await conn.execute(text("CREATE TABLE persist_test (key TEXT)"))
        await conn.commit()

    # Dispose and reconnect
    await dispose_engine()
    engine2 = build_engine(settings)
    async with engine2.connect() as conn:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='persist_test'")
        )
        rows = result.fetchall()
        assert any(r[0] == "persist_test" for r in rows)


def test_alembic_config_exists() -> None:
    """Alembic configuration file exists."""
    assert (Path(__file__).parent.parent / "alembic.ini").exists()


def test_alembic_script_exists() -> None:
    """Alembic migration scripts directory exists."""
    versions_dir = Path(__file__).parent.parent / "alembic" / "versions"
    assert versions_dir.exists()
    scripts = list(versions_dir.glob("*.py"))
    assert len(scripts) > 0


def test_alembic_env_py_exists() -> None:
    """Alembic env.py exists."""
    env_path = Path(__file__).parent.parent / "alembic" / "env.py"
    assert env_path.exists()


def _alembic_config() -> Config:
    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    return cfg


def test_upgrade_head_and_downgrade_on_sqlite(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All migrations apply to a fresh SQLite database and can be reverted."""
    import sqlite3

    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    db_path = settings.data_dir / settings.database_filename

    command.upgrade(_alembic_config(), "head")

    with sqlite3.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"projects", "work_items"} <= tables

        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("INSERT INTO projects (id, name) VALUES ('p1', 'Demo')")
        conn.execute("INSERT INTO work_items (id, project_id, title) VALUES ('w1', 'p1', 'T')")
        # Board status is enforced by the database.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO work_items (id, project_id, title, status) VALUES ('w2','p1','T','DONE')"
            )
        # Deleting a project cascades to its work items.
        conn.execute("DELETE FROM projects WHERE id = 'p1'")
        assert conn.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0

    command.downgrade(_alembic_config(), "0001")

    with sqlite3.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {"projects", "work_items"} & tables


def test_the_models_describe_exactly_what_the_migrations_create(
    migrated_settings: Settings,
) -> None:
    """``alembic check``: no table, column, index or constraint differs between models and migrations."""
    from tests.conftest import alembic_config

    command.check(alembic_config())


def test_alembic_check_notices_a_difference(migrated_settings: Settings) -> None:
    """The check above is not vacuous: a missing index is reported."""
    import sqlite3

    from alembic.util import CommandError

    from tests.conftest import alembic_config

    with sqlite3.connect(migrated_settings.data_dir / migrated_settings.database_filename) as conn:
        conn.execute("DROP INDEX ix_tasks_parent_id")
    with pytest.raises(CommandError, match="New upgrade operations detected"):
        command.check(alembic_config())
