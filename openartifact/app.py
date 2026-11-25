"""The application factory: settings in, a FastAPI app out (middleware, services, routes, lifespan)."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from starlette.routing import Route

from openartifact import database
from openartifact.activity.service import ActivityService
from openartifact.agents.providers import ProviderService
from openartifact.agents.service import AgentService
from openartifact.api.agents import routers as agent_routers
from openartifact.api.artifact_fields import router as artifact_fields_router
from openartifact.api.contract import GATED
from openartifact.api.credentials import router as credentials_router
from openartifact.api.events import router as events_router
from openartifact.api.executions import router as executions_router
from openartifact.api.forms import router as forms_router
from openartifact.api.graphs import actions_router, node_types_router, pipelines_router
from openartifact.api.guards import build_guards_router
from openartifact.api.hardening import BodyLimit, CrossSiteGuard, HostCheck, SecurityHeaders
from openartifact.api.lanes import router as lanes_router
from openartifact.api.mcp import build_mcp
from openartifact.api.routes import public_router as public_api_router
from openartifact.api.routes import router as api_router
from openartifact.api.rules import router as rules_router
from openartifact.api.runs import router as runs_router
from openartifact.api.secrets import router as secrets_router
from openartifact.api.settings import build_settings_router
from openartifact.api.tasks import router as tasks_router
from openartifact.api.ui_layouts import build_ui_layouts_router
from openartifact.api.v1 import router as v1_router
from openartifact.artifact_fields.service import ArtifactFieldService
from openartifact.comments.service import CommentService
from openartifact.config import DEFAULT_SECRET_KEY, Settings, get_settings
from openartifact.credentials.service import CredentialService
from openartifact.credentials.store import SecretStore
from openartifact.engine.executors import Limits
from openartifact.engine.runner import RunEngine
from openartifact.events import EventBus
from openartifact.exceptions import (
    ArtifactError,
    ConfigurationError,
    OpenArtifactError,
)
from openartifact.guards.monitor import GuardSettings
from openartifact.guards.service import GuardService
from openartifact.logging_config import configure_logging
from openartifact.oidc import Oidc
from openartifact.security import AccessGate, TokenProtected, require_api_token
from openartifact.tasks.service import ArtifactService
from openartifact.version import __version__
from openartifact.web.navigation import build_registry
from openartifact.web.routes import router as web_router
from openartifact.web.static import RevalidatingStaticFiles

logger = logging.getLogger(__name__)


def _create_app(settings: Settings) -> FastAPI:
    """Create and configure the FastAPI application (middleware, services, handlers, routes)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Application lifespan: startup and shutdown events."""
        # ── Startup ──────────────────────────────────────────
        logger.info(
            "Starting OpenArtifact %s on %s:%d",
            __version__,
            settings.host,
            settings.port,
        )
        logger.info("Environment: %s", "production" if settings.is_production else "development")
        logger.info("Logging level: %s", settings.log_level)

        if not settings.secret_key or settings.secret_key == DEFAULT_SECRET_KEY:
            logger.warning("Using default SECRET_KEY — not suitable for production")
        if not settings.api_token:
            logger.warning(
                "No OPENARTIFACT_API_TOKEN: the web interface and the browser API are open to "
                "everyone who can reach port %d; set a token before exposing the application",
                settings.port,
            )
            if settings.code_nodes_enabled and settings.code_nodes_without_token:
                logger.warning(
                    "OPENARTIFACT_CODE_NODES_WITHOUT_TOKEN is on and no API token is set: everyone who "
                    "can reach port %d can run code as the application's user",
                    settings.port,
                )

        # ── Database initialization ──────────────────────────
        try:
            engine = database.build_engine(settings)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Database connected at %s", settings.data_dir / settings.database_filename)
        except ConfigurationError:
            raise
        except Exception as exc:
            logger.error("Database connection failed: %s", exc)
            raise ConfigurationError(f"Cannot connect to database: {exc}") from exc

        try:
            await app.state.engine.recover()  # no run survives a restart as "running"
        except OperationalError:
            logger.warning("Run recovery skipped: the database is not migrated yet")

        async with app.state.mcp_app.router.lifespan_context(app.state.mcp_app):
            yield

        # ── Shutdown ─────────────────────────────────────────
        await app.state.engine.shutdown()
        app.state.event_bus.close()

        logger.info("Shutting down OpenArtifact %s", __version__)
        await database.dispose_engine()
        logger.info("Shutdown complete")

    if problems := settings.security_problems():
        raise ConfigurationError("; ".join(problems))

    app = FastAPI(
        title="OpenArtifact",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.event_bus = EventBus(max_subscribers=settings.max_sse_subscribers)
    app.state.secret_store = SecretStore(database.new_session, settings)
    app.state.credentials = CredentialService(
        database.new_session, app.state.secret_store, settings, app.state.event_bus
    )
    app.state.comments = CommentService(database.new_session, app.state.event_bus)
    app.state.navigation = (
        build_registry()
    )  # the sidebar and the rail of the artifact dialog (ADR-066)
    app.state.activity = ActivityService(database.new_session)
    app.state.engine = RunEngine(
        app.state.event_bus,
        database.new_session,
        max_runs=settings.max_concurrent_runs,
        limits=Limits.from_settings(
            settings,
            app.state.secret_store.resolve,
            app.state.comments,
            app.state.credentials.settings_of,
            app.state.event_bus.publish,
        ),
        history_default_keep=settings.execution_history_default_keep,
        guards=GuardSettings(
            min_interval_seconds=settings.guard_min_interval_seconds,
            max_firings=settings.guard_max_firings,
            timeout_seconds=settings.guard_timeout_seconds,
            heartbeat_spacing_seconds=settings.heartbeat_min_spacing_seconds,
        ),
    )
    app.state.guards = GuardService(
        database.new_session, app.state.event_bus, settings.guard_min_interval_seconds
    )
    app.state.artifacts = ArtifactService(
        database.new_session, app.state.event_bus, app.state.engine
    )
    app.state.artifact_fields = ArtifactFieldService(database.new_session, app.state.event_bus)
    app.state.agents = AgentService(database.new_session, app.state.event_bus)
    app.state.providers = ProviderService(
        database.new_session, app.state.event_bus, settings, app.state.secret_store
    )
    app.state.settings = settings
    app.state.oidc = Oidc(settings) if settings.oidc_enabled else None
    # Added innermost first: a request meets the headers, the host check, the body limit and the
    # cross-site guard before the access gate.
    app.add_middleware(AccessGate, settings=settings)
    app.add_middleware(CrossSiteGuard)
    app.add_middleware(BodyLimit, limit=settings.max_request_bytes)
    app.add_middleware(HostCheck, allowed=settings.allowed_host_list)
    app.add_middleware(SecurityHeaders, settings=settings)
    # The MCP server (Streamable HTTP, stateless) answers at /mcp; it is open only with the API token.
    # host="0.0.0.0" switches the SDK's own DNS-rebinding check off: the bearer token (TokenProtected)
    # and the HostCheck middleware above are the protection, and HostCheck also covers /mcp.
    app.state.mcp_app = build_mcp(
        app.state.artifacts,
        app.state.secret_store,
        app.state.artifact_fields,
        app.state.agents,
        app.state.providers,
        app.state.comments,
        app.state.activity,
        app.state.guards,
        app.state.engine,
    ).streamable_http_app(stateless_http=True, json_response=True, host="0.0.0.0")
    app.router.routes.append(Route("/mcp", endpoint=TokenProtected(app.state.mcp_app, settings)))

    # ── Exception handlers ─────────────────────────────────────────

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        # FastAPI's default echoes the rejected input, which cannot always be sent as JSON (Infinity)
        detail = [{k: v for k, v in e.items() if k not in ("input", "ctx")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.exception_handler(ArtifactError)
    async def _handle_refusal(request: Request, exc: ArtifactError) -> JSONResponse:
        # the same body HTTPException produces: the services refuse, routes do not translate
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.exception_handler(OpenArtifactError)
    async def _handle_app_error(request: Request, exc: OpenArtifactError) -> JSONResponse:
        logger.warning("Application error: %s", exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ConfigurationError)
    async def _handle_config_error(request: Request, exc: ConfigurationError) -> JSONResponse:
        logger.error("Configuration error: %s", exc)
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # The server logs the traceback itself (the exception is raised on after this handler);
        # this line says which request it was, in the application's format.
        logger.error("Unexpected %s on %s %s", type(exc).__name__, request.method, request.url.path)
        message = f"Error: {exc}" if settings.debug else "Internal server error"
        return JSONResponse(status_code=500, content={"detail": message})

    # ── Register routes ────────────────────────────────────────────
    app.include_router(public_api_router)
    app.include_router(api_router)
    app.include_router(tasks_router)
    app.include_router(lanes_router)
    app.include_router(artifact_fields_router)
    app.include_router(executions_router)
    app.include_router(node_types_router)
    app.include_router(pipelines_router)
    app.include_router(actions_router)
    app.include_router(runs_router)
    app.include_router(rules_router)
    app.include_router(forms_router)
    app.include_router(
        build_guards_router("/api", ["guards"], editor=True), dependencies=[], responses=GATED
    )
    app.include_router(secrets_router)
    app.include_router(credentials_router)
    app.include_router(v1_router)
    for router in agent_routers([Depends(require_api_token)]):
        app.include_router(router)
    app.include_router(build_settings_router("/api", ["settings"]))
    app.include_router(build_ui_layouts_router("/api", ["ui-layouts"]))
    app.include_router(
        build_settings_router("/api/v1", ["integration API"], [Depends(require_api_token)])
    )
    app.include_router(
        build_ui_layouts_router("/api/v1", ["integration API"], [Depends(require_api_token)])
    )
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
    """The application factory (``uvicorn --factory``): reads the settings, builds the app, logs.

    Logging is configured last: building the MCP server makes the MCP SDK set up the root logger,
    and the application's handler and level must be the ones that count.
    """
    if settings is None:
        settings = get_settings()
    app = _create_app(settings)
    configure_logging(settings.log_level, secrets=(settings.api_token, settings.secret_key))
    return app
