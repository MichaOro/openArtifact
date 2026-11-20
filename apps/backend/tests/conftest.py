"""Shared test fixtures.

Fixtures for database sessions, application client, and test data factories
will be added alongside implementation in WP-03.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from openartifact.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Provide settings pointing to a temporary directory."""
    return Settings(data_dir=tmp_path, database_filename="test.db")


@pytest.fixture
def app_routes() -> Callable[[Any], list[str]]:
    """Collect all route paths from a FastAPI app, recursively."""

    def _collect(app: Any) -> list[str]:
        paths: list[str] = []
        for route in app.routes:
            # Recursively find all paths including nested routers
            _find_paths(route, paths)
        return paths

    def _find_paths(route: Any, paths: list[str]) -> None:
        path = getattr(route, "path", None)
        if path:
            paths.append(path)
        subroutes = getattr(route, "routes", None)
        if subroutes:
            for subroute in subroutes:
                _find_paths(subroute, paths)

    return _collect
