"""One request to a model, with its time limits and retries (the part of the agent runtime that talks to the provider).

:func:`run_completion` makes the request (through :mod:`~openartifact.agents.client`) and tries again after a failure that can pass:
a network error, a timeout, HTTP 408, 429 or 5xx. The waits are 3, 10, 30 and 60 seconds; a ``Retry-After`` of a 429 replaces the
wait. The time of the whole node always wins: an attempt gets at most what is left of it, and no wait is started that would not
leave time for another attempt. Waiting is ``asyncio.sleep``, so stopping the run ends it at once.

**After a timeout the next attempt gets more time** (:data:`TIMEOUT_GROWTH` times the one before, at most
:data:`ATTEMPT_TIMEOUT_CAP`): a model that did not answer a large prompt in time will not answer it in the same time again, and
the identical request with the identical limit, repeated, only costs the node's time. (A node that has run tools and cannot get its
answer at all writes its final answer from a shortened conversation instead: ``agents/loop.py``.)
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from openartifact.agents import client
from openartifact.agents.client import Completion, Endpoint, ProviderError
from openartifact.agents.schemas import (
    REQUEST_TIMEOUT_DEFAULT,
    RETRIES_DEFAULT,
    RETRIES_MAX,
    TOTAL_TIMEOUT_DEFAULT,
)
from openartifact.agents.tools import Toolbox

#: The wait before the first, second, third and fourth retry.
BACKOFF_SECONDS = (3.0, 10.0, 30.0, 60.0)
assert len(BACKOFF_SECONDS) == RETRIES_MAX
#: After a timeout the next attempt may take this many times as long, but never more than the cap (seconds).
TIMEOUT_GROWTH = 1.5
ATTEMPT_TIMEOUT_CAP = 300.0

Complete = Callable[..., Awaitable[Completion]]
Sleep = Callable[[float], Awaitable[None]]
OpenTools = Callable[[], AbstractAsyncContextManager[Toolbox]]


@dataclass
class Attempt:
    """One try, as the history shows it."""

    number: int
    started_at: str
    duration_ms: int = 0
    http_status: int | None = None
    error: str | None = None
    #: Seconds waited after this attempt before the next one (``None``: there was no next one).
    wait_seconds: float | None = None
    retry_after: float | None = None

    def to_data(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "http_status": self.http_status,
            "error": self.error,
            "wait_seconds": self.wait_seconds,
            "retry_after": self.retry_after,
        }


@dataclass
class Outcome:
    """What the request came to: an answer, or the error of the last attempt."""

    completion: Completion | None = None
    error: str | None = None
    http_status: int | None = None
    attempts: list[Attempt] = field(default_factory=list)
    duration: float = 0.0


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def run_completion(
    endpoint: Endpoint,
    model: str,
    messages: list[dict[str, Any]],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    request_timeout: float = REQUEST_TIMEOUT_DEFAULT,
    total_timeout: float = TOTAL_TIMEOUT_DEFAULT,
    retries: int = RETRIES_DEFAULT,
    complete: Complete = client.complete,
    sleep: Sleep = asyncio.sleep,
    tools: list[dict[str, Any]] | None = None,
    limit: float | None = None,
) -> Outcome:
    """Ask the model once and retry what can pass, within ``total_timeout`` (see the module docstring)."""
    retries = max(0, min(int(retries), RETRIES_MAX))
    named = total_timeout if limit is None else limit  # the node's limit, when this is a later turn
    started = time.monotonic()
    deadline = started + total_timeout
    outcome = Outcome()
    scale = 1.0  # grows after a timeout (see the module docstring)
    for number in range(1, retries + 2):
        left = deadline - time.monotonic()
        if left <= 0:
            outcome.error = f"{outcome.error or 'No answer'}; the time limit of {named:g} s is over"
            break
        attempt = Attempt(number, _now())
        outcome.attempts.append(attempt)
        allowed = min(max(request_timeout, min(request_timeout * scale, ATTEMPT_TIMEOUT_CAP)), left)
        began = time.monotonic()
        error: ProviderError
        more: dict[str, Any] = {"tools": tools} if tools else {}
        try:
            async with asyncio.timeout(allowed):
                completion = await complete(
                    endpoint,
                    model,
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=allowed,
                    **more,
                )
        except TimeoutError:
            error = ProviderError(f"Timeout after {round(allowed, 1):g} s", transient=True)
            scale *= TIMEOUT_GROWTH
        except ProviderError as raised:
            error = raised
        else:
            attempt.duration_ms = round((time.monotonic() - began) * 1000)
            attempt.http_status = completion.status
            outcome.completion, outcome.error, outcome.http_status = (
                completion,
                None,
                completion.status,
            )
            break
        attempt.duration_ms = round((time.monotonic() - began) * 1000)
        attempt.http_status, attempt.error = error.status, error.message
        attempt.retry_after = error.retry_after if error.status == 429 else None
        outcome.error, outcome.http_status = error.message, error.status
        if not error.transient:
            break
        if number > retries:
            if retries:
                outcome.error = f"{error.message} (gave up after {number} attempts)"
            break
        wait = (
            attempt.retry_after if attempt.retry_after is not None else BACKOFF_SECONDS[number - 1]
        )
        if wait >= deadline - time.monotonic():
            outcome.error = (
                f"{error.message}; not tried again: the wait of {wait:g} s does not fit the time "
                f"limit of {named:g} s"
            )
            break
        attempt.wait_seconds = wait
        await sleep(wait)
    outcome.duration = time.monotonic() - started
    return outcome
