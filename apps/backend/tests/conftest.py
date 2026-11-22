"""Shared test fixtures: isolated settings, a migrated database and a client with the real lifespan.

The database is migrated once per session into a template file; every test gets a copy, so a test
costs milliseconds instead of running all migrations again. Tests never see the developer's
``OPENARTIFACT_*`` environment or ``.env``.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient

import openartifact.database as db_mod
from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever the developer has exported (a token, a data directory ...) must not change a test."""
    for name in [n for n in os.environ if n.upper().startswith("OPENARTIFACT_")]:
        monkeypatch.delenv(name)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Provide settings pointing to a temporary directory."""
    return Settings(data_dir=tmp_path, database_filename="test.db", _env_file=None)  # type: ignore[call-arg]


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


def alembic_config() -> Config:
    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    return cfg


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
def migrated_settings(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, _migrated_template: Path
) -> Settings:
    """Settings pointing at a temp database with all migrations applied (a copy of the template)."""
    shutil.copy(_migrated_template, settings.data_dir / settings.database_filename)
    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    return settings


@pytest.fixture
def client(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    """Test client with the real lifespan (shared engine) on a migrated database."""
    with TestClient(_create_app(migrated_settings)) as c:
        yield c
    assert db_mod._engine is None
