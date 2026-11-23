"""The tools of an agent that run here: the HTTP Request Tool and the Code Tool (ADR-040)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from openartifact.credentials.refs import names_in, parse_name_lines
from openartifact.models import NodeKind


def secret_names(kind: str, config: Mapping[str, Any]) -> list[str]:
    """The secrets a local tool uses: ``${secret:NAME}`` in the request, the Code Tool's list."""
    if kind == NodeKind.HTTP_TOOL:
        return list(names_in(*(str(config.get(k) or "") for k in ("url", "headers", "body"))))
    if kind == NodeKind.CODE_TOOL:
        return list(parse_name_lines(str(config.get("secrets") or "")))
    return []
