"""Tests for database configuration and engine management."""

from __future__ import annotations

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from pydantic_settings import SettingsConfigDict
from sqlalchemy import text

from openartifact.config import Settings
from openartifact.database import build_engine, dispose_engine


class _TestSettings(Settings):
    """Settings without lru_cache wrapping for test isolation."""

    model_config = SettingsConfigDict(env_prefix="", env_file=".env")


def _reset_engine() -> None:
    """Reset the global engine for test isolation."""
    import openartifact.database as db_mod

    if db_mod._engine is not None:
        import asyncio

        # Use asyncio.run() instead of get_event_loop() to avoid
        # "no current event loop" errors in Python 3.12+ async contexts
        asyncio.run(db_mod.dispose_engine())


@pytest.fixture(autouse=True)
def clean_engine() -> Generator[None, None, None]:
    """Ensure engine is reset between tests."""
    _reset_engine()
    yield
    _reset_engine()


def test_default_database_path() -> None:
    """Default database URL uses /data directory."""
    s = _TestSettings()
    url = s.database_url
    assert "openartifact.db" in url
    assert "aiosqlite" in url


def test_database_url_from_custom_data_dir() -> None:
    """Database URL includes the configured data_dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        s = _TestSettings(data_dir=Path(tmpdir), database_filename="test.db")
        assert f"{tmpdir}/test.db" in s.database_url
        assert s.database_url.startswith("sqlite+aiosqlite:///")


def test_database_url_from_env() -> None:
    """Database path can be overridden via environment variables."""
    with tempfile.TemporaryDirectory() as tmpdir, pytest.MonkeyPatch.context() as mp:
        mp.setenv("OPENARTIFACT_DATA_DIR", tmpdir)
        mp.setenv("OPENARTIFACT_DATABASE_FILENAME", "custom.db")
        s = Settings()
        assert f"{tmpdir}/custom.db" in s.database_url


def test_engine_creation_creates_data_dir() -> None:
    """Building engine creates the data directory if missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_dir = Path(tmpdir) / "nonexistent" / "db"
        s = _TestSettings(data_dir=db_dir, database_filename="test.db")
        engine = build_engine(s)
        assert engine is not None
        assert db_dir.exists()


def test_engine_returns_singleton() -> None:
    """Building engine twice returns the same engine instance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        s = _TestSettings(data_dir=Path(tmpdir), database_filename="test.db")
        e1 = build_engine(s)
        e2 = build_engine(s)
        assert e1 is e2


async def test_engine_connectivity() -> None:
    """Engine can connect and execute a simple query."""
    with tempfile.TemporaryDirectory() as tmpdir:
        s = _TestSettings(data_dir=Path(tmpdir), database_filename="test.db")
        engine = build_engine(s)
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            row = result.fetchone()
            assert row is not None
            assert row[0] == 1


async def test_wal_mode_enabled() -> None:
    """WAL mode is enabled on the database engine."""
    with tempfile.TemporaryDirectory() as tmpdir:
        s = _TestSettings(data_dir=Path(tmpdir), database_filename="test.db")
        engine = build_engine(s)
        async with engine.connect() as conn:
            result = await conn.execute(text("PRAGMA journal_mode"))
            row = result.fetchone()
            assert row is not None
            assert row[0] == "wal"


async def test_dispose_engine() -> None:
    """Disposing engine resets the global and releases connections."""
    with tempfile.TemporaryDirectory() as tmpdir:
        s = _TestSettings(data_dir=Path(tmpdir), database_filename="test.db")
        engine = build_engine(s)
        assert engine is not None
        await dispose_engine()
        import openartifact.database as db_mod

        assert db_mod._engine is None
