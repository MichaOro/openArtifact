"""Which ports may be connected. Pure functions, no database access.

Ports:

* trigger: ``out``
* stage: ``start`` and ``end``. Each serves both sides: ``start`` receives from the trigger or a
  previous stage and feeds the first action; ``end`` receives from the stage's actions and leads on
  to the next stage or an ending. Which side an edge is on follows from its other end.
* action: ``in``, ``pass``, ``error`` (only inside its own stage)
* complete: ``in``
* output (only in action definitions): ``in``; its outcomes *On Pass* / *On Fail* are not ports
"""

from __future__ import annotations

from dataclasses import dataclass

from openartifact.models import NodeKind

OUTPUT_PORTS = {
    NodeKind.TRIGGER: ("out",),
    NodeKind.STAGE: ("start", "end"),
    NodeKind.ACTION: ("pass", "error"),
    NodeKind.COMPLETE: (),
    NodeKind.OUTPUT: (),
}
INPUT_PORTS = {
    NodeKind.TRIGGER: (),
    NodeKind.STAGE: ("start", "end"),
    NodeKind.ACTION: ("in",),
    NodeKind.COMPLETE: ("in",),
    NodeKind.OUTPUT: ("in",),
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

    if source.kind is NodeKind.STAGE and source_port == "start":
        # the stage's start feeds the first action, which must be inside it
        if target.kind is not NodeKind.ACTION or target.stage_id != source.id:
            raise EdgeError("The start of a stage connects to an action inside that stage")
    elif source.kind is NodeKind.ACTION:
        # inside a stage: to another action of the same stage, or to the stage's end
        if target.kind is NodeKind.ACTION:
            if target.stage_id != source.stage_id:
                raise EdgeError("Actions connect only to actions of their own stage")
        elif target.kind is NodeKind.STAGE and target_port == "end":
            if target.id != source.stage_id:
                raise EdgeError("An action connects only to the end of its own stage")
        else:
            raise EdgeError("An action connects to actions of its stage or to the stage end")
    else:
        # trigger or the end of a stage: on to the start of another stage, or to an ending
        if target.kind is NodeKind.ACTION:
            raise EdgeError("Stages connect to stages; actions are reached from inside a stage")
        if target.kind is NodeKind.STAGE:
            if target_port != "start":
                raise EdgeError("The end of a stage is fed by its own actions")
            if target.id == source.id:
                raise EdgeError("A stage cannot be connected to itself")
        if source.kind is NodeKind.TRIGGER and target.kind is NodeKind.COMPLETE:
            raise EdgeError("A trigger starts a stage")
