"""The executors of execution nodes: what the engine does when a run reaches a node of an action definition.

An executor is an async function ``(node, limits) -> NodeResult`` registered for a kind of node
(:func:`register_executor`), the same way a node type is registered. The engine looks the kind up,
runs it, stores the result (a step of the run, see ``RunNodeResult``) and leaves the node by the port
that matches the outcome: *On Pass* or *On Fail* for kinds with ``by_outcome``, *Next* for the rest.
Triggers and outputs have no executor: the engine handles them itself (start and end of a definition).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from openartifact.config import Settings
from openartifact.engine.code_runner import CodeLimits, run_code
from openartifact.engine.http_runner import run_http
from openartifact.engine.results import NodeResult, failed
from openartifact.logging_config import masked_in_logs
from openartifact.models import NodeKind
from openartifact.secret_refs import (
    SecretReferenceError,
    mask_data,
    mask_text,
    names_in,
    parse_name_lines,
)
from openartifact.secret_store import SecretResolveError

logger = logging.getLogger(__name__)

OPEN_MODE_CODE_REASON = "Code nodes need OPENARTIFACT_API_TOKEN: the application is open without it"

#: Gives the values of secrets by name; raises :class:`SecretResolveError`.
SecretResolver = Callable[[Sequence[str]], Awaitable[dict[str, str]]]


@dataclass(frozen=True)
class Limits:
    """The settings the executors depend on (taken from :class:`~openartifact.config.Settings`)."""

    code_nodes_enabled: bool = True
    code_output_limit_bytes: int = 65536
    http_response_limit_bytes: int = 1024 * 1024
    http_allow_private_networks: bool = False
    code: CodeLimits = field(default_factory=CodeLimits)
    #: Where a node's secrets come from (the credential store); ``None``: no secret can be used.
    secrets: SecretResolver | None = None
    #: Open mode (no API token) without the explicit opt-in: Code nodes must not run, because anyone who
    #: reaches the port could write one. ``from_settings`` decides; the default keeps unit tests simple.
    code_blocked_in_open_mode: bool = False

    @classmethod
    def from_settings(cls, settings: Settings, secrets: SecretResolver | None = None) -> Limits:
        return cls(
            settings.code_nodes_enabled,
            settings.code_output_limit_bytes,
            settings.http_response_limit_bytes,
            settings.http_allow_private_networks,
            CodeLimits(
                settings.code_memory_limit_mb,
                settings.code_process_limit,
                settings.code_file_size_limit_mb,
                settings.code_open_files_limit,
            ),
            secrets,
            code_blocked_in_open_mode=not settings.api_token
            and not settings.code_nodes_without_token,
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


async def _resolve(names: list[str], limits: Limits) -> dict[str, str]:
    """The values of the secrets a node uses (executor-side, so snapshots only ever hold names)."""
    if not names:
        return {}
    if limits.secrets is None:
        raise SecretResolveError("Secrets are not available")
    return await limits.secrets(names)


def _masked(result: NodeResult, values: dict[str, str]) -> NodeResult:
    """The result with every form of every used secret value replaced by ``***``."""
    used = list(values.values())
    if not used:
        return result
    result.output = mask_text(result.output, used)
    if result.reason is not None:
        result.reason = mask_text(result.reason, used)
    if result.data is not None:
        result.data = mask_data(result.data, used)
    return result


async def _with_secrets(
    names: list[str], limits: Limits, run: Callable[[dict[str, str]], Awaitable[NodeResult]]
) -> NodeResult:
    """Run a node with the values of ``names``; whatever it returns or raises is masked."""
    try:
        values = await _resolve(names, limits)
    except SecretResolveError as error:
        return failed(str(error))
    with masked_in_logs(values.values()):
        try:
            result = await run(values)
        except Exception as error:  # the text of an exception may hold a URL or an echoed value
            result = failed(f"The node failed ({type(error).__name__})")
        return _masked(result, values)


async def _code(node: dict[str, Any], limits: Limits) -> NodeResult:
    if not limits.code_nodes_enabled:
        return failed("Code nodes are disabled")
    if limits.code_blocked_in_open_mode:
        return failed(OPEN_MODE_CODE_REASON)
    config = node["config"]
    try:
        names = parse_name_lines(str(config.get("secrets") or ""))
    except SecretReferenceError as error:
        return failed(str(error))

    async def run(values: dict[str, str]) -> NodeResult:
        return await run_code(
            config["language"],
            config["code"],
            config["timeout_seconds"],
            limits.code_output_limit_bytes,
            env=values,
            limits=limits.code,
            node_id=str(node.get("id") or ""),
        )

    return await _with_secrets(names, limits, run)


async def _http(node: dict[str, Any], limits: Limits) -> NodeResult:
    config = node["config"]
    try:
        names = names_in(*(str(config.get(k) or "") for k in ("url", "headers", "body")))
    except SecretReferenceError as error:
        return failed(str(error))

    async def run(values: dict[str, str]) -> NodeResult:
        return await run_http(
            config,
            response_limit_bytes=limits.http_response_limit_bytes,
            allow_private_networks=limits.http_allow_private_networks,
            secrets=values,
        )

    return await _with_secrets(names, limits, run)


async def _timer(node: dict[str, Any], limits: Limits) -> NodeResult:
    started = time.monotonic()
    await asyncio.sleep(node["seconds"] or 0)
    return NodeResult("pass", duration=time.monotonic() - started)


register_executor(NodeKind.CODE, _code)
register_executor(NodeKind.HTTP, _http)
register_executor(NodeKind.TIMER, _timer, by_outcome=False)
