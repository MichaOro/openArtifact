"""Database engine, session management, and lifecycle.

Provides centralized database connection management for OpenArtifact.
All database access flows through this module — application code never
creates engines or sessions directly.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from openartifact.config import Settings
from openartifact.exceptions import ConfigurationError

logger = logging.getLogger("openartifact")


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""


# ── Engine Management ─────────────────────────────────────────────────

_engine: AsyncEngine | None = None


def _build_engine(settings: Settings) -> AsyncEngine:
    """Create an async SQLite engine with WAL mode.

    WAL (Write-Ahead Logging) provides concurrent reads with serializable
    writes, which is critical for OpenArtifact's concurrent workflow pattern.

    Args:
        settings: Application settings containing database configuration.

    Returns:
        Configured AsyncEngine.
    """
    global _engine

    if _engine is not None:
        return _engine

    db_path = settings.data_dir / settings.database_filename

    # Ensure the data directory exists
    if not db_path.parent.exists():
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Created database directory: %s", db_path.parent)
        except OSError as exc:
            raise ConfigurationError(
                f"Cannot create database directory {db_path.parent}: {exc}"
            ) from exc

    # ── Create the async engine ────────────────────────────────────
    _engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        connect_args={
            "check_same_thread": False,
            "timeout": 30,
        },
    )

    # Enable WAL mode on every new connection for concurrent read performance
    @event.listens_for(_engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:  # type: ignore[no-untyped-def]
        """Set WAL mode on new connections."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return _engine


async def dispose_engine() -> None:
    """Dispose all database connections and release resources.

    Must be called during application shutdown to prevent connection leaks.
    """
    global _engine

    if _engine is not None:
        await _engine.dispose()
        logger.info("Database connections disposed")
        _engine = None


# ── Session Management ──────────────────────────────────────────────

_async_session_factory = sessionmaker(
    expire_on_commit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session for request handling.

    Used as a FastAPI dependency for automatic session lifecycle management.
    The session is created per-request and closed after the response.
    """
    global _engine

    if _engine is None:
        raise ConfigurationError("Database engine not initialized")

    async with _async_session_factory(_engine) as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Context Manager (non-FastAPI usage) ─────────────────────────────

@asynccontextmanager
async def db_session_context(settings: Settings) -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database sessions outside of FastAPI requests.

    Creates its own engine and session — does NOT use the shared engine.
    Intended for standalone scripts, migrations, and tests.
    """
    engine = _build_engine(settings)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
