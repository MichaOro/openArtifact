"""Tests for the application-wide exception handlers."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.exceptions import (
    ArtifactError,
    ConfigurationError,
    DatabaseError,
    OpenArtifactError,
)


def _app_raising(settings: Settings, exc: Exception) -> FastAPI:
    app = _create_app(settings)

    @app.get("/_boom")
    async def _boom() -> None:
        raise exc

    return app


def test_application_error_returns_400() -> None:
    """Domain errors map to HTTP 400 with their message."""
    client = TestClient(_app_raising(Settings(), ArtifactError("bad artifact")))
    response = client.get("/_boom")
    assert response.status_code == 400
    assert response.json() == {"detail": "bad artifact"}


def test_base_application_error_returns_400() -> None:
    """The base error type is handled the same way."""
    client = TestClient(_app_raising(Settings(), OpenArtifactError("generic")))
    assert client.get("/_boom").status_code == 400


def test_configuration_error_returns_503() -> None:
    """Configuration errors map to HTTP 503 and expose their message."""
    client = TestClient(_app_raising(Settings(), ConfigurationError("no db")))
    response = client.get("/_boom")
    assert response.status_code == 503
    assert response.json() == {"detail": "no db"}


def test_database_error_returns_503_without_details() -> None:
    """Database errors map to HTTP 503 and hide internals."""
    client = TestClient(_app_raising(Settings(), DatabaseError("secret path /data/x.db")))
    response = client.get("/_boom")
    assert response.status_code == 503
    assert response.json() == {"detail": "Service unavailable"}


def test_unexpected_error_hides_details_in_production() -> None:
    """Unknown errors yield a generic 500 when debug is off."""
    client = TestClient(
        _app_raising(Settings(debug=False), RuntimeError("internal detail")),
        raise_server_exceptions=False,
    )
    response = client.get("/_boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}


def test_unexpected_error_includes_details_in_debug() -> None:
    """Unknown errors expose the message when debug is on."""
    client = TestClient(
        _app_raising(Settings(debug=True), RuntimeError("internal detail")),
        raise_server_exceptions=False,
    )
    response = client.get("/_boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "Error: internal detail"}
