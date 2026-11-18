"""Tests for application configuration."""

from __future__ import annotations

import os

import pytest
from pydantic_settings import SettingsConfigDict

from openartifact.config import Settings


def test_settings_defaults() -> None:
    """Settings use documented defaults."""
    s = Settings()
    assert s.host == "0.0.0.0"
    assert s.port == 2909
    assert s.debug is False
    assert s.log_level == "INFO"
    assert s.database_url == "sqlite+aiosqlite:///./openartifact.db"
    assert s.data_dir == "/data"
    assert s.is_production is True


def test_settings_is_production_false() -> None:
    """Debug mode makes settings report non-production."""
    s = Settings(debug=True)
    assert s.is_production is False


def test_settings_env_prefix() -> None:
    """Settings can be overridden via OPENARTIFACT_ prefixed env vars."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("OPENARTIFACT_HOST", "127.0.0.1")
        mp.setenv("OPENARTIFACT_PORT", "9999")
        mp.setenv("OPENARTIFACT_DEBUG", "true")
        s = Settings()
        assert s.host == "127.0.0.1"
        assert s.port == 9999
        assert s.debug is True


def test_settings_env_override_int() -> None:
    """Integer settings are parsed correctly from env."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("OPENARTIFACT_PORT", "8080")
        s = Settings()
        assert s.port == 8080


def test_settings_env_override_bool() -> None:
    """Boolean settings are parsed correctly from env."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("OPENARTIFACT_DEBUG", "true")
        s = Settings()
        assert s.debug is True


def test_settings_secret_key_default() -> None:
    """Default secret key is a placeholder."""
    s = Settings()
    assert s.secret_key == "change-me-in-production"


def test_settings_invalid_env_value() -> None:
    """Invalid port value raises validation error."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("OPENARTIFACT_PORT", "not-a-number")
        with pytest.raises(ValueError):
            Settings()
