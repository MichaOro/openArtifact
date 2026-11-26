"""What the OpenAPI document says about errors and limits, defined once for every router.

The error answers are real: ``{"detail": "..."}`` from the application's handlers and middlewares
(``app.py``, ``security.py``, ``hardening.py``). The exception is ``413``, which the body limit
answers as plain text. A route lists the statuses its code can produce with :func:`errors`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

#: Executions of one artifact: ``GET .../executions`` returns the newest ``limit`` (no cursor; ``total``
#: says how many exist). The global list (``engine/history_query.py``) pages with a cursor, 1 to 200.
ARTIFACT_EXECUTIONS_DEFAULT_LIMIT = 100
ARTIFACT_EXECUTIONS_MAX_LIMIT = 500


class ErrorDetail(BaseModel):
    """The body of every refused request (except ``413``)."""

    detail: str


_JSON = {"model": ErrorDetail}
_RESPONSES: dict[int, dict[str, Any]] = {
    401: {
        **_JSON,
        "description": "No or a wrong API token (or session cookie). Only when a token is configured; "
        "``/api/v1`` always needs it. Sent with ``WWW-Authenticate: Bearer``.",
    },
    403: {
        **_JSON,
        "description": "A browser request from another site or origin (state-changing methods only).",
    },
    404: {
        **_JSON,
        "description": "The artifact, lane, graph, node, edge, execution, step or secret does not exist.",
    },
    409: {
        **_JSON,
        "description": "The request conflicts with the current state (e.g. the artifact is being processed, or a lane to delete still holds artifacts).",
    },
    413: {
        "description": "The request body is larger than the limit (``OPENARTIFACT_MAX_REQUEST_BYTES``). Plain text.",
        "content": {"text/plain": {"schema": {"type": "string"}}},
    },
    415: {**_JSON, "description": "The body is not sent as ``application/json``."},
    422: {**_JSON, "description": "A value is invalid; ``detail`` says which."},
    429: {**_JSON, "description": "As many runs are active as allowed; try again later."},
    502: {**_JSON, "description": "A provider could not be reached or did not answer usably."},
    503: {
        **_JSON,
        "description": "The server cannot take this request now (e.g. too many open event streams).",
    },
}


def errors(*codes: int, write: bool = False, body: bool = False) -> dict[int | str, dict[str, Any]]:
    """The ``responses=`` of a route: ``codes``, plus ``403``/``413`` for a state-changing method
    (``write``) and ``415`` when it takes a JSON body (``body``)."""
    chosen = list(codes)
    if write:
        chosen += [403, 413]
    if body:
        chosen.append(415)
    return {code: _RESPONSES[code] for code in sorted(set(chosen))}


#: Every router of ``/api`` answers 401 (with a token configured, the access gate asks for it).
GATED = errors(401)
