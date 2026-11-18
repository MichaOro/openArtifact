"""Tests for the application info endpoint."""

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


def test_info_returns_200(client: TestClient) -> None:
    """Info endpoint returns HTTP 200."""
    response = client.get("/api/info")
    assert response.status_code == 200


def test_info_response_schema(client: TestClient) -> None:
    """Info response contains required fields."""
    response = client.get("/api/info")
    data = response.json()
    assert data["application"] == "OpenArtifact"
    assert data["version"] == "0.1.0"
    assert data["status"] == "running"
    assert "environment" in data


def test_info_default_environment(client: TestClient) -> None:
    """Info returns development environment by default."""
    response = client.get("/api/info")
    data = response.json()
    assert data["environment"] == "development"
