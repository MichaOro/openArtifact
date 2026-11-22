"""The health check (``/health``) and the application information endpoint (``/api/info``)."""

from __future__ import annotations

from fastapi import APIRouter

from openartifact.config import get_settings
from openartifact.version import __version__

# Mounted at /health, which the Docker Compose health check uses.
public_router = APIRouter()


@public_router.get("/health")
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
        "version": __version__,
        "uptime_status": "running",
    }


router = APIRouter(prefix="/api")


@router.get("/info")
async def application_info() -> dict[str, str | int]:
    """Application information endpoint.

    Returns the application identity, version and environment.

    Response schema:
    - application: "OpenArtifact"
    - version: application version string
    - status: runtime status
    - environment: "development" or "production"
    """
    return {
        "application": "OpenArtifact",
        "version": __version__,
        "status": "running",
        "environment": "production" if get_settings().is_production else "development",
    }
