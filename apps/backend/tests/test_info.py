"""Tests for the application info endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.version import __version__


@pytest.fixture
def client() -> TestClient:
    """Test client on the application with its routes."""
    return TestClient(_create_app(Settings()))


def test_info_returns_200(client: TestClient) -> None:
    """Info endpoint returns HTTP 200."""
    response = client.get("/api/info")
    assert response.status_code == 200


def test_info_response_schema(client: TestClient) -> None:
    """Info response contains required fields."""
    response = client.get("/api/info")
    data = response.json()
    assert data["application"] == "OpenArtifact"
    assert data["version"] == __version__
    assert data["status"] == "running"
    assert "environment" in data


def test_info_default_environment(client: TestClient) -> None:
    """Info returns production environment by default (debug=False)."""
    response = client.get("/api/info")
    data = response.json()
    assert data["environment"] == "production"
