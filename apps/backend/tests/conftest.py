"""Shared test fixtures.

Fixtures for database sessions, application client, and test data factories
will be added alongside implementation in WP-03.
"""

from __future__ import annotations

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


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Provide settings pointing to a temporary directory."""
    return Settings(data_dir=tmp_path, database_filename="test.db")


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


@pytest.fixture
def migrated_settings(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings pointing at a temp database with all migrations applied."""
    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    command.upgrade(alembic_config(), "head")
    return settings


@pytest.fixture
def client(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    """Test client with the real lifespan (shared engine) on a migrated database."""
    with TestClient(_create_app(migrated_settings)) as c:
        yield c
    assert db_mod._engine is None
