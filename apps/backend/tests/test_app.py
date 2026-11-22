"""Tests for the application factory and lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from openartifact.app import _create_app, create_app
from openartifact.config import Settings
from openartifact.version import __version__
from tests.helpers import bare_settings


def test_create_app() -> None:
    """Application factory creates a FastAPI instance."""
    settings = bare_settings()
    app = _create_app(settings)
    assert app.title == "OpenArtifact"
    assert app.version == __version__


def test_app_lifespan_hooks_exist() -> None:
    """App has lifespan configuration."""
    settings = bare_settings()
    app = _create_app(settings)
    # In newer FastAPI versions, lifespan is on the router
    assert app.router.lifespan_context is not None


def test_create_app_with_explicit_settings() -> None:
    """Factory accepts explicit settings."""
    settings = Settings(debug=True, port=8080)
    app = create_app(settings)
    assert app.version == __version__


def test_routes_registered(app_routes: Callable[[Any], list[str]]) -> None:
    """Routes are registered via create_app."""
    app = create_app()
    route_paths = app_routes(app)
    assert "/health" in route_paths
    assert "/api/info" in route_paths
    assert "/" in route_paths
