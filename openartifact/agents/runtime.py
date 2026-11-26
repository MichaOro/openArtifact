"""The agent runtime: what an agent node does, from the inputs of the run to the ``NodeResult``.

:func:`run_node` resolves the inputs from the run, fills the prompts, opens the tools and hands everything to the engine: the single
request with its time limits and retries (``agents/completion.py``) and the turn loop around it when tools are attached
(``agents/loop.py``: limits that end in a final answer, a conversation that does not grow without end, a note on calls that repeat,
events while it runs). The runtime writes nothing itself: the engine stores the result, and ``detail`` (the prompts as sent, every
attempt, every turn) is kept with the step only, never in the run context.

Without tools it is exactly one request, and no ``tools`` field is sent.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from contextlib import AsyncExitStack
from typing import Any

from openartifact.agents import client
from openartifact.agents.artifact_inputs import ArtifactInputError, artifact_values
from openartifact.agents.client import UNENCRYPTED_REFUSED, Endpoint
from openartifact.agents.completion import (  # noqa: F401 (the requests are part of the runtime's interface)
    BACKOFF_SECONDS,
    Attempt,
    Complete,
    OpenTools,
    Outcome,
    Sleep,
    run_completion,
)
from openartifact.agents.loop import Signal, run_turns, tools_used  # noqa: F401
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
    TOTAL_TIMEOUT_DEFAULT,
)
from openartifact.agents.tools import Toolbox, ToolboxError
from openartifact.engine.artifact_runner import CommentsGateway
from openartifact.engine.context import RunView
from openartifact.engine.results import NodeResult, failed
from openartifact.models import ProviderKind

#: Told while a node runs what happens in it (``signal(event, data)``: ``tool_call`` and ``turn``, see ``agents/loop.py``); the engine
#: hands the events on to the event bus, the runtime knows nothing of the bus.
AgentSignal = Signal


def endpoint_of(provider: Mapping[str, Any], api_key: str | None) -> Endpoint:
    """The endpoint of a frozen provider. OpenRouter's address is fixed and never private; the address of
    another provider is just an address, a local one included."""
    if provider.get("kind") == ProviderKind.OPENROUTER:
        return Endpoint(client.OPENROUTER_URL, api_key, False)
    return Endpoint(str(provider.get("base_url") or ""), api_key, True)


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
        "token_budget": settings.get("token_budget"),
        "tool_result_chars": settings.get("tool_result_chars"),
    }


NO_AGENT = "This execution has no agent for the node"


async def run_node(
    node: Mapping[str, Any],
    view: RunView,
    api_key: str | None,
    *,
    complete: Complete = client.complete,
    sleep: Sleep = asyncio.sleep,
    open_tools: OpenTools | None = None,
    comments: CommentsGateway | None = None,
    on_event: AgentSignal | None = None,
) -> NodeResult:
    """Run an agent node of a frozen pipeline: ``node["agent"]`` is what the snapshot resolved.
    ``open_tools`` opens the toolbox of the tools frozen with it (none: the agent has no tools); ``on_event`` is told what happens
    while the node runs (see :data:`AgentSignal`)."""
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
    specs = frozen.get("inputs") or []
    try:
        from_artifact = await artifact_values(specs, view, comments)
    except ArtifactInputError as error:
        return refuse(str(error))
    states = resolve_inputs(specs, mapping, view, artifact=from_artifact)
    detail["inputs"] = [s.model_dump() for s in states]
    if problems := input_problems(states):
        return refuse("; ".join(problems))
    messages: list[dict[str, str]] = []
    try:
        system = str(merged.get("system_prompt") or "")
        if settings["system_prompt_enabled"] and system.strip():
            detail["system_prompt"] = fill(system, states, view=view)
            messages.append({"role": "system", "content": detail["system_prompt"]})
        detail["user_prompt"] = fill(str(merged.get("user_prompt") or ""), states, view=view)
    except RenderError as error:
        return refuse(str(error))
    if not detail["user_prompt"].strip():
        return refuse("The user prompt is empty")
    messages.append({"role": "user", "content": detail["user_prompt"]})
    if (
        provider.get("kind") != ProviderKind.OPENROUTER
        and str(provider.get("base_url") or "").startswith("http://")
        and not provider.get("allow_http")
    ):
        return refuse(UNENCRYPTED_REFUSED)
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
        return await run_turns(
            started,
            endpoint_of(provider, api_key),
            model,
            messages,
            settings,
            box,
            data,
            detail,
            complete=complete,
            sleep=sleep,
            signal=(
                lambda event, payload: on_event(event, {"agent_node_id": node.get("id"), **payload})
            )
            if on_event
            else None,
        )
