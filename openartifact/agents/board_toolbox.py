"""The tools of an OpenArtifact MCP Tool node (ADR-079): the board tools of ``api/board_tools.py``, offered to an agent in this process.

The node has no address and no token: its tools are the very functions the MCP server registers (one set, so the two cannot drift),
called here with the arguments of the model. The schema the model sees is the one the MCP server derives from the same function, and the
arguments are validated the same way, so a call here and a call over ``/mcp`` answer the same.

*Allow writes* (off by default) holds back the tools that change something (:data:`~openartifact.agents.board_tool_names.WRITE_TOOLS`);
*Tools to include* narrows the set further (all, selected, all except). A refusal of the application (a card that is being processed,
an archived card) comes back as the tool's error text, like any tool's failure.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from mcp.server.mcpserver.tools import Tool as FunctionTool

from openartifact.agents.board_tool_names import BOARD_TOOLS, WRITE_TOOLS
from openartifact.agents.tool_config import ToolConfigError, parse_tool_names
from openartifact.agents.tools import Run, Tool

_PREFIX = "Error executing tool "


def _included(config: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """The tools the node's *Tools to include* names (in the order of the tool list) and the names that are no tool."""
    mode = str(config.get("tools_mode") or "all")
    if mode == "all":
        return list(BOARD_TOOLS), []
    try:
        listed = parse_tool_names(str(config.get("tool_names") or ""))
    except ToolConfigError:
        listed = []
    unknown = [n for n in listed if n not in BOARD_TOOLS]
    if mode == "selected":
        return [n for n in BOARD_TOOLS if n in listed], unknown
    return [n for n in BOARD_TOOLS if n not in listed], unknown


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def _reason(error: Exception) -> str:
    """What the SDK wraps (``Error executing tool NAME: reason``) as the plain reason."""
    text = str(error)
    if text.startswith(_PREFIX) and ": " in text:
        return text[len(_PREFIX) :].split(": ", 1)[1]
    return text


def _runner(tool: FunctionTool) -> Run:
    async def run(arguments: dict[str, Any]) -> str:
        try:
            result = await tool.run(arguments, context=None)  # type: ignore[arg-type]
        except (ToolError, UnexpectedToolError) as error:
            return f"Error: {_reason(error)}"
        return _text(result)

    return run


def board_tools(
    frozen: Mapping[str, Any], board: object, *, prefix: str, label: str
) -> tuple[list[Tool], list[str]]:
    """The tools of a frozen OpenArtifact MCP Tool node and what the run says about those it could not offer as asked."""
    config = frozen.get("config") or {}
    names, unknown = _included(config)
    allow_write = bool(config.get("allow_write"))
    offered = [n for n in names if allow_write or n not in WRITE_TOOLS]
    held_back = [n for n in names if n not in offered]
    notes: list[str] = []
    if unknown:
        notes.append(f"Tool {label}: no tool named {', '.join(unknown)}")
    if held_back:
        notes.append(
            f"Tool {label}: {', '.join(held_back)} not offered (it changes something and Allow writes is off)"
        )
    tools: list[Tool] = []
    for name in offered:
        function = FunctionTool.from_function(getattr(board, name), name=name)
        tools.append(
            Tool(
                name,
                function.description,
                function.parameters,
                _runner(function),
                writes=name in WRITE_TOOLS,
                prefix=prefix,
                node_id=str(frozen.get("node_id") or ""),
                node_name=label,
            )
        )
    return tools, notes
