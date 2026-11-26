"""Tests for logging configuration, secret masking and the single start path."""

from __future__ import annotations

import logging
import sys

import pytest
from fastapi.testclient import TestClient

from openartifact.app import create_app
from openartifact.config import Settings
from openartifact.logging_config import _SensitiveFilter, configure_logging

SECRET = "s3cure-token-" + "x" * 30


def _record(msg: object, *args: object) -> logging.LogRecord:
    return logging.LogRecord("openartifact", logging.INFO, __file__, 1, msg, args or None, None)


def _filtered(msg: str, *args: object, secrets: tuple[str, ...] = ()) -> str:
    record = _record(msg, *args)
    assert _SensitiveFilter(secrets).filter(record) is True
    return record.getMessage()


def test_configure_logging_sets_level_and_single_handler() -> None:
    """Calling configure_logging twice does not duplicate handlers."""
    configure_logging("DEBUG")
    configure_logging("WARNING")

    logger = logging.getLogger("openartifact")
    assert logger.level == logging.WARNING
    assert len(logger.handlers) == 1


def test_configure_logging_falls_back_to_info_for_unknown_level() -> None:
    """An invalid level name falls back to INFO."""
    configure_logging("NOT-A-LEVEL")
    assert logging.getLogger("openartifact").level == logging.INFO


def test_configure_logging_attaches_sensitive_filter() -> None:
    """The handler masks secrets."""
    configure_logging("INFO")
    handler = logging.getLogger("openartifact").handlers[0]
    assert any(isinstance(f, _SensitiveFilter) for f in handler.filters)


def test_configure_logging_keeps_records_away_from_the_root_logger() -> None:
    """Otherwise a root handler installed by a library would print every line a second time."""
    configure_logging("INFO")
    assert logging.getLogger("openartifact").propagate is False


def test_configure_logging_quiets_chatty_libraries_unless_debugging() -> None:
    configure_logging("INFO")
    assert logging.getLogger("httpx").level == logging.WARNING
    configure_logging("DEBUG")
    assert logging.getLogger("httpx").level == logging.DEBUG


def test_the_filter_masks_secret_looking_values_in_the_message() -> None:
    assert _filtered("token=abc123 for user") == "token=*** for user"
    assert _filtered("Authorization: Bearer abc.def") == "Authorization: ***"
    assert _filtered("password: hunter2, user: alice") == "password: ***, user: alice"


def test_the_filter_masks_values_in_a_dict_and_in_formatted_arguments() -> None:
    assert _filtered("settings %s", {"secret_key": "abc", "user": "alice"}) == (
        "settings {'secret_key': '***', 'user': 'alice'}"
    )
    assert _filtered("login with %s", "api_key=KEY1") == "login with api_key=***"


def test_the_filter_masks_the_configured_secrets_wherever_they_appear() -> None:
    assert _filtered(f"sent {SECRET} to the proxy", secrets=(SECRET,)) == "sent *** to the proxy"
    assert _filtered("value %s here", SECRET, secrets=(SECRET,)) == "value *** here"


def test_a_short_configured_secret_is_not_masked_by_value() -> None:
    """A one-letter key would turn every word into asterisks."""
    assert _filtered("a banana", secrets=("a",)) == "a banana"


def test_the_filter_masks_secrets_in_a_traceback() -> None:
    try:
        raise RuntimeError(f"cannot use {SECRET}")
    except RuntimeError:
        record = logging.LogRecord(
            "openartifact", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )
    _SensitiveFilter((SECRET,)).filter(record)
    assert SECRET not in logging.Formatter().format(record)


def test_plain_messages_pass_through() -> None:
    assert _filtered("hello %s", "world") == "hello world"


def test_the_application_factory_owns_the_logging_whoever_starts_it(
    settings: Settings, capfd: pytest.CaptureFixture[str]
) -> None:
    """``create_app`` configures logging after the MCP server is built, so the MCP SDK's root
    logger does not win, lines appear once, in the application's format, and secrets are masked."""
    configured = settings.model_copy(update={"log_level": "WARNING", "secret_key": SECRET})
    app = create_app(configured)
    logger = logging.getLogger("openartifact")
    assert logger.level == logging.WARNING
    assert logger.propagate is False
    assert len(logger.handlers) == 1

    logging.getLogger("openartifact.test").warning("leaked %s", SECRET)
    logging.getLogger("openartifact.test").info("below the level")
    out = capfd.readouterr().out
    assert out.count("leaked ***") == 1
    assert SECRET not in out
    assert "below the level" not in out
    assert "[WARNING " in out and "openartifact.test:" in out
    assert isinstance(app.state.settings, Settings)


def test_a_started_app_logs_through_the_configured_handler(
    migrated_settings: Settings, capfd: pytest.CaptureFixture[str]
) -> None:
    app = create_app(migrated_settings)
    with TestClient(app):
        pass
    out = capfd.readouterr().out
    assert out.count("Starting OpenArtifact") == 1
    assert out.count("Shutdown complete") == 1
