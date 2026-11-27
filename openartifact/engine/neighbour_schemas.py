"""What the neighbours read says (ADR-069 addendum 2): the links around every node of a graph, and where one execution is."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from openartifact.schemas_common import UtcDateTime

Connection = Literal["next", "pass", "failure", "branch", "tool", "stage"]
NodeState = Literal["pass", "fail", "running", "stopped"]


class Link(BaseModel):
    """One connection seen from a node: the node on the other end and the connector it hangs on.

    ``port`` is the output connector of the *source* of the connection (``pass``, ``error``, ``fail``, ``yes``, ``case_2``, ``out``,
    ``start``, ``end``, ``tool``) and ``port_label`` how the editor writes it (*On Pass*, *On Error*, *On Fail*, ...). ``connection``
    sorts it: ``next`` (a plain output), ``pass``, ``failure`` (*On Error* and *On Fail*), ``branch`` (If and Switch), ``tool`` (an agent's
    tool) or ``stage`` (the start and end of a stage frame). In ``successors`` ``node_id`` is the node the connection leads to and
    ``target_port`` its input; in ``predecessors`` it is the node the connection comes from.
    """

    edge_id: str | None
    node_id: str
    name: str
    kind: str
    port: str
    port_label: str
    connection: Connection
    target_port: str


class NodeNeighbours(BaseModel):
    """A node (a stage, an action, a trigger, a Code node, ...) with what leads to it and what it leads to."""

    id: str
    name: str
    kind: str
    stage_id: str | None
    stage_name: str | None
    predecessors: list[Link]
    successors: list[Link]


class GraphVersionUsed(BaseModel):
    """Which state of the graph was read: ``published`` (``number``) or the ``draft`` (``number`` ``None``)."""

    source: Literal["published", "draft"]
    number: int | None


class GraphHead(BaseModel):
    id: str
    name: str
    kind: Literal["pipeline", "action"]


class GraphNeighbours(BaseModel):
    """Every node of a pipeline (stages with their actions) or of an action definition with its predecessors and successors.

    The same connections the graph editor draws (``GET /api/pipelines/{id}``, ``GET /api/actions/{id}``): every connection appears once
    as a successor of its source and once as a predecessor of its target.
    """

    graph: GraphHead
    version: GraphVersionUsed
    nodes: list[NodeNeighbours]


class PlaceNode(BaseModel):
    """A node of a frozen graph that the position names."""

    id: str
    name: str
    kind: str
    stage_id: str | None = None
    stage_name: str | None = None


class Where(BaseModel):
    """One level of *where an execution is*: the node of this graph the execution is in (root pipeline first)."""

    graph_id: str
    graph_name: str
    graph_kind: Literal["pipeline", "action"]
    node: PlaceNode


class PathNode(PlaceNode):
    """A node a visit reached, with its state as the flow view draws it: ``pass``, ``fail``, ``running`` or ``stopped``."""

    state: NodeState


class PathStep(BaseModel):
    """A recorded step (a node of an action definition that ran) with its result; the output is left out (``get_execution_step``)."""

    seq: int
    node_id: str
    name: str
    kind: str
    outcome: str
    port: str | None
    reason: str | None


class PathVisit(BaseModel):
    """One pass through a graph (see ``FlowVisit``): the nodes reached in order and the steps recorded in it."""

    index: int
    parent: int | None
    level: int
    graph_id: str
    graph_name: str
    graph_kind: Literal["pipeline", "action"]
    entered_via: PlaceNode | None
    outcome: Literal["pass", "fail", "running"] | None
    nodes: list[PathNode]
    steps: list[PathStep]


class ExecutionState(BaseModel):
    id: str
    number: int
    status: Literal["running", "done", "failed", "stopped"]
    pipeline_id: str | None
    pipeline_name: str
    started_at: UtcDateTime
    finished_at: UtcDateTime | None


class ExecutionPosition(BaseModel):
    """Where one execution is, from its frozen graphs (the same data as its flow).

    ``path`` is what was walked, visit by visit. ``at`` says where it is: from the root pipeline down to the node it is in
    (while it runs: the node it waits in; once it ended: the node it ended in; a stopped one: the node it was stopped in). ``next`` are
    the connections that leave that node (which port leads where), ``afterwards`` those of the nodes around it, innermost first
    (for a Code node in an action: what the action's own node leads to). A node whose connector leads nowhere has no entry for it.
    """

    execution: ExecutionState
    at: list[Where]
    next: list[Link]
    afterwards: list[list[Link]]
    path: list[PathVisit]
    truncated: bool = Field(default=False, description="The path was cut at the limit of visits.")
