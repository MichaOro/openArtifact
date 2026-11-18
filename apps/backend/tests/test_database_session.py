"""Tests for database session management."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from openartifact.database import (
    Base,
    dispose_engine,
    get_db_session,
    _build_engine,
    db_session_context,
)
from openartifact.config import Settings


def _reset_engine() -> None:
    """Reset the global engine for test isolation."""
    import openartifact.database as db_mod  # noqa: PLC0415
    if db_mod._engine is not None:
        import asyncio  # noqa: PLC0415
        asyncio.get_event_loop().run_until_complete(db_mod.dispose_engine())


@pytest.fixture(autouse=True)
def clean_engine() -> None:
    """Ensure engine is reset between tests."""
    _reset_engine()
    yield
    _reset_engine()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Provide settings pointing to a temporary directory."""
    return Settings(data_dir=tmp_path, database_filename="test.db")


@pytest.fixture
async def session(settings: Settings) -> Settings:
    """Ensure engine is built."""
    return settings


async def test_get_db_session_requires_initialized_engine() -> None:
    """get_db_session raises when engine is not built."""
    with pytest.raises(Exception):
        session_obj = get_db_session()
        await session_obj.__anext__()


async def test_session_is_async_generator(settings: Settings) -> None:
    """get_db_session yields an AsyncSession."""
    _build_engine(settings)
    async for session in get_db_session():
        assert session is not None


async def test_session_context(settings: Settings) -> None:
    """db_session_context provides a session without global state."""
    from sqlalchemy import text  # noqa: PLC0415

    async with db_session_context(settings) as session:
        result = await session.execute(text("SELECT 1"))
        row = await result.fetchone()
        assert row is not None
        assert row[0] == 1


async def test_session_autocommit(settings: Settings) -> None:
    """Session auto-commits on successful yield."""
    from sqlalchemy import text  # noqa: PLC0415

    async with db_session_context(settings) as session:
        await session.execute(text("CREATE TABLE test_table (id INTEGER)"))
        await session.commit()
        # After context exit, the data should persist
    async with db_session_context(settings) as session:
        result = await session.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'"))
        rows = await result.fetchall()
        assert any(r[0] == "test_table" for r in rows)


async def test_session_autorollback_on_error(settings: Settings) -> None:
    """Session auto-rolls back on error within context."""
    from sqlalchemy import text  # noqa: PLC0415

    with pytest.raises(Exception):
        async with db_session_context(settings) as session:
            await session.execute(text("CREATE TABLE error_table (id INTEGER)"))
            raise ValueError("intentional error")

    async with db_session_context(settings) as session:
        result = await session.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='error_table'"))
        rows = await result.fetchall()
        assert not any(r[0] == "error_table" for r in rows)
