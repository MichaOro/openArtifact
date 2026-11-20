"""API routes for OpenArtifact.

Provides the health check endpoint and application information endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter

from openartifact.config import get_settings

# ── Shared health check implementation ───────────────────────────────

def _health_response() -> dict[str, str | int]:
    """Return the health check payload."""
    return {
        "status": "ok",
        "application": "OpenArtifact",
        "version": "0.1.0",
        "uptime_status": "running",
    }


# ── Public health check (no prefix) ──────────────────────────────────
# Mounted at /health — matches Docker Compose health check and public docs.

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
    return _health_response()


# ── API routes (prefix=/api) ────────────────────────────────────────

router = APIRouter(prefix="/api")


@router.get("/health")
async def api_health_check() -> dict[str, str | int]:
    """Health check endpoint (legacy path /api/health).

    Backwards-compatible alias — delegates to the same implementation.
    """
    return _health_response()


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
