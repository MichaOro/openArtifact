"""Database engine, session management, and lifecycle.

One engine and one session maker serve the whole process. Application code opens sessions only
through :func:`new_session` (outside a request) or :func:`get_db_session` (a request's dependency).

Who commits: whoever changes data. A service or route calls ``session.commit()`` itself; a session
that is closed without a commit discards its changes, so the request dependency neither commits nor
needs to roll back by hand.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Callable
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from openartifact.config import Settings
from openartifact.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""


# ── Engine Management ─────────────────────────────────────────────────

_engine: AsyncEngine | None = None
_sessions: async_sessionmaker[AsyncSession] | None = None

#: Opens a session on the shared engine (what services and the engine are given).
SessionOpener = Callable[[], AsyncSession]


def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    """WAL for concurrent reads; SQLite only enforces foreign keys when asked to, per connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_engine_for(settings: Settings, *, pragmas: bool = True) -> AsyncEngine:
    """A new async SQLite engine for the configured database file (not the shared one).

    ``pragmas`` turns on WAL and foreign keys per connection. The migrations pass ``False``: those
    that rebuild tables rely on foreign keys being off.
    """
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    if pragmas:
        event.listen(engine.sync_engine, "connect", _set_sqlite_pragma)
    return engine


def build_engine(settings: Settings) -> AsyncEngine:
    """The shared engine (WAL: concurrent reads, serialized writes), created on the first call.

    Later calls return the same engine whatever the settings. The data directory is created if it
    does not exist.
    """
    global _engine, _sessions

    if _engine is not None:
        return _engine

    db_path = settings.data_dir / settings.database_filename

    if not db_path.parent.exists():
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Created database directory: %s", db_path.parent)
        except OSError as exc:
            raise ConfigurationError(
                f"Cannot create database directory {db_path.parent}: {exc}"
            ) from exc

    _engine = create_engine_for(settings)
    _sessions = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


async def dispose_engine() -> None:
    """Dispose all database connections and release resources.

    Must be called during application shutdown to prevent connection leaks.
    """
    global _engine, _sessions

    if _engine is not None:
        await _engine.dispose()
        logger.info("Database connections disposed")
        _engine = None
        _sessions = None


# ── Session Management ──────────────────────────────────────────────


def new_session() -> AsyncSession:
    """A session on the shared engine; use it as ``async with new_session() as session``."""
    if _sessions is None:
        raise ConfigurationError("Database engine not initialized")
    return _sessions()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a session for one request (FastAPI dependency); it is closed after the response.

    Changes are committed by the route that makes them (see the module docstring).
    """
    async with new_session() as session:
        yield session
