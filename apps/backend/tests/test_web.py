"""Tests for the web application shell."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from openartifact.api.routes import public_router as api_public_router
from openartifact.api.routes import router as api_router
from openartifact.app import _create_app
from openartifact.web.routes import router as web_router


@pytest.fixture
def app() -> FastAPI:
    """FastAPI app with all routes attached."""
    from openartifact.config import Settings

    settings = Settings()
    a = _create_app(settings)
    a.include_router(api_public_router)
    a.include_router(api_router)
    a.include_router(web_router)
    # Serve static files for template test
    Jinja2Templates(
        directory=str(Path(__file__).parent.parent / "openartifact" / "templates"),
    )
    a.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).parent.parent / "openartifact" / "static")),
        name="static",
    )
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Test client for the full app."""
    return TestClient(app)


# ── Root path (web shell) ─────────────────────────────────────────────


def test_root_returns_200(client: TestClient) -> None:
    """Root path returns HTTP 200 with HTML."""
    response = client.get("/")
    assert response.status_code == 200


def test_root_contains_html(client: TestClient) -> None:
    """Root page contains OpenArtifact identity."""
    response = client.get("/")
    assert "OpenArtifact" in response.text


def test_root_contains_version(client: TestClient) -> None:
    """Root page displays version."""
    response = client.get("/")
    assert "0.1.0" in response.text


def test_root_contains_htmx(client: TestClient) -> None:
    """Root page includes HTMX script."""
    response = client.get("/")
    assert "htmx.org" in response.text


# ── Health endpoints ──────────────────────────────────────────────────


def test_health_public_returns_200(client: TestClient) -> None:
    """Public health endpoint returns HTTP 200."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_public_is_json(client: TestClient) -> None:
    """Public health endpoint returns JSON content type."""
    response = client.get("/health")
    assert "application/json" in response.headers["content-type"]


def test_health_api_returns_200(client: TestClient) -> None:
    """Legacy health endpoint returns HTTP 200."""
    response = client.get("/api/health")
    assert response.status_code == 200


def test_health_api_is_json(client: TestClient) -> None:
    """Legacy health endpoint returns JSON content type."""
    response = client.get("/api/health")
    assert "application/json" in response.headers["content-type"]


def test_health_responses_are_equivalent(client: TestClient) -> None:
    """Both health endpoints return identical data."""
    pub = client.get("/health").json()
    api = client.get("/api/health").json()
    assert pub == api
