"""Application exception hierarchy.

All custom exceptions inherit from OpenArtifactError, enabling consistent
error handling across the application.
"""

from __future__ import annotations


class OpenArtifactError(Exception):
    """Base exception for all OpenArtifact errors."""


class ArtifactError(OpenArtifactError):
    """Errors related to artifact operations."""


class WorkflowError(OpenArtifactError):
    """Errors related to workflow execution."""


class ConfigurationError(OpenArtifactError):
    """Errors related to application configuration."""


class DatabaseError(OpenArtifactError):
    """Errors related to database operations."""
