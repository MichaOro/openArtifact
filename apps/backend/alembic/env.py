"""Alembic environment configuration.

Handles migration execution with proper database engine and session setup.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from openartifact.config import Settings
from openartifact.database import Base

# Import all models so Alembic can detect them for autogenerate
from openartifact.models import (  # noqa: F401
    Graph,
    GraphEdge,
    GraphNode,
    PipelineRun,
    Project,
    RunStage,
    Task,
    WorkItem,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(
        config.config_file_name, disable_existing_loggers=False
    )  # keep the application loggers alive

# Set the target metadata for autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    """
    settings = Settings()
    url = settings.database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Any) -> None:
    """Run a single migration against the connection.

    Foreign keys are deliberately NOT enforced here (no ``PRAGMA foreign_keys``): migrations that
    rebuild or rename tables (0007, 0019, 0020) rely on SQLite not cascading while they do.
    """
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using async engine.

    Creates an engine from settings, connects, and runs all pending migrations.
    """
    settings = Settings()
    connect_args = {"check_same_thread": False, "timeout": 30}
    engine = create_async_engine(
        settings.database_url,
        connect_args=connect_args,
    )

    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await engine.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Runs migrations using an async engine via trio.
    """
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
