"""The tools of an agent that run here: the HTTP Request Tool and the Code Tool (ADR-040).

Both are built from a tool node frozen into the snapshot and called with the model's arguments. They
follow the rules of the HTTP node and the Code node: the guarded HTTP path (SSRF rules, pinned
addresses, no redirect, capped body), the Code node's switches and limits.

Model values never meet a reference: the templates are rendered first (``${secret:...}``,
``${var...}``, ``${node...}``), then every ``{name}`` of a declared parameter is replaced in one pass.
A model that writes ``${secret:X}`` sends exactly that text, and a filled-in value is not filled again.
A parameter is not allowed in the scheme or host of the URL: the model never picks where a request goes.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx

from openartifact.agents.tool_config import parse_parameters
from openartifact.agents.tools import LOCAL_TOOLS, Tool, ToolContext
from openartifact.credentials.refs import SecretReferenceError, names_in, parse_name_lines
from openartifact.engine.code_runner import run_code
from openartifact.engine.context import ContextError, RunView
from openartifact.engine.http_runner import (
    AddressRefusedError,
    ConnectFailedError,
    guarded_exchange,
    parse_headers,
)
from openartifact.graph.node_types import parse_status_spec
from openartifact.models import NodeKind

_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]{0,31})\}")


def secret_names(kind: str, config: Mapping[str, Any]) -> list[str]:
    """The secrets a local tool uses: ``${secret:NAME}`` in the request, the Code Tool's list."""
    if kind == NodeKind.HTTP_TOOL:
        return list(names_in(*(str(config.get(k) or "") for k in ("url", "headers", "body"))))
    if kind == NodeKind.CODE_TOOL:
        return list(parse_name_lines(str(config.get("secrets") or "")))
    return []


def _schema(declared: Mapping[str, str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {n: {"type": "string", "description": d} for n, d in declared.items()},
        "required": list(declared),
    }


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _fill(template: str, values: Mapping[str, str], *, encode: bool = False) -> str:
    """Every ``{name}`` of a given parameter replaced in one pass (others stay as they are)."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            return match.group(0)
        return quote(values[name], safe="") if encode else values[name]

    return _PLACEHOLDER.sub(replace, template)


def _check_placement(url: str) -> None:
    scheme, separator, rest = url.partition("://")
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0] if separator else url
    if "{" in scheme or "{" in authority:
        raise ValueError("A parameter is allowed in the path and the query of the URL only")


def build_http_tool(frozen: Mapping[str, Any], context: ToolContext) -> Tool:
    """The HTTP Request Tool of a frozen tool node; :class:`ValueError` when it cannot be used."""
    config = frozen.get("config") or {}
    declared = parse_parameters(str(config.get("parameters") or ""))
    url_template = str(config.get("url") or "").strip()
    if not url_template:
        raise ValueError("The URL is empty")
    _check_placement(url_template)
    header_templates = parse_headers(str(config.get("headers") or ""))
    body_template = str(config.get("body") or "")
    method = str(config.get("method") or "GET")
    timeout = float(config.get("timeout_seconds") or 30)
    accepted = str(config.get("success_status") or "200-299")
    ranges = parse_status_spec(accepted)
    allow_private = bool(config.get("allow_private")) and context.allow_private_networks
    limit = int(getattr(context.limits, "http_response_limit_bytes", 1024 * 1024))
    view: RunView = context.view or RunView()
    secrets = dict(context.secrets)

    async def run(arguments: dict[str, Any]) -> str:
        used = " ".join([url_template, body_template, *header_templates.values()])
        wanted = set(_PLACEHOLDER.findall(used))
        for name in declared:
            if name in wanted and arguments.get(name) is None:
                return f"Error: the parameter {name} is missing"
        values = {n: _text(arguments[n]) for n in declared if arguments.get(n) is not None}
        try:
            url = _fill(
                view.render(url_template, secrets=secrets, percent_encode=True), values, encode=True
            )
            headers = {
                name: _fill(view.render(value, secrets=secrets), values)
                for name, value in header_templates.items()
            }
            body = _fill(view.render(body_template, secrets=secrets), values)
        except (ContextError, SecretReferenceError) as error:
            return f"Error: {error}"
        for name, value in headers.items():
            if any((ord(c) < 32 and c != "\t") or ord(c) == 127 for c in value):
                return f"Error: The header '{name}' has a control character"
        try:
            async with asyncio.timeout(timeout):
                got = await guarded_exchange(
                    method,
                    url,
                    headers,
                    body.encode("utf-8") if body else None,
                    timeout=timeout,
                    limit=limit,
                    allow_private=allow_private,
                )
        except (AddressRefusedError, ConnectFailedError) as error:
            return f"Error: {error}"
        except TimeoutError:
            return f"Error: Timeout after {timeout:g} s"
        except ValueError as error:
            return f"Error: {error}"
        except httpx.HTTPError as error:
            return f"Error: the request failed ({type(error).__name__})"
        answer = f"HTTP {got.status}\n{got.text}"
        if not any(low <= got.status <= high for low, high in ranges):
            return f"Error: {answer}"
        return answer

    return Tool(
        str(frozen.get("tool_name") or "tool"),
        str(config.get("description") or ""),
        _schema(declared),
        run,
    )


def build_code_tool(frozen: Mapping[str, Any], context: ToolContext) -> Tool:
    """The Code Tool of a frozen tool node; :class:`ValueError` when the Code node's rules forbid it."""
    from openartifact.engine.executors import OPEN_MODE_CODE_REASON, Limits

    limits = context.limits if isinstance(context.limits, Limits) else Limits()
    if not limits.code_nodes_enabled:
        raise ValueError("Code nodes are disabled")
    if limits.code_blocked_in_open_mode:
        raise ValueError(OPEN_MODE_CODE_REASON)
    config = frozen.get("config") or {}
    declared = parse_parameters(str(config.get("parameters") or ""))
    names = parse_name_lines(str(config.get("secrets") or ""))
    env = {n: context.secrets[n] for n in names if n in context.secrets}
    view: RunView = context.view or RunView()

    async def run(arguments: dict[str, Any]) -> str:
        data = json.loads(view.dumps())
        data["input"] = arguments
        result = await run_code(
            str(config.get("language") or "python"),
            str(config.get("code") or ""),
            int(config.get("timeout_seconds") or 30),
            limits.code_output_limit_bytes,
            env=env,
            limits=limits.code,
            node_id=str(frozen.get("node_id") or ""),
            context_json=json.dumps(data, ensure_ascii=False),
        )
        output = (result.output or "").rstrip("\n")
        if result.outcome != "pass":
            return f"Error: {result.reason or 'the code failed'}" + (
                f"\n{output}" if output else ""
            )
        return output

    return Tool(
        str(frozen.get("tool_name") or "tool"),
        str(config.get("description") or ""),
        _schema(declared),
        run,
    )


LOCAL_TOOLS[NodeKind.HTTP_TOOL] = build_http_tool
LOCAL_TOOLS[NodeKind.CODE_TOOL] = build_code_tool
