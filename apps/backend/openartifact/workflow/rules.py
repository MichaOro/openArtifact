"""Which ports may be connected. Pure functions, no database access.

Ports:

* trigger: ``out``
* stage: ``in``, ``out`` (to other stages) and the inner pair ``entry`` / ``exit`` (to and from its actions)
* action: ``in``, ``pass``, ``error`` (only inside its own stage)
* complete: ``in``
"""

from __future__ import annotations

from dataclasses import dataclass

from openartifact.models import NodeKind

OUTPUT_PORTS = {
    NodeKind.TRIGGER: ("out",),
    NodeKind.STAGE: ("out", "entry"),
    NodeKind.ACTION: ("pass", "error"),
    NodeKind.COMPLETE: (),
}
INPUT_PORTS = {
    NodeKind.TRIGGER: (),
    NodeKind.STAGE: ("in", "exit"),
    NodeKind.ACTION: ("in",),
    NodeKind.COMPLETE: ("in",),
}


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
    if source_port not in OUTPUT_PORTS[source.kind]:
        raise EdgeError(f"A {source.kind.value} has no output '{source_port}'")
    if target_port not in INPUT_PORTS[target.kind]:
        raise EdgeError(f"A {target.kind.value} has no input '{target_port}'")

    if source.kind is NodeKind.STAGE and source_port == "entry":
        # inner start of a stage: only to an action of that stage
        if target.kind is not NodeKind.ACTION or target.stage_id != source.id:
            raise EdgeError("The start of a stage connects to an action inside that stage")
    elif source.kind is NodeKind.ACTION:
        # inside a stage: to another action of the same stage, or to the stage's exit
        if target.kind is NodeKind.ACTION:
            if target.stage_id != source.stage_id:
                raise EdgeError("Actions connect only to actions of their own stage")
        elif target.kind is NodeKind.STAGE and target_port == "exit":
            if target.id != source.stage_id:
                raise EdgeError("An action connects only to the exit of its own stage")
        else:
            raise EdgeError("An action connects to actions of its stage or to the stage exit")
    else:
        # trigger / stage output: between top-level nodes
        if target.kind is NodeKind.STAGE and target_port == "exit":
            raise EdgeError("The exit of a stage is fed by its own actions")
        if target.kind is NodeKind.ACTION:
            raise EdgeError("Stages connect to stages; actions are reached from inside a stage")
        if target.kind is NodeKind.STAGE and target.id == source.id:
            raise EdgeError("A stage cannot be connected to itself")
        if source.kind is NodeKind.TRIGGER and target.kind is NodeKind.COMPLETE:
            raise EdgeError("A trigger starts a stage")
