"""Tests for database session management."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from openartifact.config import Settings
from openartifact.database import (
    _build_engine,
    db_session_context,
    get_db_session,
)
from openartifact.exceptions import ConfigurationError


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


@pytest.fixture
async def session(settings: Settings) -> Settings:
    """Ensure engine is built."""
    return settings


async def test_get_db_session_requires_initialized_engine() -> None:
    """get_db_session raises when engine is not built."""
    with pytest.raises(ConfigurationError):
        session_obj = get_db_session()
        await session_obj.__anext__()


async def test_session_is_async_generator(settings: Settings) -> None:
    """get_db_session yields an AsyncSession."""
    _build_engine(settings)
    async for session in get_db_session():
        assert session is not None


async def test_session_context(settings: Settings) -> None:
    """db_session_context provides a session without global state."""
    from sqlalchemy import text

    async with db_session_context(settings) as session:
        result = await session.execute(text("SELECT 1"))
        row = result.fetchone()
        assert row is not None
        assert row[0] == 1


async def test_session_autocommit(settings: Settings) -> None:
    """Session auto-commits on successful yield."""
    from sqlalchemy import text

    async with db_session_context(settings) as session:
        await session.execute(text("CREATE TABLE test_table (id INTEGER)"))
        await session.commit()
        # After context exit, the data should persist
    async with db_session_context(settings) as session:
        result = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'")
        )
        rows = result.fetchall()
        assert any(r[0] == "test_table" for r in rows)


async def test_session_autorollback_on_error(settings: Settings) -> None:
    """Session auto-rolls back on error within context."""
    from sqlalchemy import text

    # First ensure a table exists and insert a known row
    async with db_session_context(settings) as session:
        await session.execute(text("CREATE TABLE IF NOT EXISTS rollback_test (id INTEGER)"))
        await session.execute(text("INSERT INTO rollback_test VALUES (0)"))
        await session.commit()

    with pytest.raises(ValueError):
        async with db_session_context(settings) as session:
            await session.execute(text("INSERT INTO rollback_test VALUES (42)"))
            raise ValueError("intentional error")

    async with db_session_context(settings) as session:
        result = await session.execute(text("SELECT COUNT(*) FROM rollback_test"))
        row = result.fetchone()
        count = row[0] if row is not None else 0
        assert count == 1  # Only the pre-existing row, not the rolled-back insert


def test_build_engine_is_cached(settings: Settings) -> None:
    """A second call returns the already-built engine."""
    assert _build_engine(settings) is _build_engine(settings)


def test_build_engine_creates_missing_data_dir(tmp_path: Path) -> None:
    """The data directory is created when absent."""
    target = tmp_path / "nested" / "data"
    _build_engine(Settings(data_dir=target, database_filename="x.db"))
    assert target.is_dir()


def test_build_engine_reports_uncreatable_data_dir(tmp_path: Path) -> None:
    """A data dir below a regular file raises ConfigurationError."""
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")

    with pytest.raises(ConfigurationError, match="Cannot create database directory"):
        _build_engine(Settings(data_dir=blocker / "sub", database_filename="x.db"))


async def test_dispose_engine_resets_global(settings: Settings) -> None:
    """dispose_engine clears the shared engine and is idempotent."""
    import openartifact.database as db_mod

    _build_engine(settings)
    await db_mod.dispose_engine()
    assert db_mod._engine is None
    await db_mod.dispose_engine()


async def test_get_db_session_rolls_back_and_reraises(settings: Settings) -> None:
    """Errors thrown into the dependency trigger a rollback and propagate."""
    _build_engine(settings)
    gen = get_db_session()
    await gen.__anext__()

    with pytest.raises(ValueError, match="oops"):
        await gen.athrow(ValueError("oops"))
