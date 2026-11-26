"""Application exception hierarchy.

All custom exceptions inherit from OpenArtifactError. ``ArtifactError`` is the refusal the services
and the engine raise; the application answers it with its ``status`` and ``message`` (see
``app.py``), so no route translates it by hand.
"""

from __future__ import annotations

from typing import Any


class OpenArtifactError(Exception):
    """Base exception for all OpenArtifact errors."""


class ArtifactError(OpenArtifactError):
    """A request that cannot be done; ``status`` is the HTTP status to answer with.

    ``code`` is an optional stable word a program can match on (``stopped``); the message is for people. ``extra`` is more data for the
    answer's body (the findings of the check before publishing, ADR-082).
    """

    def __init__(
        self,
        status: int,
        message: str,
        code: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.extra = extra


class ConfigurationError(OpenArtifactError):
    """Errors related to application configuration."""
