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
    ``board.resync``, ``board.lanes`` (``{"lanes": [...]}``: the lanes, after one was added, renamed, restyled or deleted; those
    changes never move artifacts),
    ``run.updated`` (the state of a run, see ``GET /api/runs``),
    ``execution.updated`` (``{"task_id", "execution"}``: the summary of an execution, when it starts
    and whenever its status changes) and ``execution.deleted`` (``{"task_id", "id"}``: by hand,
    by retention or by the operator's guard; each leaves a trace in the activity) and ``comment.created`` / ``comment.updated`` (the comment)
    and ``comment.deleted`` (``{"id", "task_id"}``) and ``activity.created`` (an entry of the artifact's activity, see
    ``GET /api/tasks/{ref}/activity``) and ``agent.tool_call`` (``{"task_id", "execution_id", "agent_node_id",
    "tool_node_id", "tool_node_name", "tool", "state", "ok", "duration_ms"}``: a tool call of an agent node of a running
    execution started (``state`` ``started``) or ended (``finished``, with ``ok`` and ``duration_ms``); names and states only,
    never arguments or results; the flow page shows the tool node working; ``turn`` is the round of the agent it belongs to) and
    ``agent.turn`` (``{"task_id", "execution_id", "agent_node_id", "turn", "state", "text", "finish_reason", "tokens",
    "total_tokens", "tool_calls", "wrap_up", "error"}``: a request of an agent node to its model started (``started``, ``wrap_up``
    names the limit when it is the final answer without tools) or ended (``finished``: the first 300 characters of the answer, the
    tokens of the request and in all, the number of tool calls it asked for, or ``error``); the flow page shows the rounds).

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
