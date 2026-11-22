"""Tests for the application-wide exception handlers."""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.exceptions import (
    ArtifactError,
    ConfigurationError,
    OpenArtifactError,
)
from tests.helpers import bare_settings


def _app_raising(settings: Settings, exc: Exception) -> FastAPI:
    app = _create_app(settings)

    @app.get("/_boom")
    async def _boom() -> None:
        raise exc

    return app


def test_a_refusal_is_answered_with_its_status_and_message() -> None:
    """ArtifactError carries the HTTP status; no route translates it by hand."""
    client = TestClient(_app_raising(bare_settings(), ArtifactError(409, "bad artifact")))
    response = client.get("/_boom")
    assert response.status_code == 409
    assert response.json() == {"detail": "bad artifact"}


def test_a_refusal_is_not_logged_as_an_error(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(_app_raising(bare_settings(), ArtifactError(422, "nope")))
    with caplog.at_level(logging.DEBUG, logger="openartifact"):
        assert client.get("/_boom").status_code == 422
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_base_application_error_returns_400_and_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The base error type is answered with 400 and logged as a warning, not as an error."""
    client = TestClient(_app_raising(bare_settings(), OpenArtifactError("generic")))
    with caplog.at_level(logging.WARNING, logger="openartifact"):
        assert client.get("/_boom").status_code == 400
    assert [r.levelno for r in caplog.records if "generic" in r.getMessage()] == [logging.WARNING]


def test_configuration_error_returns_503() -> None:
    """Configuration errors map to HTTP 503 and expose their message."""
    client = TestClient(_app_raising(bare_settings(), ConfigurationError("no db")))
    response = client.get("/_boom")
    assert response.status_code == 503
    assert response.json() == {"detail": "no db"}


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


def test_an_unexpected_error_is_logged_with_the_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The log line names the exception class and the request, never the message."""
    client = TestClient(
        _app_raising(Settings(debug=False), RuntimeError("internal detail")),
        raise_server_exceptions=False,
    )
    with caplog.at_level(logging.ERROR, logger="openartifact"):
        client.get("/_boom")
    line = next(r.getMessage() for r in caplog.records if r.levelno == logging.ERROR)
    assert line == "Unexpected RuntimeError on GET /_boom"
