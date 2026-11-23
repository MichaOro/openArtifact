"""The agent runtime: one request to a model, with its time limits and retries, and its result.

:func:`run_completion` makes the request (through :mod:`~openartifact.agents.client`) and tries again
after a failure that can pass: a network error, a timeout, HTTP 408, 429 or 5xx. The waits are 3, 10,
30 and 60 seconds; a ``Retry-After`` of a 429 replaces the wait. The time of the whole node always
wins: an attempt gets at most what is left of it, and no wait is started that would not leave time for
another attempt. Waiting is ``asyncio.sleep``, so stopping the run ends it at once.

:func:`run_node` is what the agent node does with it: resolve the inputs from the run, fill the prompts,
call the model and hand the engine a ``NodeResult``. The runtime writes nothing itself: the engine
stores the result, and ``detail`` (the prompts as sent, every attempt) is kept with the step only,
never in the run context.

With tools attached (ADR-040) :func:`run_node` is a loop: each turn is one :func:`run_completion` with the
tools offered; the tools the answer calls are run (``agents/tools.py``) and their results sent back, until
an answer calls none or *Max iterations* requests were made. The node's time limit covers every turn and
every tool call. Without tools it is exactly one request, and no ``tools`` field is sent.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from openartifact.agents import client
from openartifact.agents.client import Completion, Endpoint, ProviderError
from openartifact.agents.render import (
    MappingError,
    RenderError,
    fill,
    input_problems,
    parse_mapping,
    resolve_inputs,
)
from openartifact.agents.schemas import (
    ITERATIONS_DEFAULT,
    REQUEST_TIMEOUT_DEFAULT,
    RETRIES_DEFAULT,
    RETRIES_MAX,
    TOTAL_TIMEOUT_DEFAULT,
)
from openartifact.agents.tools import Toolbox, ToolboxError
from openartifact.engine.context import NODE_OUTPUT_LIMIT_BYTES, RunView
from openartifact.engine.results import NodeResult, failed
from openartifact.models import ProviderKind

#: The wait before the first, second, third and fourth retry.
BACKOFF_SECONDS = (3.0, 10.0, 30.0, 60.0)
assert len(BACKOFF_SECONDS) == RETRIES_MAX

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
    for number in range(1, retries + 2):
        left = deadline - time.monotonic()
        if left <= 0:
            outcome.error = f"{outcome.error or 'No answer'}; the time limit of {named:g} s is over"
            break
        attempt = Attempt(number, _now())
        outcome.attempts.append(attempt)
        allowed = min(request_timeout, left)
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


def endpoint_of(
    provider: Mapping[str, Any], api_key: str | None, allow_private_networks: bool
) -> Endpoint:
    """The endpoint of a frozen provider. OpenRouter's address is fixed and never private; another
    provider reaches a private address only when it and the operator both allow it."""
    if provider.get("kind") == ProviderKind.OPENROUTER:
        return Endpoint(client.OPENROUTER_URL, api_key, False)
    return Endpoint(
        str(provider.get("base_url") or ""),
        api_key,
        bool(provider.get("allow_private")) and allow_private_networks,
    )


def _settings(frozen: Mapping[str, Any]) -> dict[str, Any]:
    settings = frozen.get("settings") or {}
    return {
        "system_prompt_enabled": bool(settings.get("system_prompt_enabled")),
        "temperature": settings.get("temperature"),
        "max_tokens": settings.get("max_tokens"),
        "request_timeout_seconds": settings.get("request_timeout_seconds")
        or REQUEST_TIMEOUT_DEFAULT,
        "total_timeout_seconds": settings.get("total_timeout_seconds") or TOTAL_TIMEOUT_DEFAULT,
        "retries": RETRIES_DEFAULT if settings.get("retries") is None else settings["retries"],
        "max_iterations": settings.get("max_iterations") or ITERATIONS_DEFAULT,
    }


NO_AGENT = "This execution has no agent for the node"


async def run_node(
    node: Mapping[str, Any],
    view: RunView,
    api_key: str | None,
    *,
    allow_private_networks: bool = False,
    complete: Complete = client.complete,
    sleep: Sleep = asyncio.sleep,
    open_tools: OpenTools | None = None,
) -> NodeResult:
    """Run an agent node of a frozen pipeline: ``node["agent"]`` is what the snapshot resolved.
    ``open_tools`` opens the toolbox of the tools frozen with it (none: the agent has no tools)."""
    frozen = node.get("agent")
    if not isinstance(frozen, dict):
        return failed(NO_AGENT)
    identity = {
        "agent_id": frozen.get("agent_id"),
        "agent_version": frozen.get("version"),
    }
    if frozen.get("error"):
        return failed(str(frozen["error"]), data=identity)
    provider, model = frozen["provider"], str(frozen["model"])
    settings = _settings(frozen)
    merged = frozen.get("settings") or {}
    detail: dict[str, Any] = {
        "agent": {"id": frozen["agent_id"], "name": frozen["name"], "version": frozen["version"]},
        "provider": {"id": provider["id"], "name": provider["name"], "kind": provider["kind"]},
        "model": model,
        "overrides": frozen.get("overrides") or {},
        "settings": settings,
        "inputs": [],
        "system_prompt": None,
        "user_prompt": None,
        "attempts": [],
        "turns": [],
    }
    data: dict[str, Any] = {
        **identity,
        "provider": provider["name"],
        "model": model,
        "usage": None,
        "finish_reason": None,
        "attempts": 0,
    }

    def refuse(reason: str) -> NodeResult:
        return failed(reason, data=data, detail=detail)

    try:
        mapping = parse_mapping(str((node.get("config") or {}).get("inputs") or ""))
    except MappingError as error:
        return refuse(f"Input mapping: {error}")
    states = resolve_inputs(frozen.get("inputs") or [], mapping, view)
    detail["inputs"] = [s.model_dump() for s in states]
    if problems := input_problems(states):
        return refuse("; ".join(problems))
    messages: list[dict[str, str]] = []
    try:
        system = str(merged.get("system_prompt") or "")
        if settings["system_prompt_enabled"] and system.strip():
            detail["system_prompt"] = fill(system, states)
            messages.append({"role": "system", "content": detail["system_prompt"]})
        detail["user_prompt"] = fill(str(merged.get("user_prompt") or ""), states)
    except RenderError as error:
        return refuse(str(error))
    if not detail["user_prompt"].strip():
        return refuse("The user prompt is empty")
    messages.append({"role": "user", "content": detail["user_prompt"]})
    started = time.monotonic()  # the node's time limit covers opening the tools too
    async with AsyncExitStack() as stack:
        box = Toolbox([])
        if frozen.get("tools") and open_tools is not None:
            limit = float(settings["total_timeout_seconds"])
            try:
                async with asyncio.timeout(limit):
                    box = await stack.enter_async_context(open_tools())
            except ToolboxError as error:
                return refuse(str(error))
            except TimeoutError:
                return refuse(f"The tools could not be opened within the time limit of {limit:g} s")
        return await _loop(
            started,
            endpoint_of(provider, api_key, allow_private_networks),
            model,
            messages,
            settings,
            box,
            data,
            detail,
            complete=complete,
            sleep=sleep,
        )


def _summed(
    total: dict[str, int | None] | None, usage: dict[str, int | None]
) -> dict[str, int | None]:
    """Usage of all turns: a number the provider never sent stays ``None``."""
    if total is None:
        return dict(usage)
    return {
        key: None
        if total.get(key) is None and value is None
        else (total.get(key) or 0) + (value or 0)
        for key, value in usage.items()
    }


async def _loop(
    started: float,
    endpoint: Endpoint,
    model: str,
    messages: list[dict[str, Any]],
    settings: dict[str, Any],
    box: Toolbox,
    data: dict[str, Any],
    detail: dict[str, Any],
    *,
    complete: Complete,
    sleep: Sleep,
) -> NodeResult:
    """The turns of the node: ask, run the tools the answer calls, send their results, ask again."""
    total = float(settings["total_timeout_seconds"])
    iterations = int(settings["max_iterations"]) if box else 1
    schemas = box.schemas() if box else None
    attempts: list[dict[str, Any]] = []

    def finish(result: NodeResult) -> NodeResult:
        detail["attempts"] = attempts
        detail["duration_ms"] = round((time.monotonic() - started) * 1000)
        data["attempts"] = len(attempts)
        data["iterations"] = len(detail["turns"])
        result.duration = time.monotonic() - started
        return result

    def fail(reason: str) -> NodeResult:
        return finish(failed(reason, data=data, detail=detail))

    done: Completion | None = None
    for _number in range(1, iterations + 1):
        left = total - (time.monotonic() - started)
        outcome = await run_completion(
            endpoint,
            model,
            messages,
            temperature=settings["temperature"],
            max_tokens=settings["max_tokens"],
            request_timeout=settings["request_timeout_seconds"],
            total_timeout=max(left, 0.0),
            limit=total,
            retries=settings["retries"],
            complete=complete,
            sleep=sleep,
            tools=schemas,
        )
        turn: dict[str, Any] = {
            "attempts": [a.to_data() for a in outcome.attempts],
            "text": None,
            "finish_reason": None,
            "tool_calls": [],
        }
        detail["turns"].append(turn)
        attempts.extend(turn["attempts"])
        if outcome.completion is None:
            data["status"] = outcome.http_status
            return fail(outcome.error or "The request failed")
        done = outcome.completion
        turn["text"], turn["finish_reason"] = done.text, done.finish_reason
        data["usage"] = detail["usage"] = _summed(data["usage"], done.usage())
        data["finish_reason"] = detail["finish_reason"] = done.finish_reason
        if not done.tool_calls:
            break
        if len(detail["turns"]) >= iterations:
            return fail(f"Stopped after {iterations} iterations without a final answer")
        messages.append(
            {
                "role": "assistant",
                "content": done.text or None,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": c.arguments},
                    }
                    for c in done.tool_calls
                ],
            }
        )
        for call in done.tool_calls:
            left = total - (time.monotonic() - started)
            try:
                async with asyncio.timeout(max(left, 0.0)):
                    record = await box.call(call.id, call.name, call.arguments)
            except TimeoutError:
                return fail(
                    f"The tool {call.name} did not finish within the time limit of {total:g} s"
                )
            turn["tool_calls"].append(record.to_data())
            messages.append({"role": "tool", "tool_call_id": call.id, "content": record.result})
    assert done is not None
    if not done.text.strip():
        return fail(
            "The model returned no text"
            + (f" (finish reason: {done.finish_reason})" if done.finish_reason else "")
        )
    notes = []
    if done.finish_reason == "length":
        notes.append("the model stopped at its token limit, the answer may be incomplete")
    if len(done.text.encode("utf-8")) > NODE_OUTPUT_LIMIT_BYTES:
        notes.append(
            f"the answer is longer than the {NODE_OUTPUT_LIMIT_BYTES // 1024} KiB the run context "
            "keeps: later nodes read its beginning, the step keeps all of it"
        )
    return finish(
        NodeResult(
            "pass",
            output=done.text,
            reason=("Note: " + "; ".join(notes)) if notes else None,
            data=data,
            detail=detail,
        )
    )
