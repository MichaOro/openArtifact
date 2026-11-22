"""Application exception hierarchy.

All custom exceptions inherit from OpenArtifactError. ``ArtifactError`` is the refusal the services
and the engine raise; the application answers it with its ``status`` and ``message`` (see
``app.py``), so no route translates it by hand.
"""

from __future__ import annotations


class OpenArtifactError(Exception):
    """Base exception for all OpenArtifact errors."""


class ArtifactError(OpenArtifactError):
    """A request that cannot be done; ``status`` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class ConfigurationError(OpenArtifactError):
    """Errors related to application configuration."""
