"""The tools of an agent node for one run (ADR-040): what the model is told, and calling them.

:class:`Toolbox` holds the tools as the model sees them: OpenAI function tools with names that are valid
and unique (a name two tools share gets the tool node's name in front). :meth:`Toolbox.call` never
raises: an unknown tool, arguments that are not a JSON object, or a tool that fails become an
``Error: ...`` text the model reads (as n8n does). Results are cut to :data:`TOOL_RESULT_LIMIT_BYTES`.

:func:`open_toolbox` builds the toolbox from the tools frozen into the snapshot: it connects to the MCP
servers (their tools listed and filtered) and builds the HTTP Request and Code tools; it raises
:class:`ToolboxError` when a tool cannot be used, so the node fails before its first request.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from openartifact.agents.mcp_client import McpToolError, open_mcp
from openartifact.models import NodeKind

TOOL_RESULT_LIMIT_BYTES = 16 * 1024
CUT_NOTE = "\n[cut: the result is longer than 16 KiB]"
_INVALID = re.compile(r"[^A-Za-z0-9_-]+")

Run = Callable[[dict[str, Any]], Awaitable[str]]


class ToolboxError(Exception):
    """A tool of the node cannot be used (the message names the tool node)."""


@dataclass
class Tool:
    """One tool for the model. ``name`` is the tool's own name; ``prefix`` (the tool node's name for
    the model) goes in front only when another tool has the same name."""

    name: str
    description: str
    parameters: dict[str, Any]
    run: Run
    prefix: str = ""
    #: The name the model calls it by, set by the toolbox.
    called: str = field(default="", init=False)


@dataclass
class ToolCallRecord:
    """One tool call as the history keeps it."""

    id: str
    tool: str
    arguments: str
    result: str
    error: bool
    duration_ms: int

    def to_data(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "arguments": cut(self.arguments),
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


def cut(text: str) -> str:
    """``text`` within :data:`TOOL_RESULT_LIMIT_BYTES` (UTF-8), with a note when it was longer."""
    raw = text.encode("utf-8")
    if len(raw) <= TOOL_RESULT_LIMIT_BYTES:
        return text
    return raw[: TOOL_RESULT_LIMIT_BYTES - len(CUT_NOTE)].decode("utf-8", "ignore") + CUT_NOTE


def _valid(name: str) -> str:
    return _INVALID.sub("_", name).strip("_")[:64] or "tool"


def _parameters(schema: Mapping[str, Any]) -> dict[str, Any]:
    """A JSON schema of an object, as the function tools of OpenAI want it."""
    found = dict(schema)
    if found.get("type") != "object":
        return {"type": "object", "properties": {}}
    found.setdefault("properties", {})
    return found


class Toolbox:
    """The tools of one agent node run, by the names the model calls them."""

    def __init__(self, tools: Sequence[Tool]) -> None:
        own = [_valid(t.name) for t in tools]
        shared = {n for n in own if own.count(n) > 1}
        self._tools: dict[str, Tool] = {}
        for tool, name in zip(tools, own, strict=True):
            if name in shared and tool.prefix:
                name = _valid(f"{tool.prefix}_{name}")
            base, number = name, 2
            while name in self._tools:
                name = f"{base[:60]}_{number}"
                number += 1
            tool.called = name
            self._tools[name] = tool

    def __bool__(self) -> bool:
        return bool(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.description,
                    "parameters": _parameters(tool.parameters),
                },
            }
            for name, tool in self._tools.items()
        ]

    async def call(self, call_id: str, name: str, arguments: str) -> ToolCallRecord:
        """Run one call of the model; the outcome is always a text for the model."""
        began = time.monotonic()

        def record(result: str, error: bool) -> ToolCallRecord:
            duration = round((time.monotonic() - began) * 1000)
            return ToolCallRecord(call_id, name, arguments, cut(result), error, duration)

        tool = self._tools.get(name)
        if tool is None:
            return record(f"Error: there is no tool named {name}", True)
        try:
            parsed = json.loads(arguments) if arguments.strip() else {}
        except ValueError:
            return record("Error: the arguments are not valid JSON", True)
        if not isinstance(parsed, dict):
            return record("Error: the arguments are not a JSON object", True)
        try:
            result = await tool.run(parsed)
        except Exception as error:  # a tool's failure is the model's to handle
            return record(f"Error: the tool failed ({type(error).__name__}: {error})", True)
        return record(result, result.startswith("Error:"))


@dataclass(frozen=True)
class ToolContext:
    """What tools need from the run: the resolved secrets and the operator's permissions."""

    secrets: Mapping[str, str]
    allow_private_networks: bool
    limits: Any = None
    view: Any = None


#: Builders of tools that run here (HTTP Request Tool, Code Tool), by kind: see ``agents/local_tools.py``.
LocalBuilder = Callable[[Mapping[str, Any], ToolContext], Tool]
LOCAL_TOOLS: dict[str, LocalBuilder] = {}


def secret_names(tools: Sequence[Mapping[str, Any]]) -> list[str]:
    """The secrets the frozen tools use (resolved and masked by the engine like every secret)."""
    from openartifact.agents import local_tools

    names: list[str] = []
    for tool in tools:
        config = tool.get("config") or {}
        if tool.get("kind") == NodeKind.MCP_TOOL:
            found = [str(config.get("secret") or "").strip()]
        else:
            found = local_tools.secret_names(str(tool.get("kind")), config)
        names.extend(n for n in found if n and n not in names)
    return names


@asynccontextmanager
async def open_toolbox(
    tools: Sequence[Mapping[str, Any]], context: ToolContext
) -> AsyncIterator[Toolbox]:
    """The toolbox of the frozen ``tools``, with the MCP servers connected for the time of the block."""
    from openartifact.agents import local_tools  # registers the local builders

    del local_tools
    async with AsyncExitStack() as stack:
        built: list[Tool] = []
        for frozen in tools:
            config = frozen.get("config") or {}
            label, prefix = str(frozen.get("name") or "tool"), str(frozen.get("tool_name") or "")
            kind = str(frozen.get("kind"))
            if kind == NodeKind.MCP_TOOL:
                secret = str(config.get("secret") or "").strip()
                try:
                    server = await stack.enter_async_context(
                        open_mcp(
                            config,
                            context.secrets.get(secret) if secret else None,
                            allow_private=bool(config.get("allow_private"))
                            and context.allow_private_networks,
                        )
                    )
                except McpToolError as error:
                    raise ToolboxError(f"Tool {label}: {error.message}") from None
                for offered in server.tools:
                    built.append(
                        Tool(
                            offered.name,
                            offered.description,
                            offered.input_schema,
                            _mcp_call(server.call, offered.name),
                            prefix=prefix,
                        )
                    )
                continue
            builder = LOCAL_TOOLS.get(kind)
            if builder is None:
                raise ToolboxError(f"Tool {label}: a {kind} cannot be used by an agent")
            try:
                built.append(builder(frozen, context))
            except ValueError as error:
                raise ToolboxError(f"Tool {label}: {error}") from None
        yield Toolbox(built)


def _mcp_call(call: Callable[[str, Mapping[str, Any]], Awaitable[str]], name: str) -> Run:
    async def run(arguments: dict[str, Any]) -> str:
        return await call(name, arguments)

    return run
