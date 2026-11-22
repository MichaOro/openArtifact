"""Tests for database session management."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from openartifact.config import Settings
from openartifact.database import build_engine, get_db_session, new_session
from openartifact.exceptions import ConfigurationError
from tests.conftest import db_session_context


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
    build_engine(settings)
    async for session in get_db_session():
        assert session is not None


async def test_new_session_requires_initialized_engine() -> None:
    """Without an engine there is no session to open."""
    with pytest.raises(ConfigurationError):
        new_session()


async def test_new_session_uses_the_shared_engine(settings: Settings) -> None:
    """Sessions come from one session maker on the shared engine."""
    from sqlalchemy import text

    build_engine(settings)
    async with new_session() as session:
        assert (await session.execute(text("SELECT 1"))).scalar() == 1


async def test_a_request_session_does_not_commit_for_the_route(settings: Settings) -> None:
    """Whoever changes data commits: a session closed without a commit discards its changes."""
    from sqlalchemy import text

    build_engine(settings)
    async with new_session() as session:
        await session.execute(text("CREATE TABLE kept (id INTEGER)"))
        await session.commit()
    async for session in get_db_session():
        await session.execute(text("INSERT INTO kept VALUES (1)"))
    async for session in get_db_session():
        assert (await session.execute(text("SELECT COUNT(*) FROM kept"))).scalar() == 0
    async for session in get_db_session():
        await session.execute(text("INSERT INTO kept VALUES (2)"))
        await session.commit()
    async for session in get_db_session():
        assert (await session.execute(text("SELECT COUNT(*) FROM kept"))).scalar() == 1


async def test_the_test_session_context_commits_and_rolls_back(settings: Settings) -> None:
    """The helper the repository tests use: commit on success, roll back on an error."""
    from sqlalchemy import text

    async with db_session_context(settings) as session:
        await session.execute(text("CREATE TABLE rollback_test (id INTEGER)"))
        await session.execute(text("INSERT INTO rollback_test VALUES (0)"))
    with pytest.raises(ValueError):
        async with db_session_context(settings) as session:
            await session.execute(text("INSERT INTO rollback_test VALUES (42)"))
            raise ValueError("intentional error")
    async with db_session_context(settings) as session:
        assert (await session.execute(text("SELECT COUNT(*) FROM rollback_test"))).scalar() == 1


def test_build_engine_is_cached(settings: Settings) -> None:
    """A second call returns the already-built engine."""
    assert build_engine(settings) is build_engine(settings)


def test_build_engine_creates_missing_data_dir(tmp_path: Path) -> None:
    """The data directory is created when absent."""
    target = tmp_path / "nested" / "data"
    build_engine(Settings(data_dir=target, database_filename="x.db"))
    assert target.is_dir()


def test_build_engine_reports_uncreatable_data_dir(tmp_path: Path) -> None:
    """A data dir below a regular file raises ConfigurationError."""
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")

    with pytest.raises(ConfigurationError, match="Cannot create database directory"):
        build_engine(Settings(data_dir=blocker / "sub", database_filename="x.db"))


async def test_dispose_engine_resets_global(settings: Settings) -> None:
    """dispose_engine clears the shared engine and is idempotent."""
    import openartifact.database as db_mod

    build_engine(settings)
    await db_mod.dispose_engine()
    assert db_mod._engine is None
    await db_mod.dispose_engine()


async def test_get_db_session_rolls_back_and_reraises(settings: Settings) -> None:
    """Errors thrown into the dependency trigger a rollback and propagate."""
    build_engine(settings)
    gen = get_db_session()
    await gen.__anext__()

    with pytest.raises(ValueError, match="oops"):
        await gen.athrow(ValueError("oops"))
