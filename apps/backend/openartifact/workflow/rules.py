"""Which ports may be connected. Pure functions, no database access.

The ports of each kind and its rules live with the kind in :mod:`.node_types`; this module checks
an edge against them.
"""

from __future__ import annotations

from dataclasses import dataclass

from openartifact.models import NodeKind
from openartifact.workflow.node_types import node_type


class EdgeError(ValueError):
    """The requested connection is not allowed."""


@dataclass(frozen=True)
class Endpoint:
    """A node as far as the rules care."""

    id: str
    kind: NodeKind
    stage_id: str | None = None


def validate_edge(source: Endpoint, source_port: str, target: Endpoint, target_port: str) -> None:
    """Raise :class:`EdgeError` unless ``source.source_port`` may feed ``target.target_port``."""
    source_type, target_type = node_type(source.kind), node_type(target.kind)
    if source_port not in source_type.output_names():
        raise EdgeError(f"A {source.kind.value} has no output '{source_port}'")
    if target_port not in target_type.input_names():
        raise EdgeError(f"A {target.kind.value} has no input '{target_port}'")
    message = source_type.connect_error(source, source_port, target, target_port)
    if message:
        raise EdgeError(message)
