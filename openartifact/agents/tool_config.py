"""The settings of tool nodes as rules (ADR-040): names for the model, declared parameters, MCP tool lists.

Pure functions, used when a tool node is saved (``graph/node_types.py``) and when a run builds the tools for the
model (``agents/tools.py``).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

#: What a model accepts as a function name (OpenAI: letters, digits, ``_`` and ``-``, at most 64).
TOOL_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
PARAMETER_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")
MCP_TOOL_NAME = re.compile(r"[A-Za-z0-9_.\-/]{1,128}")
MAX_PARAMETERS = 30
MAX_TOOL_NAMES = 200


class ToolConfigError(ValueError):
    """A setting of a tool node is not valid (the message names the line or the rule)."""


def check_tool_name(name: str) -> None:
    if len(name) > 64:
        raise ToolConfigError("The tool name is too long (at most 64 characters)")
    if name and not TOOL_NAME.fullmatch(name):
        raise ToolConfigError("A tool name has letters, digits, _ and - only")


def default_tool_name(node_name: str) -> str:
    """The name the model sees when the node sets none: its own name, made a valid tool name."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", node_name.strip()).strip("_")[:64] or "tool"


def parse_parameters(text: str) -> dict[str, str]:
    """``name: description`` per line as ``{name: description}``; :class:`ToolConfigError` for a wrong line."""
    found: dict[str, str] = {}
    lines = [(n, line) for n, line in enumerate(text.splitlines(), start=1) if line.strip()]
    if len(lines) > MAX_PARAMETERS:
        raise ToolConfigError(f"At most {MAX_PARAMETERS} parameters")
    for number, line in lines:
        name, colon, description = line.partition(":")
        name = name.strip()
        if not colon or not PARAMETER_NAME.fullmatch(name):
            raise ToolConfigError(
                f"Line {number} is not 'name: description' (a name has lowercase letters, digits and _)"
            )
        if name in found:
            raise ToolConfigError(f"Parameter '{name}' is declared twice")
        found[name] = description.strip()
    return found


def parse_tool_names(text: str) -> list[str]:
    """The MCP tool names of *Tools to include*, one per line; :class:`ToolConfigError` for a wrong line."""
    names: list[str] = []
    lines = [(n, line.strip()) for n, line in enumerate(text.splitlines(), start=1) if line.strip()]
    if len(lines) > MAX_TOOL_NAMES:
        raise ToolConfigError(f"At most {MAX_TOOL_NAMES} tool names")
    for number, name in lines:
        if not MCP_TOOL_NAME.fullmatch(name):
            raise ToolConfigError(f"Line {number} is not a tool name")
        if name not in names:
            names.append(name)
    return names


def check_endpoint(url: str) -> None:
    """An MCP endpoint: an http(s) address with a host and without credentials (empty: not set yet)."""
    if not url.strip():
        return
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
    except ValueError as error:
        raise ToolConfigError("The address must be an http or https URL with a host") from error
    if parts.scheme not in ("http", "https") or not host:
        raise ToolConfigError("The address must be an http or https URL with a host")
    if parts.username is not None or parts.password is not None:
        raise ToolConfigError("The address must not contain a user name or password")
