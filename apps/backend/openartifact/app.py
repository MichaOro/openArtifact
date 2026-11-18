"""Application factory and lifecycle management.

Creates the FastAPI application instance with proper configuration,
lifecycle hooks, and exception handlers.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from openartifact.config import Settings
from openartifact.exceptions import OpenArtifactError

logger = logging.getLogger("openartifact")


def _create_app(settings: Settings) -> FastAPI:
    """Create and configure the FastAPI application.

    The app is created with proper lifespan hooks for startup and shutdown,
    exception handlers, and middleware. Routes are registered separately.
    """

    async def _startup() -> None:
        """Application startup: log identity, validate configuration."""
        logger.info(
            "Starting OpenArtifact %s on %s:%d",
            "0.1.0",
            settings.host,
            settings.port,
        )
        logger.info("Environment: %s", "development" if settings.debug else "production")
        logger.info("Logging level: %s", settings.log_level)

        if not settings.secret_key or settings.secret_key == "change-me-in-production":
            logger.warning("Using default SECRET_KEY — not suitable for production")

    async def _shutdown() -> None:
        """Application shutdown: release resources."""
        logger.info("Shutting down OpenArtifact 0.1.0")

    app = FastAPI(
        title="OpenArtifact",
        version="0.1.0",
        lifespan={"startup": _startup, "shutdown": _shutdown},
        docs_url="/api/docs",
        redoc_url=None,
    )

    # ── Exception handlers ─────────────────────────────────────────

    @app.exception_handler(OpenArtifactError)
    async def _handle_app_error(
        request: Request,
        exc: OpenArtifactError,
    ) -> JSONResponse:
        logger.error("Application error: %s", exc)
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        if settings.debug:
            logger.exception("Unexpected error: %s", exc)
            message = f"Error: {exc}"
        else:
            logger.error("Unexpected error: %s", type(exc).__name__)
            message = "Internal server error"
        return JSONResponse(
            status_code=500,
            content={"detail": message},
        )

    # ── Register routes ────────────────────────────────────────────
    from openartifact.api.routes import router as api_router  # noqa: PLC0415
    from openartifact.web.routes import router as web_router  # noqa: PLC0415

    app.include_router(api_router)
    app.include_router(web_router)

    return app


def create_app(settings: Settings | None = None) -> FastAPI:
    """Entry point for creating the application.

    Reads settings from environment, creates the app instance, and returns it.
    Accepts an optional explicit settings object for testing.
    """
    from openartifact.config import get_settings  # noqa: PLC0415

    if settings is None:
        settings = get_settings()
    return _create_app(settings)
