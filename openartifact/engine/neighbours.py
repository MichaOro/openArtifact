"""Who is connected to whom, and where an execution is (ADR-069 addendum 2). Read only.

*One implementation of the connections.* :func:`links_of` turns the nodes and edges of any graph (the draft the editor draws, a published
version, the frozen graph of an execution) into the predecessors and successors of every node. The neighbours of a pipeline or an action
definition (``GET /api/pipelines/{id}/neighbours``) and the position of an execution (``.../executions/{id}/position``) are both made
with it, and the position is made from the same :class:`~openartifact.engine.flow_schemas.ExecutionFlow` the flow view draws, so the
page and the API cannot tell different stories. ``tests/test_neighbours.py`` holds the two against each other.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.engine.flow_schemas import ExecutionFlow, FlowGraph, FlowStepRead, FlowVisit
from openartifact.engine.neighbour_schemas import (
    Connection,
    ExecutionPosition,
    ExecutionState,
    GraphHead,
    GraphNeighbours,
    GraphVersionUsed,
    Link,
    NodeNeighbours,
    NodeState,
    PathNode,
    PathStep,
    PathVisit,
    PlaceNode,
    Where,
)
from openartifact.graph import versions
from openartifact.graph.content import graph_of
from openartifact.graph.node_types import Ports, node_type
from openartifact.models import Graph

Raw = Mapping[str, Any]

#: The path of a position is cut here (a loop can make thousands of visits); the newest ones stay.
MAX_PATH_VISITS = 200
MAX_REASON = 300

_BRANCH = {Ports.YES, Ports.NO, Ports.ELSE}


def port_label(kind: str, port: str) -> str:
    """How the editor writes a connector of a node of ``kind`` (*On Pass*, *On Error*, *Input*, ...); the name itself when it has no
    label (the cases of a Switch are labelled by their condition in the editor)."""
    try:
        view = node_type(kind)
    except ValueError:
        return port
    for found in (*view.outputs, *view.inputs):
        if found.name == port and found.label:
            return found.label
    return port


def connection_of(port: str) -> Connection:
    """The sort of a connection by the output connector it leaves from."""
    if port == Ports.PASS:
        return "pass"
    if port in (Ports.ERROR, Ports.FAIL):
        return "failure"
    if port in _BRANCH or port.startswith("case_"):
        return "branch"
    if port in (Ports.TOOL, Ports.TOOLS):
        return "tool"
    if port in (Ports.START, Ports.END):
        return "stage"
    return "next"


def display_name(node: Raw) -> str:
    """What the editor calls a node: an action or pipeline node carries the name of what it links to (its ``label``)."""
    return str(node.get("definition_name") or node.get("label") or node.get("name") or "")


def _order(kind: str, port: str) -> int:
    try:
        names = [p.name for p in node_type(kind).outputs]
    except ValueError:
        return 0
    return names.index(port) if port in names else len(names)


def _link(edge: Raw, other: Raw, port_owner: Raw) -> Link:
    port = str(edge["source_port"])
    return Link(
        edge_id=str(edge["id"]) if edge.get("id") else None,
        node_id=str(other["id"]),
        name=display_name(other),
        kind=str(other["kind"]),
        port=port,
        port_label=port_label(str(port_owner["kind"]), port),
        connection=connection_of(port),
        target_port=str(edge["target_port"]),
    )


def links_of(nodes: Sequence[Raw], edges: Sequence[Raw]) -> dict[str, NodeNeighbours]:
    """The predecessors and successors of every node, by node id. An edge to or from a node that is not in ``nodes`` is left out."""
    by_id = {str(n["id"]): n for n in nodes}
    successors: dict[str, list[tuple[Raw, Raw]]] = defaultdict(list)
    predecessors: dict[str, list[tuple[Raw, Raw]]] = defaultdict(list)
    for edge in edges:
        source, target = by_id.get(str(edge["source_id"])), by_id.get(str(edge["target_id"]))
        if source is None or target is None:
            continue
        successors[str(source["id"])].append((edge, target))
        predecessors[str(target["id"])].append((edge, source))

    def key(source_of: Raw) -> Any:
        def inner(pair: tuple[Raw, Raw]) -> tuple[int, str, str, str]:
            edge, other = pair
            owner = source_of if source_of else other
            return (
                _order(str(owner["kind"]), str(edge["source_port"])),
                str(edge["source_port"]),
                display_name(other),
                str(other["id"]),
            )

        return inner

    result: dict[str, NodeNeighbours] = {}
    for node in nodes:
        node_id = str(node["id"])
        stage = by_id.get(str(node["stage_id"])) if node.get("stage_id") else None
        result[node_id] = NodeNeighbours(
            id=node_id,
            name=display_name(node),
            kind=str(node["kind"]),
            stage_id=str(node["stage_id"]) if node.get("stage_id") else None,
            stage_name=display_name(stage) if stage else None,
            predecessors=[_link(e, o, o) for e, o in sorted(predecessors[node_id], key=key({}))],
            successors=[_link(e, o, node) for e, o in sorted(successors[node_id], key=key(node))],
        )
    return result


# ── a graph ───────────────────────────────────────────────────────────


async def graph_neighbours(
    session: AsyncSession, graph: Graph, version: str = "published"
) -> GraphNeighbours | None:
    """The neighbours of a pipeline or an action definition.

    ``version``: ``published`` (the default: what executions run; the draft while nothing is published, as ADR-070 says), ``draft`` (what
    the editor shows) or the number of a published version. ``None`` when that version does not exist.
    """
    used: GraphVersionUsed
    if version == "draft":
        content = await graph_of(session, graph.id)
        used = GraphVersionUsed(source="draft", number=None)
    else:
        published = None
        if version == "published":
            published = await versions.current_version(session, graph)
        elif version.isdigit():
            published = await versions.get_version(session, graph.id, int(version))
            if published is None:
                return None
        else:
            raise ValueError("version is 'published', 'draft' or the number of a published version")
        if published is None:
            content = await graph_of(session, graph.id)
            used = GraphVersionUsed(source="draft", number=None)
        else:
            content = json.loads(published.content)
            used = GraphVersionUsed(source="published", number=published.number)
    nodes = content.get("nodes", [])
    links = links_of(nodes, content.get("edges", []))
    return GraphNeighbours(
        graph=GraphHead(id=graph.id, name=graph.name, kind=graph.kind),  # type: ignore[arg-type]
        version=used,
        nodes=[links[str(n["id"])] for n in nodes],
    )


# ── an execution ──────────────────────────────────────────────────────

_FINISHED: dict[str, NodeState] = {"pass": "pass", "fail": "fail", "running": "running"}


def _state(outcome: str | None) -> NodeState:
    """The state of an unfinished tail or a child the way ``FlowModel`` of the flow view maps an outcome (``None``: stopped there)."""
    return _FINISHED.get(outcome or "", "stopped")


def _place(node: Raw, graph: FlowGraph) -> PlaceNode:
    by_id = {n.id: n for n in graph.nodes}
    stage = by_id.get(node["stage_id"]) if node.get("stage_id") else None
    return PlaceNode(
        id=node["id"],
        name=display_name(node),
        kind=node["kind"],
        stage_id=node.get("stage_id"),
        stage_name=display_name(stage.model_dump()) if stage else None,
    )


def _visit_steps(flow: ExecutionFlow, visit: FlowVisit, graph: FlowGraph) -> list[FlowStepRead]:
    """The steps recorded inside an action visit (a pipeline visit has none of its own), like ``FlowModel.stepsOf``."""
    if visit.first_seq is None or visit.last_seq is None or graph.kind != "action":
        return []
    ids = {n.id for n in graph.nodes}
    return [
        s for s in flow.steps if visit.first_seq <= s.seq <= visit.last_seq and s.node_id in ids
    ]


def _path_visit(flow: ExecutionFlow, visit: FlowVisit, children: list[FlowVisit]) -> PathVisit:
    """One visit with the state of each node it reached, by the rules of ``FlowModel.describe`` of the flow view: a node with a step has
    the step's outcome, one with child visits the outcome of the last child, the tail of an unfinished visit the visit's own state;
    everything else passed."""
    graph = flow.graphs[visit.graph_id]
    by_id = {n.id: n for n in graph.nodes}
    steps = list(_visit_steps(flow, visit, graph))
    unfinished = _state(visit.outcome) if visit.outcome != "pass" else None
    last = len(visit.nodes) - 1
    tail = by_id.get(visit.nodes[last]) if visit.nodes else None
    tail_stage = (tail.id if tail.kind == "stage" else tail.stage_id) if tail else None
    nodes: list[PathNode] = []
    taken: list[FlowStepRead] = []
    for position, node_id in enumerate(visit.nodes):
        node = by_id.get(node_id)
        if node is None:
            continue
        index = next((i for i, s in enumerate(steps) if s.node_id == node_id), -1)
        step = steps.pop(index) if index >= 0 else None
        if step is not None:
            taken.append(step)
        via = [c for c in children if c.entered_via and c.entered_via.node_id == node_id]
        state: NodeState = "pass"
        if step is not None:
            state = _state(step.outcome) if step.outcome in _FINISHED else "stopped"
        elif via:
            state = _state(via[-1].outcome)
        elif unfinished and (position == last or (node.kind == "stage" and node_id == tail_stage)):
            state = unfinished  # the node it ended in, and the stage that holds it
        nodes.append(PathNode(**_place(node.model_dump(), graph).model_dump(), state=state))
    entered = None
    if visit.entered_via is not None:
        parent_graph = flow.graphs.get(visit.entered_via.graph_id)
        if parent_graph is not None:
            origin = next(
                (n for n in parent_graph.nodes if n.id == visit.entered_via.node_id), None
            )
            if origin is not None:
                entered = _place(origin.model_dump(), parent_graph)
    return PathVisit(
        index=visit.index,
        parent=visit.parent,
        level=visit.level,
        graph_id=graph.id,
        graph_name=graph.name,
        graph_kind=graph.kind,
        entered_via=entered,
        outcome=visit.outcome,
        nodes=nodes,
        steps=[
            PathStep(
                seq=s.seq,
                node_id=s.node_id,
                name=s.node_name,
                kind=s.kind,
                outcome=s.outcome,
                port=s.port,
                reason=s.reason[:MAX_REASON] if s.reason else None,
            )
            for s in taken
        ],
    )


def _current_visit(visits: Sequence[FlowVisit]) -> FlowVisit | None:
    """The visit the execution is in: the newest one that is still running or was stopped; once it ended, the newest of all."""
    open_ones = [v for v in visits if v.outcome in ("running", None)]
    if open_ones:
        return max(open_ones, key=lambda v: v.index)
    return max(visits, key=lambda v: v.index, default=None)


def position_of(flow: ExecutionFlow) -> ExecutionPosition:
    """Where the execution of ``flow`` is: the place (root pipeline down to the node), what leaves it, and the path walked."""
    execution = flow.execution
    state = ExecutionState(
        id=execution.id,
        number=execution.number,
        status=execution.status.value,
        pipeline_id=execution.pipeline_id,
        pipeline_name=execution.pipeline_name,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
    )
    visits = list(flow.visits)
    by_index = {v.index: v for v in visits}
    children: dict[int, list[FlowVisit]] = defaultdict(list)
    for v in visits:
        if v.parent is not None:
            children[v.parent].append(v)
    shown = visits[-MAX_PATH_VISITS:]
    path = [_path_visit(flow, v, children[v.index]) for v in shown]

    current = _current_visit(visits)
    at: list[Where] = []
    next_links: list[Link] = []
    afterwards: list[list[Link]] = []
    if current is not None:
        chain: list[FlowVisit] = []  # the visits from the root down to the current one
        walk: FlowVisit | None = current
        while walk is not None:
            chain.insert(0, walk)
            walk = by_index.get(walk.parent) if walk.parent is not None else None
        places: list[tuple[Where, FlowGraph, str]] = []
        for i, visit in enumerate(chain):
            graph = flow.graphs[visit.graph_id]
            if i + 1 < len(chain):
                via = chain[i + 1].entered_via
                node_id = via.node_id if via else None
            else:
                node_id = visit.nodes[-1] if visit.nodes else None
            node = next((n for n in graph.nodes if n.id == node_id), None)
            if node is None:
                continue
            where = Where(
                graph_id=graph.id,
                graph_name=graph.name,
                graph_kind=graph.kind,
                node=_place(node.model_dump(), graph),
            )
            places.append((where, graph, node.id))
        at = [w for w, _, _ in places]
        for index, (_, graph, node_id) in enumerate(reversed(places)):
            links = links_of(
                [n.model_dump() for n in graph.nodes], [e.model_dump() for e in graph.edges]
            )
            successors = links[node_id].successors if node_id in links else []
            if index == 0:
                next_links = successors
            else:
                afterwards.append(successors)
    return ExecutionPosition(
        execution=state,
        at=at,
        next=next_links,
        afterwards=afterwards,
        path=path,
        truncated=len(visits) > len(shown),
    )


__all__ = [
    "MAX_PATH_VISITS",
    "connection_of",
    "display_name",
    "graph_neighbours",
    "links_of",
    "port_label",
    "position_of",
]
