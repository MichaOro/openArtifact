"""Application factory and lifecycle management.

Creates the FastAPI application instance with proper configuration,
lifespan hooks, and exception handlers.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from openartifact.config import Settings
from openartifact.database import session_factory
from openartifact.engine.runner import RunEngine
from openartifact.events import EventBus
from openartifact.exceptions import (
    ConfigurationError,
    DatabaseError,
    OpenArtifactError,
)
from openartifact.web.static import RevalidatingStaticFiles

logger = logging.getLogger("openartifact")


def _create_app(settings: Settings) -> FastAPI:
    """Create and configure the FastAPI application.

    The app is created with a proper lifespan context manager for startup
    and shutdown, exception handlers, and middleware. Routes are registered
    separately.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Application lifespan: startup and shutdown events."""
        # ── Startup ──────────────────────────────────────────
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

        # ── Database initialization ──────────────────────────
        from openartifact.database import _build_engine

        try:
            engine = _build_engine(settings)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Database connected at %s", settings.data_dir / settings.database_filename)
        except ConfigurationError:
            raise
        except Exception as exc:
            logger.error("Database connection failed: %s", exc)
            raise ConfigurationError(f"Cannot connect to database: {exc}") from exc

        await app.state.engine.recover()  # no run survives a restart as "running"

        yield

        # ── Shutdown ─────────────────────────────────────────
        from openartifact.database import dispose_engine

        await app.state.engine.shutdown()
        app.state.event_bus.close()

        logger.info("Shutting down OpenArtifact 0.1.0")
        await dispose_engine()
        logger.info("Shutdown complete")

    app = FastAPI(
        title="OpenArtifact",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.event_bus = EventBus()
    app.state.engine = RunEngine(app.state.event_bus, session_factory)

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

    @app.exception_handler(ConfigurationError)
    async def _handle_config_error(
        request: Request,
        exc: ConfigurationError,
    ) -> JSONResponse:
        logger.error("Configuration error: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc)},
        )

    @app.exception_handler(DatabaseError)
    async def _handle_db_error(
        request: Request,
        exc: DatabaseError,
    ) -> JSONResponse:
        logger.error("Database error: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"detail": "Service unavailable"},
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
    from openartifact.api.events import router as events_router
    from openartifact.api.routes import public_router as public_api_router
    from openartifact.api.routes import router as api_router
    from openartifact.api.runs import router as runs_router
    from openartifact.api.tasks import router as tasks_router
    from openartifact.api.workflows import router as workflows_router
    from openartifact.web.routes import router as web_router

    app.include_router(public_api_router)
    app.include_router(api_router)
    app.include_router(tasks_router)
    app.include_router(workflows_router)
    app.include_router(runs_router)
    app.include_router(events_router)
    app.include_router(web_router)

    # ── Static assets (CSS / JS of the web UI) ─────────────────────
    app.mount(
        "/static",
        RevalidatingStaticFiles(directory=str(Path(__file__).parent / "static")),
        name="static",
    )

    return app


def create_app(settings: Settings | None = None) -> FastAPI:
    """Entry point for creating the application.

    Reads settings from environment, creates the app instance, and returns it.
    Accepts an optional explicit settings object for testing.
    """
    from openartifact.config import get_settings

    if settings is None:
        settings = get_settings()
    return _create_app(settings)
