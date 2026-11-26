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
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from openartifact.agents import tools as agent_tools
from openartifact.agents.runtime import run_node as run_agent_node
from openartifact.comments.schemas import Author
from openartifact.config import Settings
from openartifact.credentials.refs import (
    SecretReferenceError,
    mask_data,
    mask_text,
    names_in,
    parse_name_lines,
)
from openartifact.credentials.store import SecretResolveError
from openartifact.engine.artifact_runner import CommentsGateway, run_artifact
from openartifact.engine.branching import evaluate_if, evaluate_switch
from openartifact.engine.code_runner import CodeLimits, run_code
from openartifact.engine.context import RunView
from openartifact.engine.context_builder import CardsGateway, run_context
from openartifact.engine.fields import run_set
from openartifact.engine.github_runner import run_github
from openartifact.engine.http_runner import run_http
from openartifact.engine.postgres_runner import run_postgres
from openartifact.engine.results import NodeResult, failed
from openartifact.engine.sqlite_runner import APP_SOURCE, DataSource, application_source, run_sqlite
from openartifact.logging_config import masked_in_logs
from openartifact.models import NodeKind

logger = logging.getLogger(__name__)

OPEN_MODE_CODE_REASON = (
    "Execute Command nodes need OPENARTIFACT_API_TOKEN: the application is open without it"
)
#: The reason of an Execute Command node (and the Execute Command Tool of an agent) while the instance has them switched off.
CODE_DISABLED_REASON = (
    "Execute Command nodes are switched off on this instance: set OPENARTIFACT_CODE_NODES_ENABLED=true "
    "in the environment and restart to switch them on"
)

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
    #: The comments of artifacts, for the Artifact node (ADR-055); ``None``: the node fails.
    comments: CommentsGateway | None = None
    #: The parent, children, siblings and earlier executions of a card, for the Build Context node (ADR-078); ``None``: those sources fail.
    cards: CardsGateway | None = None
    #: The settings of a credential that are no secret, by its name (the address of a GitHub server); ``None``: none.
    credential_settings: Callable[[str], Awaitable[dict[str, str]]] | None = None
    #: The SQLite databases a SQLite node may read, by name (``engine/sqlite_runner.py``, ADR-068): the application's own
    #: (``app``, through the ``v_guard_*`` views); an extension adds more.
    data_sources: Mapping[str, DataSource] = field(default_factory=dict)
    #: Told what a running node does that others may want to see (``agent.tool_call``: the event type and its data); the
    #: application hands it to the event bus. ``None``: nobody listens.
    publish: Callable[[str, dict[str, Any]], object] | None = None

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        secrets: SecretResolver | None = None,
        comments: CommentsGateway | None = None,
        credential_settings: Callable[[str], Awaitable[dict[str, str]]] | None = None,
        publish: Callable[[str, dict[str, Any]], object] | None = None,
        cards: CardsGateway | None = None,
    ) -> Limits:
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
            comments=comments,
            cards=cards,
            credential_settings=credential_settings,
            data_sources={
                APP_SOURCE: application_source(settings.data_dir / settings.database_filename)
            },
            publish=publish,
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


def node_output_limit(config: dict[str, Any], instance_limit: int) -> int:
    """What an Execute Command node keeps of its output: its own ``output_limit_bytes`` when it has one, never more than the
    limit of the instance (``OPENARTIFACT_CODE_OUTPUT_LIMIT_BYTES``), which stays the ceiling (ADR-075)."""
    own = config.get("output_limit_bytes")
    if isinstance(own, int) and not isinstance(own, bool) and own > 0:
        return min(own, instance_limit)
    return instance_limit


async def _code(node: dict[str, Any], limits: Limits, view: RunView | None = None) -> NodeResult:
    if not limits.code_nodes_enabled:
        return failed(CODE_DISABLED_REASON)
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
            node_output_limit(config, limits.code_output_limit_bytes),
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


async def _postgres(
    node: dict[str, Any], limits: Limits, view: RunView | None = None
) -> NodeResult:
    """One SQL statement on the database of the secret's URL (``engine/postgres_runner.py``, ADR-041). The
    URL is resolved here, like every secret, so the result is masked for it and the snapshot only holds
    the secret's name."""
    config = node["config"]
    secret = str(config.get("secret") or "").strip()
    if not secret:
        return failed("No secret with the connection URL is set")
    try:
        names = parse_name_lines(secret)
    except SecretReferenceError as error:
        return failed(str(error))

    async def run(values: dict[str, str]) -> NodeResult:
        return await run_postgres(
            config,
            values[secret],
            view=view,
            operator_allows_private=limits.http_allow_private_networks,
        )

    return await _with_secrets(names, limits, run)


async def _sqlite(node: dict[str, Any], limits: Limits, view: RunView | None = None) -> NodeResult:
    """One read-only SQL statement on a data source of the application (``engine/sqlite_runner.py``, ADR-068): only through the
    listed views, never a change."""
    return await run_sqlite(node["config"], limits.data_sources, view=view)


