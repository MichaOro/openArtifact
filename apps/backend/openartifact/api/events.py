"""Server-sent events endpoint (``GET /api/events``)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from openartifact.events import EventBus, event_stream

router = APIRouter(prefix="/api", tags=["events"])


def get_event_bus(request: Request) -> EventBus:
    """Return the application's event bus."""
    bus: EventBus = request.app.state.event_bus
    return bus


EventBusDep = Annotated[EventBus, Depends(get_event_bus)]


@router.get("/events")
async def stream_events(bus: EventBusDep) -> StreamingResponse:
    """Stream board events: ``task.created``, ``task.moved`` and ``task.deleted``.

    Clients that (re)connect should reload ``GET /api/tasks`` to resync, because
    events that happened while disconnected are not replayed.
    """
    return StreamingResponse(
        event_stream(bus),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
