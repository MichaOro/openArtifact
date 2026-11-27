"""The flow of one execution: the graphs it ran through, the steps, and the path in terms of graphs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from openartifact.engine.schemas import ExecutionRead, ExecutionStepRead
from openartifact.schemas_common import UtcDateTime


class FlowNode(BaseModel):
    """A node of a frozen graph, in the shape of the editor API (``GET /api/pipelines/{id}``).

    ``name`` is the node's own name; ``definition_name`` the name of the action definition or pipeline
    it links to (the editor shows it instead). Sizes of stages that an old snapshot lacks are filled
    with the default size of a stage.
    """

    id: str
    kind: str
    stage_id: str | None
    name: str
    label: str
    x: float
    y: float
    width: float | None
    height: float | None
    fail_enabled: bool
    seconds: int | None
    config: dict[str, Any] = Field(default_factory=dict)
    definition_id: str | None
    definition_name: str | None
    definition_fail_enabled: bool | None
    #: "Check #2": the number of this placement while its definition is placed more than once in the pipeline (ADR-082), else ``None``.
    placement_number: int | None = None


class FlowEdge(BaseModel):
    """An edge of a frozen graph. ``id`` is the edge's own id; for snapshots that lack one it is
    ``source_id:source_port>target_id:target_port``."""

    id: str
    source_id: str
    source_port: str
    target_id: str
    target_port: str
    style: str
    source_slot: int
    target_slot: int


class FlowGraph(BaseModel):
    """The root pipeline, a called pipeline or an action definition as frozen at the start."""

    id: str
    kind: Literal["pipeline", "action"]
    name: str
    nodes: list[FlowNode]
    edges: list[FlowEdge]


class TraversedEdge(BaseModel):
    """An edge of a graph that the execution went along (``id`` is the id of the ``FlowEdge``)."""

    id: str
    source_id: str
    source_port: str
    target_id: str
    target_port: str


class EnteredVia(BaseModel):
    """The node of the parent graph a visit was entered from (an action or a pipeline node)."""

    graph_id: str
    node_id: str


class FlowVisit(BaseModel):
    """One pass of the execution through a graph.

    ``index`` numbers the visits in the order they began; ``parent`` is the index of the visit this one
    was entered from (``None`` for the root). ``level`` is how deep the graph is nested: 0 the root
    pipeline, 1 its actions and called pipelines, 2 theirs, and so on.

    ``nodes`` are the node ids reached in order (a node can appear twice if the flow loops) and
    ``edges`` the distinct edges gone along. For a pipeline graph they are the trigger, stages, actions
    and pipeline nodes and complete; for an action definition the trigger, timers, code and HTTP nodes
    and the output. ``skipped_nodes`` (pipelines only) are the stages, pipeline nodes and actions in
    front of the entry the execution started at. While the execution runs, the node it is waiting
    in is the last of ``nodes``.

    ``outcome``: ``pass``, ``fail``, ``running``, or ``None`` when the execution was stopped inside
    it. ``left_port`` (action definitions) is the port of the action node taken in the parent graph:
    ``pass`` or ``error``.
    """

    index: int
    parent: int | None
    graph_id: str
    level: int
    entered_via: EnteredVia | None
    nodes: list[str]
    edges: list[TraversedEdge]
    skipped_nodes: list[str]
    outcome: Literal["pass", "fail", "running"] | None
    left_port: Literal["pass", "error"] | None
    first_seq: int | None
    last_seq: int | None
    started_at: UtcDateTime | None
    finished_at: UtcDateTime | None


class FlowReached(BaseModel):
    """Everything of one graph that any visit touched: node ids and edge ids. What a graph has
    beyond this was not run (the view dims it)."""

    nodes: list[str]
    edges: list[str]


class FlowStepRead(ExecutionStepRead):
    """A step in the flow. Without ``?outputs=true`` ``output`` is empty and ``output_included`` false;
    ``output_length`` is the length of the stored output either way."""

    output_length: int
    output_included: bool


class FlowAttachedGuard(BaseModel):
    """A guard attached to a place of the frozen run (the snapshot's switched-on attachments): ``id`` is the attachment's,
    ``enabled`` whether it is still switched on now (the engine checks that live: a guard switched off during the run does
    not fire any more)."""

    id: str
    guard_id: str
    name: str
    scope_type: str
    scope_id: str
    graph_id: str
    enabled: bool = True


class ExecutionFlow(BaseModel):
    """The flow of one execution: ``graphs`` by id (the frozen snapshot), the ``steps`` and the
    ``visits`` and ``reached`` sets the server derived from them. Never changes when the live
    pipeline is edited or deleted."""

    execution: ExecutionRead
    root_graph_id: str
    graphs: dict[str, FlowGraph]
    steps: list[FlowStepRead]
    visits: list[FlowVisit]
    reached: dict[str, FlowReached]
    #: The guards' bookkeeping of the execution (ADR-060): ``scopes`` (counters per scope), ``guards`` (per guard
    #: and scope), ``progress_at``, ``heartbeat`` and ``firings`` (each with its facts); ``{}`` without guards.
    guards: dict[str, Any] = Field(default_factory=dict)
    #: The guards attached to the places of the frozen run, so the flow can show a shield where one watches (ADR-060).
    attached_guards: list[FlowAttachedGuard] = Field(default_factory=list)
