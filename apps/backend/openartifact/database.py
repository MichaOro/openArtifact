"""Database engine and session configuration.

Provides async database connections using SQLAlchemy with aiosqlite.
Migrations are managed by Alembic.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from openartifact.config import get_settings


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session for request handling.

    Used as a FastAPI dependency for automatic session lifecycle management.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=settings.debug)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        try:
            yield session
        finally:
            await engine.dispose()


@asynccontextmanager
async def get_db_session_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database sessions outside of FastAPI requests."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=settings.debug)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        try:
            yield session
        finally:
            await engine.dispose()
