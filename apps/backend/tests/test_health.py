"""Tests for the health endpoint (``/health``)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.version import __version__
from tests.helpers import bare_settings


@pytest.fixture
def client() -> TestClient:
    """Test client on the application with its routes."""
    return TestClient(_create_app(bare_settings()))


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
    assert data["version"] == __version__
    assert data["uptime_status"] == "running"


def test_health_response_json_content_type(client: TestClient) -> None:
    """Public health response has JSON content type."""
    response = client.get("/health")
    assert "application/json" in response.headers["content-type"]
