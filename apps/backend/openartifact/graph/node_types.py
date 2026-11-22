"""The kinds of nodes, as classes: one place that says what a node is and what it may do.

A :class:`NodeType` describes a kind of node: where it may be used (a pipeline or an action
definition), whether it comes with the graph and stays (``fixed``) or is added through the "+"
menu (``addable``), its ports, its settings and what it links to. ``connect_error`` holds its
connection rules. The base class has the common behaviour; a kind overrides only what differs.
Every kind is registered through :func:`register`, the same way an extension would add one later
(see ADR-014). The editor loads these descriptions (``GET /api/node-types``) and draws from them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from openartifact.models import GraphKind, NodeKind

if TYPE_CHECKING:
    from openartifact.graph.rules import Endpoint

PIPELINE = GraphKind.PIPELINE
ACTION_DEFINITION = GraphKind.ACTION
#: A timer pauses for one second to one day.
TIMER_MIN_SECONDS = 1
TIMER_MAX_SECONDS = 86400


class Ports:
    """The names of the connectors that the rules and the engine refer to."""

    IN = "in"
    OUT = "out"
    START = "start"
    END = "end"
    PASS = "pass"
    ERROR = "error"
    FAIL = "fail"


@dataclass(frozen=True)
class Port:
    """A connector of a node."""

    name: str
    label: str


@dataclass(frozen=True)
class Setting:
    """A value the user sets on a node in the inspector (stored in the column of the same name)."""

    key: str
    label: str
    type: str  # "integer" or "switch"
    minimum: int | None = None
    maximum: int | None = None
    default: Any = None


class NodeType:
    """What every kind of node has; kinds override the class attributes and hooks they need."""

    kind: ClassVar[NodeKind]
    label: ClassVar[str]
    scopes: ClassVar[frozenset[GraphKind]] = frozenset({PIPELINE})
    fixed: ClassVar[bool] = False  # comes with the graph, cannot be added or deleted
    addable: ClassVar[bool] = False  # offered in the "+" menu
    chain: ClassVar[bool] = False  # a step of the main line (new ones are placed after these)
    ending: ClassVar[bool] = False  # the end of the main line (moves on to make room)
    inputs: ClassVar[tuple[Port, ...]] = ()
    outputs: ClassVar[tuple[Port, ...]] = ()
    settings: ClassVar[tuple[Setting, ...]] = ()
    links_to: ClassVar[GraphKind | None] = (
        None  # the kind of graphs row ``definition_id`` points at
    )
    size: ClassVar[tuple[float, float] | None] = None  # only stages store a size of their own

    @property
    def default_name(self) -> str:
        return self.label

    def input_names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.inputs)

    def output_names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.outputs)

    def connect_error(
        self, source: Endpoint, source_port: str, target: Endpoint, target_port: str
    ) -> str | None:
        """Why ``source.source_port`` may not feed ``target.target_port`` (``None``: it may).

        The common rule for steps of the main line: on to a stage's start, a pipeline node or an
        ending; never into an action (actions are reached from inside their stage), never to itself.
        """
        if target.id == source.id:
            return f"A {self.kind.value} cannot feed itself"
        if target.kind is NodeKind.ACTION:
            return "Stages connect to stages; actions are reached from inside a stage"
        if target.kind is NodeKind.STAGE and target_port != Ports.START:
            return "The end of a stage is fed by its own actions"
        return None

    def describe(self) -> dict[str, Any]:
        """The description the editor draws from."""
        return {
            "kind": self.kind.value,
            "label": self.label,
            "scopes": sorted(s.value for s in self.scopes),
            "fixed": self.fixed,
            "addable": self.addable,
            "chain": self.chain,
            "ending": self.ending,
            "inputs": [{"name": p.name, "label": p.label} for p in self.inputs],
            "outputs": [{"name": p.name, "label": p.label} for p in self.outputs],
            "settings": [s.__dict__ for s in self.settings],
            "links_to": self.links_to.value if self.links_to else None,
        }


class TriggerType(NodeType):
    kind = NodeKind.TRIGGER
    label = "Trigger"
    scopes = frozenset({PIPELINE, ACTION_DEFINITION})
    fixed = True
    chain = True
    outputs = (Port(Ports.OUT, "Next"),)


class StageType(NodeType):
    """A container of actions. ``start`` and ``end`` each serve both sides: ``start`` receives from
    before and feeds the first action, ``end`` receives from the actions and leads on."""

    kind = NodeKind.STAGE
    label = "Stage"
    addable = True
    chain = True
    inputs = (Port(Ports.START, "Start"), Port(Ports.END, "End"))
    outputs = (Port(Ports.START, "First action"), Port(Ports.END, "Next"))
    size = (360.0, 240.0)

    def connect_error(
        self, source: Endpoint, source_port: str, target: Endpoint, target_port: str
    ) -> str | None:
        if source_port == Ports.START:
            if target.kind is not NodeKind.ACTION or target.stage_id != source.id:
                return "The start of a stage connects to an action inside that stage"
            return None
        if target.id == source.id:
            return "A stage cannot be connected to itself"
        return super().connect_error(source, source_port, target, target_port)


class ActionType(NodeType):
    """A step inside a stage; an empty shell until it is linked to an action definition."""

    kind = NodeKind.ACTION
    label = "Action"
    inputs = (Port(Ports.IN, "Input"),)
    outputs = (Port(Ports.PASS, "On Pass"), Port(Ports.ERROR, "On Error"))
    links_to = ACTION_DEFINITION

    def connect_error(
        self, source: Endpoint, source_port: str, target: Endpoint, target_port: str
    ) -> str | None:
        if target.kind is NodeKind.ACTION:
            if target.stage_id != source.stage_id:
                return "Actions connect only to actions of their own stage"
            return None
        if target.kind is NodeKind.STAGE and target_port == Ports.END:
            return (
                None
                if target.id == source.stage_id
                else "An action connects only to the end of its own stage"
            )
        return "An action connects to actions of its stage or to the stage end"


class PipelineNodeType(NodeType):
    """A step of the main line that runs another pipeline up to its complete, then goes on."""

    kind = NodeKind.PIPELINE
    label = "Pipeline"
    addable = True
    chain = True
    inputs = (Port(Ports.IN, "Input"),)
    outputs = (Port(Ports.OUT, "Next"),)
    links_to = PIPELINE


class CompleteType(NodeType):
    kind = NodeKind.COMPLETE
    label = "Complete"
    fixed = True
    ending = True
    inputs = (Port(Ports.IN, "Input"),)


class TimerType(NodeType):
    kind = NodeKind.TIMER
    label = "Timer"
    scopes = frozenset({ACTION_DEFINITION})
    addable = True
    chain = True
    inputs = (Port(Ports.IN, "Input"),)
    outputs = (Port(Ports.OUT, "Next"),)
    settings = (
        Setting(
            "seconds",
            "Seconds",
            "integer",
            minimum=TIMER_MIN_SECONDS,
            maximum=TIMER_MAX_SECONDS,
            default=5,
        ),
    )


class OutputType(NodeType):
    """The end of an action definition: a connector per outcome (On Fail only when switched on)."""

    kind = NodeKind.OUTPUT
    label = "Output"
    scopes = frozenset({ACTION_DEFINITION})
    fixed = True
    ending = True
    inputs = (Port(Ports.PASS, "On Pass"), Port(Ports.FAIL, "On Fail"))
    settings = (Setting("fail_enabled", "On Fail", "switch", default=False),)


NODE_TYPES: dict[NodeKind, NodeType] = {}


def register(node_type: NodeType) -> NodeType:
    """Make a kind of node known (built-in kinds use this as an extension would)."""
    NODE_TYPES[node_type.kind] = node_type
    return node_type


def node_type(kind: NodeKind | str) -> NodeType:
    return NODE_TYPES[NodeKind(kind)]


def kinds_in(scope: GraphKind) -> set[NodeKind]:
    """The kinds a pipeline (``pipeline``) or an action definition (``action``) may contain."""
    return {t.kind for t in NODE_TYPES.values() if scope in t.scopes}


def fixed_in(scope: GraphKind) -> list[NodeType]:
    """The kinds that come with a new graph of that scope, in order (start first)."""
    return [t for t in NODE_TYPES.values() if scope in t.scopes and t.fixed]


for _type in (
    TriggerType(),
    StageType(),
    ActionType(),
    PipelineNodeType(),
    CompleteType(),
    TimerType(),
    OutputType(),
):
    register(_type)
