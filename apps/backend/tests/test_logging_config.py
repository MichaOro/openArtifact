"""Tests for logging configuration and secret masking."""

from __future__ import annotations

import logging
from collections.abc import Generator

import pytest

from openartifact.logging_config import _SensitiveFilter, configure_logging


@pytest.fixture(autouse=True)
def restore_logger() -> Generator[None, None, None]:
    """Restore the shared 'openartifact' logger after each test."""
    logger = logging.getLogger("openartifact")
    handlers, level = list(logger.handlers), logger.level
    yield
    logger.handlers[:] = handlers
    logger.setLevel(level)


def _record(msg: object) -> logging.LogRecord:
    return logging.LogRecord("openartifact", logging.INFO, __file__, 1, msg, None, None)


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


def test_sensitive_filter_masks_secret_fields() -> None:
    """Secret keys in dict messages are masked, other keys are kept."""
    record = _record({"secret_key": "abc", "Password": "pw", "user": "alice"})

    assert _SensitiveFilter().filter(record) is True
    assert record.msg == {"secret_key": "***", "Password": "***", "user": "alice"}


def test_sensitive_filter_leaves_string_messages_untouched() -> None:
    """Plain string messages pass through."""
    record = _record("hello")

    assert _SensitiveFilter().filter(record) is True
    assert record.msg == "hello"
