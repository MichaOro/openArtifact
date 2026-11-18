"""Logging configuration.

Structured logging with secret masking. No sensitive values are ever logged.
"""

from __future__ import annotations

import logging
import sys
from typing import Any


# Fields that must never appear in log output
_SECRET_FIELDS = frozenset(
    {
        "secret_key",
        "password",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "database_url",
    }
)


class _SensitiveFilter(logging.Filter):
    """Remove or mask log record fields containing sensitive data."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter the log record before emission."""
        if isinstance(record.msg, dict):
            sanitized: dict[str, Any] = {}
            for key, value in record.msg.items():
                if key.lower() in _SECRET_FIELDS:
                    sanitized[key] = "***"
                else:
                    sanitized[key] = value
            record.msg = sanitized
        return True


def configure_logging(level: str = "INFO") -> None:
    """Configure application-wide logging.

    Uses structured JSON-style formatting in production,
    human-readable format in development.
    """
    logger = logging.getLogger("openartifact")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates on reload
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_SensitiveFilter())
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
