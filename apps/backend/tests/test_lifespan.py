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


@pytest.fixture(autouse=True)
async def clean_engine() -> None:
    """Make sure no engine leaks between tests."""
    await db_mod.dispose_engine()


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
