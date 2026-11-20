"""Tests for the health endpoint (both /health and /api/health)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openartifact.api.routes import public_router, router
from openartifact.app import _create_app
from openartifact.config import Settings


@pytest.fixture
def client() -> TestClient:
    """Test client with public and API routes attached."""
    settings = Settings()
    app = _create_app(settings)
    app.include_router(public_router)
    app.include_router(router)
    return TestClient(app)


# ── /health (public path) ─────────────────────────────────────────────

def test_health_returns_200(client: TestClient) -> None:
    """Public health endpoint returns HTTP 200."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_response_schema(client: TestClient) -> None:
    """Public health response contains required fields."""
    response = client.get("/health")
    data = response.json()
    assert data["status"] == "ok"
    assert data["application"] == "OpenArtifact"
    assert data["version"] == "0.1.0"
    assert data["uptime_status"] == "running"


def test_health_response_json_content_type(client: TestClient) -> None:
    """Public health response has JSON content type."""
    response = client.get("/health")
    assert "application/json" in response.headers["content-type"]


# ── /api/health (legacy path) ─────────────────────────────────────────

def test_api_health_returns_200(client: TestClient) -> None:
    """Legacy health endpoint returns HTTP 200."""
    response = client.get("/api/health")
    assert response.status_code == 200


def test_api_health_response_schema(client: TestClient) -> None:
    """Legacy health response contains required fields."""
    response = client.get("/api/health")
    data = response.json()
    assert data["status"] == "ok"
    assert data["application"] == "OpenArtifact"
    assert data["version"] == "0.1.0"
    assert data["uptime_status"] == "running"
