"""The executors of execution nodes: what the engine does when a run reaches a node of an action definition.

An executor is an async function ``(node, limits) -> NodeResult`` registered for a kind of node
(:func:`register_executor`), the same way a node type is registered. The engine looks the kind up,
runs it, stores the result (a step of the run, see ``RunNodeResult``) and leaves the node by the port
that matches the outcome: *On Pass* or *On Fail* for kinds with ``by_outcome``, *Next* for the rest.
Triggers and outputs have no executor: the engine handles them itself (start and end of a definition).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from openartifact.config import Settings
from openartifact.engine.code_runner import run_code
from openartifact.engine.http_runner import run_http
from openartifact.engine.results import NodeResult, failed
from openartifact.models import NodeKind


@dataclass(frozen=True)
class Limits:
    """The settings the executors depend on (taken from :class:`~openartifact.config.Settings`)."""

    code_nodes_enabled: bool = True
    code_output_limit_bytes: int = 65536
    http_response_limit_bytes: int = 1024 * 1024
    http_allow_private_networks: bool = False

    @classmethod
    def from_settings(cls, settings: Settings) -> Limits:
        return cls(
            settings.code_nodes_enabled,
            settings.code_output_limit_bytes,
            settings.http_response_limit_bytes,
            settings.http_allow_private_networks,
        )


Executor = Callable[[dict[str, Any], Limits], Awaitable[NodeResult]]


@dataclass(frozen=True)
class Registered:
    run: Executor
    #: Leave by On Pass / On Fail (True) or by the single *Next* output (False).
    by_outcome: bool = True


EXECUTORS: dict[NodeKind, Registered] = {}


def register_executor(kind: NodeKind, run: Executor, *, by_outcome: bool = True) -> None:
    """Make the engine able to run nodes of ``kind``."""
    EXECUTORS[kind] = Registered(run, by_outcome)


async def _code(node: dict[str, Any], limits: Limits) -> NodeResult:
    if not limits.code_nodes_enabled:
        return failed("Code nodes are disabled")
    config = node["config"]
    return await run_code(
        config["language"],
        config["code"],
        config["timeout_seconds"],
        limits.code_output_limit_bytes,
    )


async def _http(node: dict[str, Any], limits: Limits) -> NodeResult:
    return await run_http(
        node["config"],
        response_limit_bytes=limits.http_response_limit_bytes,
        allow_private_networks=limits.http_allow_private_networks,
    )


async def _timer(node: dict[str, Any], limits: Limits) -> NodeResult:
    started = time.monotonic()
    await asyncio.sleep(node["seconds"] or 0)
    return NodeResult("pass", duration=time.monotonic() - started)


register_executor(NodeKind.CODE, _code)
register_executor(NodeKind.HTTP, _http)
register_executor(NodeKind.TIMER, _timer, by_outcome=False)
