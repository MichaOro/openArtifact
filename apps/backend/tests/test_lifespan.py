"""Tests for the application lifespan (startup and shutdown)."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import openartifact.database as db_mod
from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.exceptions import ConfigurationError


def test_lifespan_connects_database_and_disposes_on_shutdown(settings: Settings) -> None:
    """Startup opens the database; shutdown disposes the shared engine."""
    app = _create_app(settings)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert db_mod._engine is not None
        assert (settings.data_dir / settings.database_filename).exists()

    assert db_mod._engine is None


def test_lifespan_warns_about_default_secret_key(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    """The default secret key is flagged at startup."""
    app = _create_app(settings)

    with caplog.at_level(logging.WARNING, logger="openartifact"), TestClient(app):
        pass

    assert "Using default SECRET_KEY" in caplog.text


def test_lifespan_no_warning_with_custom_secret_key(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A custom secret key does not trigger the warning."""
    settings = Settings(data_dir=tmp_path, database_filename="t.db", secret_key="s3cret")
    app = _create_app(settings)

    with caplog.at_level(logging.WARNING, logger="openartifact"), TestClient(app):
        pass

    assert "Using default SECRET_KEY" not in caplog.text


def test_lifespan_warns_when_code_nodes_run_without_a_token(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    """Opt-in for Code nodes in open mode is flagged once at startup; with a token it is not."""
    opted_in = settings.model_copy(update={"code_nodes_without_token": True, "api_token": ""})
    with caplog.at_level(logging.WARNING, logger="openartifact"), TestClient(_create_app(opted_in)):
        pass
    assert caplog.text.count("OPENARTIFACT_CODE_NODES_WITHOUT_TOKEN is on") == 1

    caplog.clear()
    refused = settings.model_copy(update={"code_nodes_without_token": False, "api_token": ""})
    with caplog.at_level(logging.WARNING, logger="openartifact"), TestClient(_create_app(refused)):
        pass
    assert "OPENARTIFACT_CODE_NODES_WITHOUT_TOKEN is on" not in caplog.text


def test_lifespan_wraps_unexpected_database_errors(settings: Settings) -> None:
    """Unexpected connection errors surface as ConfigurationError."""
    app = _create_app(settings)

    with (
        patch("openartifact.database.build_engine", side_effect=RuntimeError("boom")),
        pytest.raises(ConfigurationError, match="Cannot connect to database: boom"),
        TestClient(app),
    ):
        pass


def test_lifespan_propagates_configuration_errors(settings: Settings) -> None:
    """ConfigurationError from engine creation is not re-wrapped."""
    app = _create_app(settings)

    with (
        patch(
            "openartifact.database.build_engine",
            side_effect=ConfigurationError("bad dir"),
        ),
        pytest.raises(ConfigurationError, match=r"^bad dir$"),
        TestClient(app),
    ):
        pass
