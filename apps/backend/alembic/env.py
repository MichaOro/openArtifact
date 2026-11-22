"""Alembic environment: runs the migrations against the configured database file."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from openartifact import models  # noqa: F401  (registers every table on Base.metadata)
from openartifact.config import Settings
from openartifact.database import Base, create_engine_for, ensure_auto_vacuum

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
    """Connect with an engine of the configured database and run all pending migrations."""
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    ensure_auto_vacuum(
        settings.data_dir / settings.database_filename
    )  # before anything else uses the file
    engine = create_engine_for(settings, pragmas=False)

    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await engine.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (the async engine is driven by asyncio)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
