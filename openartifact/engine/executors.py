"""The executors of execution nodes: what the engine does when a run reaches a node of an action definition.

An executor is an async function ``(node, limits) -> NodeResult`` registered for a kind of node
(:func:`register_executor`), the same way a node type is registered. The engine looks the kind up,
runs it, stores the result (a step of the run, see ``RunNodeResult``) and leaves the node by the port
that matches the outcome: *On Pass* or *On Fail* for kinds with ``by_outcome``, *Next* for the rest, or
by the port the result names itself (``NodeResult.port``: the If and Switch nodes choose their branch).
Triggers and outputs have no executor: the engine handles them itself (start and end of a definition).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from openartifact.agents.runtime import run_node as run_agent_node
from openartifact.config import Settings
from openartifact.credentials.refs import (
    SecretReferenceError,
    mask_data,
    mask_text,
    names_in,
    parse_name_lines,
)
from openartifact.credentials.store import SecretResolveError
from openartifact.engine.branching import evaluate_if, evaluate_switch
from openartifact.engine.code_runner import CodeLimits, run_code
from openartifact.engine.context import RunView
from openartifact.engine.http_runner import run_http
from openartifact.engine.results import NodeResult, failed
from openartifact.logging_config import masked_in_logs
from openartifact.models import NodeKind

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
    #: The operator's half of the permission for an LLM provider on a private network (the other half
    #: is the provider's own ``allow_private``). Independent of ``http_allow_private_networks``.
    llm_allow_private_networks: bool = False

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
            llm_allow_private_networks=settings.llm_allow_private_networks,
        )


class Executor(Protocol):
    """``(node, limits, view)``: ``view`` is what the node may read of its run (the context)."""

    def __call__(
        self, node: dict[str, Any], limits: Limits, view: RunView | None = None
    ) -> Awaitable[NodeResult]: ...


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
    if result.variables is not None:
        result.variables = mask_data(result.variables, used)
    if result.detail is not None:
        result.detail = mask_data(result.detail, used)
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


async def _code(node: dict[str, Any], limits: Limits, view: RunView | None = None) -> NodeResult:
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
            context_json=(view or RunView()).dumps(),
        )

    return _note_variables(await _with_secrets(names, limits, run), config)


def _note_variables(result: NodeResult, config: dict[str, Any]) -> NodeResult:
    """A passing node's reason says where its variables differ from ``sets_variables`` (a hint only)."""
    declared = {line.strip() for line in str(config.get("sets_variables") or "").splitlines()}
    declared.discard("")
    if result.outcome != "pass" or not declared:
        return result
    notes = [f"undeclared variable '{n}'" for n in sorted(set(result.variables or {}) - declared)]
    notes += [
        f"declared variable '{n}' was not set"
        for n in sorted(declared - set(result.variables or {}))
    ]
    if notes:
        result.reason = "; ".join(notes)
        result.__post_init__()
    return result


async def _http(node: dict[str, Any], limits: Limits, view: RunView | None = None) -> NodeResult:
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
            view=view,
        )

    return await _with_secrets(names, limits, run)


async def _timer(node: dict[str, Any], limits: Limits, view: RunView | None = None) -> NodeResult:
    started = time.monotonic()
    await asyncio.sleep(node["seconds"] or 0)
    return NodeResult("pass", duration=time.monotonic() - started)


async def _if(node: dict[str, Any], limits: Limits, view: RunView | None = None) -> NodeResult:
    return evaluate_if(node["config"], view or RunView())


async def _switch(node: dict[str, Any], limits: Limits, view: RunView | None = None) -> NodeResult:
    return evaluate_switch(node["config"], view or RunView())


async def _agent(node: dict[str, Any], limits: Limits, view: RunView | None = None) -> NodeResult:
    """One request to the model of the node's agent (see ``agents/runtime.py``). The key of the
    provider is resolved here, like every secret, so the answer, the reason, the data and the detail
    (the prompts) are masked for it and the snapshot only ever holds its name."""
    frozen = node.get("agent")
    usable = isinstance(frozen, dict) and not frozen.get(
        "error"
    )  # else it fails before any request
    provider = frozen.get("provider") if usable and isinstance(frozen, dict) else None
    name = provider.get("secret_name") if isinstance(provider, dict) else None

    async def run(values: dict[str, str]) -> NodeResult:
        return await run_agent_node(
            node,
            view or RunView(),
            values.get(name) if name else None,
            allow_private_networks=limits.llm_allow_private_networks,
        )

    return await _with_secrets([name] if name else [], limits, run)


register_executor(NodeKind.CODE, _code)
register_executor(NodeKind.HTTP, _http)
register_executor(NodeKind.TIMER, _timer, by_outcome=False)
register_executor(NodeKind.IF, _if, by_outcome=False)
register_executor(NodeKind.SWITCH, _switch, by_outcome=False)
register_executor(NodeKind.AGENT, _agent)
