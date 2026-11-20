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
    # In newer FastAPI versions, app.routes includes _IncludedRouter which has no .path
    route_paths: list[str] = []
    for route in app.routes:
        if hasattr(route, "path"):
            route_paths.append(route.path)
        elif hasattr(route, "routes"):
            for subroute in route.routes:
                if hasattr(subroute, "path"):
                    route_paths.append(subroute.path)
    assert "/api/health" in route_paths
    assert "/api/info" in route_paths
    assert "/" in route_paths