async def _github(node: dict[str, Any], limits: Limits, view: RunView | None = None) -> NodeResult:
    """One call of GitHub's API (``engine/github_runner.py``, ADR-041). The token is the value of the secret the
    node names (none: public data); it is resolved here, like every secret."""
    config = node["config"]
    secret = str(config.get("secret") or "").strip()
    try:
        names = parse_name_lines(secret) if secret else []
    except SecretReferenceError as error:
        return failed(str(error))

    # the address of the GitHub server is kept with the credential, not in the node (a value stored in an older node is not used)
    base = (
        (await limits.credential_settings(secret)).get("base_url", "")
        if secret and limits.credential_settings
        else ""
    )
    config = {**config, "api_url": base}

    async def run(values: dict[str, str]) -> NodeResult:
        return await run_github(
            config,
            token=values.get(secret) if secret else None,
            view=view,
            operator_allows_private=limits.http_allow_private_networks,
            response_limit_bytes=limits.http_response_limit_bytes,
        )

    return await _with_secrets(names, limits, run)


async def _artifact(
    node: dict[str, Any], limits: Limits, view: RunView | None = None
) -> NodeResult:
    """Read or write the comments of the run's own artifact (``engine/artifact_runner.py``, ADR-055); no secret."""
    return await run_artifact(
        node["config"],
        node_name=str(node["name"]),
        view=view or RunView(),
        gateway=limits.comments,
        author_factory=Author,
    )


async def _context(node: dict[str, Any], limits: Limits, view: RunView | None = None) -> NodeResult:
    """Build the package of the node's sources within its size limit (``engine/context_builder.py``, ADR-078); no secret."""
    return await run_context(
        node["config"], view=view or RunView(), cards=limits.cards, comments=limits.comments
    )


async def _timer(node: dict[str, Any], limits: Limits, view: RunView | None = None) -> NodeResult:
    started = time.monotonic()
    await asyncio.sleep(node["seconds"] or 0)
    return NodeResult("pass", duration=time.monotonic() - started)


async def _if(node: dict[str, Any], limits: Limits, view: RunView | None = None) -> NodeResult:
    return evaluate_if(node["config"], view or RunView())


async def _switch(node: dict[str, Any], limits: Limits, view: RunView | None = None) -> NodeResult:
    return evaluate_switch(node["config"], view or RunView())


async def _set(node: dict[str, Any], limits: Limits, view: RunView | None = None) -> NodeResult:
    """Edit Fields: variables from text and references (``engine/fields.py``); no secret is involved."""
    return run_set(node["config"], view or RunView())


def _agent_events(limits: Limits, view: RunView) -> Callable[[str, dict[str, Any]], None] | None:
    """What an agent node tells the application while it runs, with the artifact and the execution: ``agent.tool_call`` (a call of a
    tool node started or ended: the flow page shows the node working) and ``agent.turn`` (a request started or ended, with the start
    of the answer and the tokens: the flow page shows the rounds). Names, counts and states; never arguments or results."""
    if limits.publish is None or view.execution_id is None:
        return None
    publish = limits.publish

    def tell(event: str, data: dict[str, Any]) -> None:
        publish(
            f"agent.{event}", {"task_id": view.task_id, "execution_id": view.execution_id, **data}
        )

    return tell


async def _agent(node: dict[str, Any], limits: Limits, view: RunView | None = None) -> NodeResult:
    """The node's agent asks its model, with the attached tools (see ``agents/runtime.py``). The key of
    the provider and the secrets of the tools are resolved here, like every secret, so the answer, the
    reason, the data and the detail (prompts, tool calls) are masked for them and the snapshot only ever
    holds their names."""
    frozen = node.get("agent")
    usable = isinstance(frozen, dict) and not frozen.get(
        "error"
    )  # else it fails before any request
    provider = frozen.get("provider") if usable and isinstance(frozen, dict) else None
    name = provider.get("secret_name") if isinstance(provider, dict) else None
    tools = (frozen.get("tools") or []) if usable and isinstance(frozen, dict) else []
    try:
        names = ([name] if name else []) + agent_tools.secret_names(tools)
    except SecretReferenceError as error:
        return failed(str(error))
    run_view = view or RunView()

    async def run(values: dict[str, str]) -> NodeResult:
        context = agent_tools.ToolContext(
            values, limits.llm_allow_private_networks, limits=limits, view=run_view
        )
        return await run_agent_node(
            node,
            run_view,
            values.get(name) if name else None,
            open_tools=lambda: agent_tools.open_toolbox(tools, context),
            comments=limits.comments,
            on_event=_agent_events(limits, run_view),
        )

    return await _with_secrets(list(dict.fromkeys(names)), limits, run)


register_executor(NodeKind.CODE, _code)
register_executor(NodeKind.HTTP, _http)
register_executor(NodeKind.TIMER, _timer, by_outcome=False)
register_executor(NodeKind.IF, _if, by_outcome=False)
register_executor(NodeKind.SWITCH, _switch, by_outcome=False)
register_executor(NodeKind.AGENT, _agent)
register_executor(NodeKind.SET, _set)
register_executor(NodeKind.POSTGRES, _postgres)
register_executor(NodeKind.SQLITE, _sqlite)
register_executor(NodeKind.GITHUB, _github)
register_executor(NodeKind.ARTIFACT, _artifact)
register_executor(NodeKind.CONTEXT, _context)
