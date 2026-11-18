"""API routes for OpenArtifact.

Provides the health check endpoint and application information endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter

from openartifact.config import get_settings

router = APIRouter(prefix="/api")


@router.get("/health")
async def health_check() -> dict[str, str | int]:
    """Health check endpoint.

    Returns HTTP 200 when the application runtime is operational.
    Used for Docker health checks and monitoring.

    Response schema:
    - status: "ok"
    - application: "OpenArtifact"
    - version: application version string
    - uptime_status: "running"
    """
    return {
        "status": "ok",
        "application": "OpenArtifact",
        "version": "0.1.0",
        "uptime_status": "running",
    }


@router.get("/info")
async def application_info() -> dict[str, str | int]:
    """Application information endpoint.

    Returns basic application identity and version.
    The version is sourced from project metadata.

    Response schema:
    - application: "OpenArtifact"
    - version: application version string
    - status: runtime status
    """
    settings = get_settings()
    return {
        "application": "OpenArtifact",
        "version": "0.1.0",
        "status": "running",
        "environment": "development" if settings.debug else "production",
    }
