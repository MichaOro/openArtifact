"""Server-sent events endpoint (``GET /api/events``)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from openartifact.api.contract import GATED, errors
from openartifact.api.deps import EventBusDep
from openartifact.events import event_stream

router = APIRouter(prefix="/api", tags=["events"], responses=GATED)


@router.get(
    "/events",
    summary="Stream board events",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "A server-sent event stream (``event:`` name, ``data:`` JSON).",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        **errors(503),
    },
)
async def stream_events(bus: EventBusDep) -> StreamingResponse:
    """Stream board events: ``task.created``, ``task.updated``, ``task.moved``, ``task.deleted``,
    ``board.resync``, ``board.lanes`` (``{"lanes": [...]}``: the lanes, after one was added, renamed or deleted; those
    changes never move artifacts),
    ``run.updated`` (the state of a run, see ``GET /api/runs``),
    ``execution.updated`` (``{"task_id", "execution"}``: the summary of an execution, when it starts
    and whenever its status changes) and ``execution.deleted`` (``{"task_id", "id"}``: by hand,
    by retention or because the artifact's policy changed).

    Clients that (re)connect should reload ``GET /api/tasks`` to resync, because
    events that happened while disconnected are not replayed.
    """
    if bus.full:
        raise HTTPException(503, "Too many open event streams")
    return StreamingResponse(
        event_stream(bus),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
