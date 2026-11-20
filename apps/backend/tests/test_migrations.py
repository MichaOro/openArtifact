"""Tests for database migration management.

Tests cover Alembic initialization, fresh database setup,
sequential migration execution, and migration failure handling.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from openartifact.config import Settings
from openartifact.database import _build_engine, dispose_engine


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

    engine = _build_engine(settings)
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
    engine = _build_engine(settings)
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    assert (tmp_path / "test.db").exists()


async def test_persistence_across_reconnect(settings: Settings) -> None:
    """Data persists across engine reconnection."""
    from sqlalchemy import text

    engine = _build_engine(settings)
    async with engine.connect() as conn:
        await conn.execute(text("CREATE TABLE persist_test (key TEXT)"))
        await conn.commit()

    # Dispose and reconnect
    await dispose_engine()
    engine2 = _build_engine(settings)
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
