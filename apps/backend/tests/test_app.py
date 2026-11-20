"""Tests for the application factory and lifecycle."""

from __future__ import annotations

from openartifact.app import _create_app, create_app
from openartifact.config import Settings


def test_create_app() -> None:
    """Application factory creates a FastAPI instance."""
    settings = Settings()
    app = _create_app(settings)
    assert app.title == "OpenArtifact"
    assert app.version == "0.1.0"


def test_app_lifespan_hooks_exist() -> None:
    """App has lifespan configuration."""
    settings = Settings()
    app = _create_app(settings)
    # In newer FastAPI versions, lifespan is on the router
    assert app.router.lifespan_context is not None


def test_create_app_with_explicit_settings() -> None:
    """Factory accepts explicit settings."""
    settings = Settings(debug=True, port=8080)
    app = create_app(settings)
    assert app.version == "0.1.0"


def test_routes_registered() -> None:
    """Routes are registered via create_app."""
    app = create_app()
    # FastAPI nests routes deeply in _IncludedRouter objects
    # Collect all paths recursively with unlimited depth
    route_paths: list[str] = []

    def collect_paths(routes, depth=0):
        if depth > 10:
            return
        for route in routes:
            path = getattr(route, "path", None)
            if path:
                route_paths.append(path)
            subroutes = getattr(route, "routes", None)
            if subroutes:
                collect_paths(subroutes, depth + 1)

    collect_paths(app.routes)
    assert "/api/health" in route_paths
    assert "/api/info" in route_paths
    assert "/" in route_paths
