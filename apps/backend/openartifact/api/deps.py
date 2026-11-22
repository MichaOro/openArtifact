"""What route handlers ask FastAPI for: the request's session and the services on ``app.state``."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.database import get_db_session
from openartifact.engine.runner import RunEngine
from openartifact.events import EventBus
from openartifact.tasks.service import ArtifactService

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_artifacts(request: Request) -> ArtifactService:
    """The application's artifact service."""
    service: ArtifactService = request.app.state.artifacts
    return service


def get_engine(request: Request) -> RunEngine:
    """The application's execution engine."""
    engine: RunEngine = request.app.state.engine
    return engine


def get_event_bus(request: Request) -> EventBus:
    """The application's event bus."""
    bus: EventBus = request.app.state.event_bus
    return bus


ServiceDep = Annotated[ArtifactService, Depends(get_artifacts)]
EngineDep = Annotated[RunEngine, Depends(get_engine)]
EventBusDep = Annotated[EventBus, Depends(get_event_bus)]
