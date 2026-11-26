"""What a node does outside its run: ``none``, ``read``, ``write`` or ``mixed`` (ADR-086).

A dry run runs what only reads and skips what writes, so every kind of node declares its effect in its manifest
(:class:`~openartifact.graph.manifest.EffectSpec`). The declaration may depend on a setting of the node (the HTTP method, the
operation of GitHub or of the Artifact node) or on a switch (Postgres *Allow changes*, Execute Command *Read only*). What a kind does not
declare, a value of a setting the declaration does not know, and a kind that is not known at all count as **writing**: the safe side.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from openartifact.graph.node_types import NODE_TYPES
from openartifact.models import NodeKind

NONE, READ, WRITE, MIXED = "none", "read", "write", "mixed"


def effect_of(kind: str, config: Mapping[str, Any] | None) -> str:
    """The effect of a node of ``kind`` with this ``config``: ``none``, ``read``, ``write`` or ``mixed``."""
    try:
        node_type = NODE_TYPES[NodeKind(kind)]
    except (ValueError, KeyError):
        return WRITE
    spec = node_type.effect
    if spec is None:
        return WRITE
    config = config or {}
    flag = spec.get("flag")
    if flag is not None and config.get(flag):
        return str(spec["flag_true"])
    setting = spec.get("setting")
    if setting is not None:
        shown = config.get(setting)
        if shown is None:
            shown = _default_of(node_type, setting)
        return READ if shown in spec.get("reading", []) else str(WRITE)
    return str(spec["default"])


def _default_of(node_type: Any, setting: str) -> Any:
    for candidate in node_type.settings:
        if candidate.key == setting:
            return candidate.default
    return None


def writes(kind: str, config: Mapping[str, Any] | None) -> bool:
    """True when a dry run skips a node of this kind with this config (``mixed`` kinds run: their tools decide)."""
    return effect_of(kind, config) == WRITE
