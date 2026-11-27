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
    """Stream the application's events, each with its ``event:`` name and a JSON ``data:`` payload. The browser listens
    to every name in this first list (``EVENT_TYPES`` in ``static/js/tasks/events.js``; ``tests/test_event_contract.py``
    keeps that list equal to what the server publishes and the pages handle):

    - ``task.created``, ``task.updated``, ``task.moved`` (lane or position only): the artifact; ``task.deleted``
      (``{"id"}``).
    - ``board.resync`` (``{}``): reload the list (positions renumbered, a parent deleted, the card rules applied).
    - ``board.updated`` (``{"archived", "deleted"}``, with ``"restored"`` when a card left the archive): a card was
      archived by hand or taken out of the archive, or the sweep of the card rules archived or deleted cards;
      ``board.resync`` follows.
    - ``board.lanes`` (``{"lanes": [...]}``): the lanes, after one was added, renamed, restyled or deleted; those changes
      never move artifacts.
    - ``cards.rules.changed`` (``{}``): the card rules of a lane or of the board were saved; ``board.resync`` follows.
    - ``artifact_fields.changed``: the artifact fields after they were saved (as ``GET /api/artifact-fields``).
    - ``run.updated``: the state of a run, see ``GET /api/runs``.
    - ``execution.updated`` (``{"task_id", "execution"}``): the summary of an execution, when it starts and whenever its
      status changes; ``execution.deleted`` (``{"task_id", "id"}``): by hand, by retention or by the operator's guard;
      each leaves a trace in the activity.
    - ``comment.created`` / ``comment.updated`` (the comment) and ``comment.deleted`` (``{"id", "task_id"}``).
    - ``activity.created``: an entry of the artifact's activity, see ``GET /api/tasks/{ref}/activity``.
    - ``agents.changed`` and ``providers.changed`` (``{}``): an agent or a model provider changed.
    - ``credentials.changed`` (``{"id", "name", "action"}``): a credential was created, updated, rotated, revoked,
      enabled, disabled, tested or deleted.
    - ``settings.changed``: one of ``{"run_limits"}``, ``{"retention"}``, ``{"personal"}``, ``{"stop"}`` (the STOP
      switch) or ``{"ui_layout"}``, with the new value.
    - ``storage.cleaned`` (``{"at", "entries"}``): a pass of the background storage cleaner ended.
    - ``graph.changed`` (``{"graph_ids"}``): other graphs whose nodes or edges changed with an edit (open editors
      reload); ``graph.contract_changed`` (``{"graph_id"}``): a publication or a discarded draft changed the inputs and
      outputs the pipelines that use the graph see.
    - ``agent.tool_call`` (``{"task_id", "execution_id", "agent_node_id", "tool_node_id", "tool_node_name", "tool",
      "state", "ok", "duration_ms"}``): a tool call of an agent node of a running execution started (``state``
      ``started``) or ended (``finished``, with ``ok`` and ``duration_ms``); names and states only, never arguments or
      results; the flow page shows the tool node working; ``turn`` is the round of the agent it belongs to.
    - ``agent.turn`` (``{"task_id", "execution_id", "agent_node_id", "turn", "state", "text", "finish_reason",
      "tokens", "total_tokens", "tool_calls", "wrap_up", "error"}``): a request of an agent node to its model started
      (``started``, ``wrap_up`` names the limit when it is the final answer without tools) or ended (``finished``: the
      first 300 characters of the answer, the tokens of the request and in all, the number of tool calls it asked for,
      or ``error``); the flow page shows the rounds.

    Also on the stream, but no page listens to them: ``guards.changed`` (``{"guard_id"}``, with ``"graph_id"`` and its old name
    ``"pipeline_id"`` for an attachment) and ``guard.fired`` (``{"task_id", "execution_id"}`` and the firing; the pages show the
    ``activity.created`` entry published with it).

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
