"""The health check (``/health``) and the application information endpoint (``/api/info``)."""

from __future__ import annotations

from fastapi import APIRouter

from openartifact.api.contract import GATED
from openartifact.api.schemas import HealthRead, InfoRead
from openartifact.config import get_settings
from openartifact.version import __version__

# Mounted at /health, which the Docker Compose health check uses.
public_router = APIRouter(tags=["health"])


@public_router.get("/health", response_model=HealthRead, summary="Health check")
async def health_check() -> HealthRead:
    """200 while the application runs. Open (no token, any Host header); the container health check uses it."""
    return HealthRead(
        status="ok", application="OpenArtifact", version=__version__, uptime_status="running"
    )


router = APIRouter(prefix="/api", tags=["info"], responses=GATED)


@router.get("/info", response_model=InfoRead, summary="Application info")
async def application_info() -> InfoRead:
    """The application's name, version and environment (``development`` or ``production``)."""
    return InfoRead(
        application="OpenArtifact",
        version=__version__,
        status="running",
        environment="production" if get_settings().is_production else "development",
    )
