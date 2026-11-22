"""Logging configuration: one handler, one format, and the secrets masked out of every line."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable

#: Names whose value is masked wherever ``name=value``, ``name: value`` or ``'name': 'value'``
#: shows up in a message (also ``Authorization: Bearer <token>``).
_SECRET_NAMES = (
    "secret_key",
    "password",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "database_url",
)
_SECRET_VALUE = re.compile(
    rf"(?i)\b({'|'.join(_SECRET_NAMES)})(['\"]?\s*[:=]\s*['\"]?)(?:bearer\s+)?[^\s,'\")}}\]]+"
)
MASK = "***"
#: A configured secret shorter than this is not masked by value: it would mangle ordinary words.
MIN_SECRET_LENGTH = 8


class _SensitiveFilter(logging.Filter):
    """Masks secrets in the finished message, the formatted arguments and a traceback.

    Two things are masked: the values passed in as ``secrets`` (the configured token and signing
    key), wherever they appear, and any value that follows a secret-looking name.
    """

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = tuple(s for s in secrets if len(s) >= MIN_SECRET_LENGTH)

    def _mask(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, MASK)
        return _SECRET_VALUE.sub(rf"\1\2{MASK}", text)

    def filter(self, record: logging.LogRecord) -> bool:
        """Replace the record's message by its masked, fully formatted form."""
        record.msg = self._mask(record.getMessage())
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self._mask(record.exc_text)
        return True


def configure_logging(level: str = "INFO", secrets: Iterable[str] = ()) -> None:
    """Configure the ``openartifact`` loggers: level, one stdout handler, secret masking.

    The handler stays on the ``openartifact`` logger and records do not propagate to the root
    logger, so a library that configures the root logger (the MCP SDK does when its server is
    built) neither duplicates nor reformats the application's lines. Call this after the
    application is built. The chatty ``mcp`` and ``httpx`` loggers log warnings only, unless the
    level is ``DEBUG``.
    """
    numeric = getattr(logging, level.upper(), logging.INFO)
    logger = logging.getLogger("openartifact")
    logger.setLevel(numeric)
    logger.propagate = False

    # Remove existing handlers to avoid duplicates on reload
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_SensitiveFilter(secrets))
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    logger.addHandler(handler)

    quiet = logging.DEBUG if numeric <= logging.DEBUG else logging.WARNING
    for noisy in ("mcp", "httpx"):
        logging.getLogger(noisy).setLevel(quiet)
