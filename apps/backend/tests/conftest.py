"""Shared test fixtures: isolated settings, a migrated database and a client with the real lifespan.

The database is migrated once per session into a template file; every test gets a copy, so a test
costs milliseconds instead of running all migrations again. Tests never see the developer's
``OPENARTIFACT_*`` environment or ``.env``.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import os
import shutil
import sqlite3
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import openartifact.database as db_mod
from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import alembic_config


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever the developer has exported (a token, a data directory ...) must not change a test."""
    for name in [n for n in os.environ if n.upper().startswith("OPENARTIFACT_")]:
        monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def _restore_logging() -> Generator[None, None, None]:
    """``configure_logging`` (run by ``create_app``) changes shared loggers: put them back."""
    names = ("openartifact", "mcp", "httpx")
    saved = {
        n: (list(lg.handlers), lg.level, lg.propagate)
        for n in names
        if (lg := logging.getLogger(n))
    }
    yield
    for name, (handlers, level, propagate) in saved.items():
        logger = logging.getLogger(name)
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate


@pytest.fixture(autouse=True)
def clean_engine() -> Generator[None, None, None]:
    """No test starts or leaves a shared database engine behind."""

    def reset() -> None:
        if db_mod._engine is not None:
            asyncio.run(db_mod.dispose_engine())

    reset()
    yield
    reset()
    gc.collect()  # a leaked connection warns here, not in a random later test


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Provide settings pointing to a temporary directory (open mode, so Code nodes are opted in)."""
    return Settings(  # type: ignore[call-arg]
        data_dir=tmp_path,
        database_filename="test.db",
        code_nodes_without_token=True,  # open mode runs no Code nodes otherwise
        _env_file=None,
    )


@pytest.fixture
def app_routes() -> Callable[[Any], list[str]]:
    """Collect all route paths from a FastAPI app, including nested routers."""

    def _collect(app: Any) -> list[str]:
        paths: list[str] = []
        for route in app.routes:
            _find_paths(route, paths)
        return paths

    def _find_paths(route: Any, paths: list[str]) -> None:
        path = getattr(route, "path", None)
        if path is not None:
            paths.append(path)
            return

        # _IncludedRouter: access the included router's routes via include_context
        ctx = getattr(route, "include_context", None)
        if ctx is not None:
            inner_router = getattr(ctx, "included_router", None)
            if inner_router is not None:
                for subroute in getattr(inner_router, "routes", []):
                    _find_paths(subroute, paths)

    return _collect


@pytest.fixture(scope="session")
def _migrated_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A database with every migration applied, built once and copied for each test."""
    directory = tmp_path_factory.mktemp("template")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("OPENARTIFACT_DATA_DIR", str(directory))
        patch.setenv("OPENARTIFACT_DATABASE_FILENAME", "template.db")
        command.upgrade(alembic_config(), "head")
    with sqlite3.connect(directory / "template.db") as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return directory / "template.db"


@pytest.fixture
def unmigrated_settings(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings for an empty temp database that alembic (which reads them from the environment)
    migrates: for tests that go to a revision, seed old data and go on."""
    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    return settings


@pytest.fixture
def migrated_settings(unmigrated_settings: Settings, _migrated_template: Path) -> Settings:
    """Settings pointing at a temp database with all migrations applied (a copy of the template)."""
    shutil.copy(
        _migrated_template, unmigrated_settings.data_dir / unmigrated_settings.database_filename
    )
    return unmigrated_settings


@pytest.fixture
def client(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    """Test client with the real lifespan (shared engine) on a migrated database."""
    with TestClient(_create_app(migrated_settings)) as c:
        yield c
    assert db_mod._engine is None


@pytest.fixture
def published(client: TestClient) -> list[tuple[str, dict[str, Any]]]:
    """Record everything the app publishes on its event bus."""
    events: list[tuple[str, dict[str, Any]]] = []
    bus = client.app.state.event_bus  # type: ignore[attr-defined]
    original = bus.publish

    def spy(event_type: str, data: dict[str, Any]) -> Any:
        events.append((event_type, data))
        return original(event_type, data)

    bus.publish = spy
    return events
