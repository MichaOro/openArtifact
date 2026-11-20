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
