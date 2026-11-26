"""*Retry on fail* (ADR-073): a node that failed is tried again, only itself, after a wait; the run does not start over.

The setting is ``config.retry`` of a node (``{"enabled", "max_tries", "wait_ms"}``, checked when it is saved by
``graph/node_types.py``). ``max_tries`` counts the first try. :func:`tried` runs something until it succeeds or the tries are used up
and says what the failed tries before the last one were; the engine uses it for a node (``runner._run_definition``) and for an
action (``runner._run_actions``).

The wait is ``asyncio.sleep``: it does not block the event loop and ends at once when the run is stopped (the task is cancelled). A
cancellation, whether the user's Stop or a guard's, is never caught here, so it is never retried. A node that ran into its own
timeout is a failure of that try like any other.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from openartifact.graph.node_types import RETRY_DEFAULT_TRIES, RETRY_DEFAULT_WAIT_MS, retry_error


@dataclass(frozen=True)
class Retry:
    max_tries: int
    wait_ms: int


def retry_of(node: Mapping[str, Any]) -> Retry | None:
    """The retry a node asks for; ``None`` when it asks for none, it is switched off or a stored value is not valid (never a guess)."""
    value = (node.get("config") or {}).get("retry")
    if (
        not isinstance(value, dict)
        or retry_error(value) is not None
        or not value.get("enabled", True)
    ):
        return None
    return Retry(
        int(value.get("max_tries", RETRY_DEFAULT_TRIES)),
        int(value.get("wait_ms", RETRY_DEFAULT_WAIT_MS)),
    )


async def tried[T](
    run: Callable[[], Awaitable[T]],
    failure: Callable[[T], str | None],
    retry: Retry | None,
) -> tuple[T, list[dict[str, Any]]]:
    """``run()`` until ``failure(value)`` is ``None`` (it worked) or ``retry.max_tries`` tries are used: the last value, and the failed
    tries before it as ``{"try", "reason", "duration_ms"}`` (empty when the first try was the only one)."""
    earlier: list[dict[str, Any]] = []
    number = 0
    while True:
        number += 1
        started = time.monotonic()
        value = await run()
        reason = failure(value)
        if reason is None or retry is None or number >= retry.max_tries:
            return value, earlier
        earlier.append(
            {
                "try": number,
                "reason": reason[:1000],
                "duration_ms": int((time.monotonic() - started) * 1000),
            }
        )
        await asyncio.sleep(retry.wait_ms / 1000)
