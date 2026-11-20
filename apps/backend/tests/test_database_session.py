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

    with pytest.raises(ValueError):
        async with db_session_context(settings) as session:
            await session.execute(text("CREATE TABLE error_table (id INTEGER)"))
            raise ValueError("intentional error")

    async with db_session_context(settings) as session:
        result = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='error_table'")
        )
        rows = result.fetchall()
        assert not any(r[0] == "error_table" for r in rows)
