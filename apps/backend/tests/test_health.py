"""Tests for the health endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.api.routes import router


@pytest.fixture
def client() -> TestClient:
    """Test client with routes attached."""
    settings = Settings()
    app = _create_app(settings)
    app.include_router(router)
    return TestClient(app)


def test_health_returns_200(client: TestClient) -> None:
    """Health endpoint returns HTTP 200."""
    response = client.get("/api/health")
    assert response.status_code == 200


def test_health_response_schema(client: TestClient) -> None:
    """Health response contains required fields."""
    response = client.get("/api/health")
    data = response.json()
    assert data["status"] == "ok"
    assert data["application"] == "OpenArtifact"
    assert data["version"] == "0.1.0"
    assert data["uptime_status"] == "running"


def test_health_response_json_content_type(client: TestClient) -> None:
    """Health response has JSON content type."""
    response = client.get("/api/health")
    assert "application/json" in response.headers["content-type"]
