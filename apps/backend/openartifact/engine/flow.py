"""The flow of one execution: its frozen graphs and the path it took through them.

Only the nodes of action definitions are recorded as steps (trigger, timers, Code, HTTP, output). The
path through the pipelines (stages, actions without a definition, called pipelines, the edges between
them) is therefore *replayed* here from the frozen snapshot with the same rules as the engine's walk:
start at the entry the execution started at, take the action's On Pass or On Error edge by what its
steps say, and hand each run through an action definition the next group of steps. A group starts at
a ``trigger`` step. Where the steps run out the replay stops; the open end is ``running`` while the
execution runs. An action without a definition passes at once and leaves no step, so it is on the
path only if the replay reaches it.

Snapshots frozen before the flow existed lack ids, names, sizes and edge ids; they are filled in
here (see ``_graph``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise
from typing import Any, Literal

from openartifact.engine.chain import edge_from, pipeline_chain
from openartifact.engine.flow_schemas import (
    EnteredVia,
    ExecutionFlow,
    FlowEdge,
    FlowGraph,
    FlowNode,
    FlowReached,
    FlowStepRead,
    FlowVisit,
    TraversedEdge,
)
from openartifact.engine.schemas import ExecutionRead, ExecutionStepRead
from openartifact.graph.node_types import Ports, node_type
from openartifact.models import NodeKind, RunStatus

#: Same bound as the engine's: a pipeline that loops for ever fails there, the replay stops here.
MAX_ACTIONS = 1000

Outcome = Literal["pass", "fail", "running"] | None
Raw = dict[str, Any]


def _edge_id(edge: Raw) -> str:
    return str(
        edge.get("id")
        or f"{edge['source_id']}:{edge['source_port']}>{edge['target_id']}:{edge['target_port']}"
    )


def _default_size(kind: str) -> tuple[float | None, float | None]:
    try:
        size = node_type(kind).size
    except (KeyError, ValueError):
        return None, None
    return size if size else (None, None)


def _normal_graph(graph_id: str, kind: str, name: str, raw: Raw) -> Raw:
    """A snapshot graph with every field the editor's shape needs, defaults for older snapshots."""
    edges = [
        {
            "style": "curved",
            "source_slot": 0,
            "target_slot": 0,
            **e,
            "id": _edge_id(e),
        }
        for e in raw.get("edges", [])
    ]
    nodes = []
    for n in raw.get("nodes", []):
        label = n.get("label") or n.get("name") or ""
        width, height = _default_size(n.get("kind", ""))
        fail = n.get("fail_enabled")
        if fail is None:  # old snapshot: an output offers On Fail if something is connected to it
            fail = any(e["target_id"] == n["id"] and e["target_port"] == Ports.FAIL for e in edges)
        nodes.append(
            {
                "stage_id": None,
                "name": label,
                "label": label,
                "definition_id": None,
                "seconds": None,
                "config": {},
                "x": 0.0,
                "y": 0.0,
                **n,
                "width": n.get("width") or width,
                "height": n.get("height") or height,
                "fail_enabled": bool(fail),
            }
        )
    return {"id": graph_id, "kind": kind, "name": name, "nodes": nodes, "edges": edges}


def _graphs(snapshot: Raw, root_id: str) -> dict[str, Raw]:
    """Every graph of the snapshot, normalised, by id; names fall back to the label of a node linking to it."""
    raws = {
        root_id: ("pipeline", snapshot),
        **{i: ("pipeline", g) for i, g in snapshot.get("pipelines", {}).items()},
        **{i: ("action", g) for i, g in snapshot.get("definitions", {}).items()},
    }
    called: dict[str, str] = {}
    for _, raw in raws.values():
        for n in raw.get("nodes", []):
            if n.get("definition_id"):
                called.setdefault(n["definition_id"], n.get("label") or "")
    fallback = {"pipeline": "Pipeline", "action": "Action"}
    graphs = {
        i: _normal_graph(i, kind, raw.get("name") or called.get(i) or fallback[kind], raw)
        for i, (kind, raw) in raws.items()
    }
    for graph in graphs.values():
        for n in graph["nodes"]:
            target = graphs.get(n["definition_id"] or "")
            n["definition_name"] = n["label"] if target else None
            outputs = [m for m in target["nodes"] if m["kind"] == NodeKind.OUTPUT] if target else []
            n["definition_fail_enabled"] = (
                outputs[0]["fail_enabled"] if outputs and n["kind"] == NodeKind.ACTION else None
            )
    return graphs


@dataclass
class _Visit:
    graph_id: str
    level: int
    parent: int | None
    via: EnteredVia | None
    nodes: list[str] = field(default_factory=list)
    edges: list[Raw] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    outcome: Outcome = None
    left_port: Literal["pass", "error"] | None = None
    steps: list[ExecutionStepRead] = field(default_factory=list)

    def add_edge(self, edge: Raw | None) -> None:
        if edge is not None and all(e["id"] != edge["id"] for e in self.edges):
            self.edges.append(edge)


def _groups(steps: list[ExecutionStepRead]) -> list[list[ExecutionStepRead]]:
    """The steps cut at every trigger: one group per run through an action definition."""
    groups: list[list[ExecutionStepRead]] = []
    for step in steps:
        if step.kind == NodeKind.TRIGGER or not groups:
            groups.append([])
        groups[-1].append(step)
    return groups


class _Replay:
    def __init__(
        self,
        graphs: dict[str, Raw],
        root_id: str,
        steps: list[ExecutionStepRead],
        status: RunStatus,
        start: tuple[str | None, str | None],
    ) -> None:
        self.graphs, self.root_id, self.status = graphs, root_id, status
        self.groups = _groups(steps)
        self.cursor = 0
        self.visits: list[_Visit] = []
        self.start = start

    def _open_outcome(self) -> Outcome:
        """The outcome of a visit the steps do not finish."""
        if self.status == RunStatus.RUNNING:
            return "running"
        return "fail" if self.status == RunStatus.FAILED else None

    def run(self) -> None:
        root = self.graphs[self.root_id]
        chain = pipeline_chain(root["nodes"], root["edges"])
        stage_id, action_id = self.start
        start = next((i for i, e in enumerate(chain) if e["id"] == stage_id), 0)
        result = self._pipeline(root, chain, start, action_id, 0, None, None)
        visit = self.visits[0]
        if result == "fail":
            visit.outcome = "fail"
        elif result == "done" and self.status == RunStatus.DONE:
            visit.outcome = "pass"
        else:
            visit.outcome = self._open_outcome()

    def _pipeline(
        self,
        graph: Raw,
        chain: list[Raw],
        start: int,
        action_id: str | None,
        level: int,
        parent: int | None,
        via: EnteredVia | None,
    ) -> Literal["done", "fail", "stop"]:
        """Replay the entries of a pipeline from ``start``; ``stop`` is: the steps end in or before it."""
        visit = _Visit(graph["id"], level, parent, via)
        index = len(self.visits)
        self.visits.append(visit)
        edges, nodes = graph["edges"], {n["id"]: n for n in graph["nodes"]}
        for entry in chain[:start]:
            visit.skipped += [entry["id"], *(a["id"] for a in entry["actions"])]
        trigger = next((n for n in graph["nodes"] if n["kind"] == NodeKind.TRIGGER), None)
        previous: tuple[str, str] | None = None
        if start == 0 and trigger:
            visit.nodes.append(trigger["id"])
            previous = (trigger["id"], Ports.OUT)
        result: Literal["done", "fail", "stop"] = "done"
        for entry in chain[start:]:
            if previous:
                visit.add_edge(edge_from(edges, *previous))
            visit.nodes.append(entry["id"])
            if entry["kind"] == NodeKind.PIPELINE:
                called = self.graphs.get(entry["pipeline_id"] or "")
                if called is None:
                    result = "stop"
                    break
                inner = pipeline_chain(called["nodes"], called["edges"])
                sub = self._pipeline(
                    called,
                    inner,
                    0,
                    None,
                    level + 1,
                    index,
                    EnteredVia(graph_id=graph["id"], node_id=entry["id"]),
                )
                if sub != "done":
                    result = sub
                    break
                previous = (entry["id"], Ports.OUT)
            else:
                first, action_id = action_id or entry["first_action_id"], None
                result = self._actions(visit, graph, nodes, entry, first, level, index)
                if result != "done":
                    break
                previous = (entry["id"], Ports.END)
        else:
            end = edge_from(edges, *previous) if previous else None
            if end and nodes.get(end["target_id"], {}).get("kind") == NodeKind.COMPLETE:
                visit.add_edge(end)
                visit.nodes.append(end["target_id"])
        if level > 0:
            visit.outcome = (
                "pass" if result == "done" else "fail" if result == "fail" else self._open_outcome()
            )
        return result

    def _actions(
        self,
        visit: _Visit,
        graph: Raw,
        nodes: dict[str, Raw],
        stage: Raw,
        first: str | None,
        level: int,
        index: int,
    ) -> Literal["done", "fail", "stop"]:
        """The actions of a stage from ``first`` on along On Pass / On Error, like the engine does."""
        edges = graph["edges"]
        start = edge_from(edges, stage["id"], Ports.START)
        if first and start and start["target_id"] == first:
            visit.add_edge(start)
        action = first
        for _ in range(MAX_ACTIONS):
            if action is None:
                return "done"
            node = nodes[action]
            visit.nodes.append(action)
            if node["definition_id"]:
                run = self._take(action, node["definition_id"])
                if run is None:
                    if self.status == RunStatus.RUNNING and self.cursor >= len(self.groups):
                        self._definition(graph, node, [], level + 1, index)
                    return "stop"
                passed = self._definition(graph, node, run, level + 1, index)
                if passed is None:
                    return "stop"
            else:
                passed = True
            edge = edge_from(edges, action, Ports.PASS if passed else Ports.ERROR)
            if edge is None:
                return "fail"
            visit.add_edge(edge)
            target = nodes[edge["target_id"]]
            action = target["id"] if target["kind"] == NodeKind.ACTION else None
        return "stop"

    def _take(self, action_id: str, definition_id: str) -> list[ExecutionStepRead] | None:
        if self.cursor >= len(self.groups):
            return None
        group = self.groups[self.cursor]
        if group[0].action_id != action_id or group[0].definition_id != definition_id:
            return None
        self.cursor += 1
        return group

    def _definition(
        self, graph: Raw, action: Raw, group: list[ExecutionStepRead], level: int, parent: int
    ) -> bool | None:
        """Add the visit of one run through an action definition; True/False: it passed/failed,
        None: it did not come to its end."""
        definition = self.graphs[action["definition_id"]]
        visit = _Visit(
            definition["id"],
            level,
            parent,
            EnteredVia(graph_id=graph["id"], node_id=action["id"]),
            steps=group,
        )
        self.visits.append(visit)
        edges = definition["edges"]
        for step, following in pairwise(group):
            edge = edge_from(edges, step.node_id, step.port or "")
            if edge and edge["target_id"] == following.node_id:
                visit.add_edge(edge)
        visit.nodes = [s.node_id for s in group]
        if not group:
            visit.outcome = "running"
            return None
        last = group[-1]
        passed: bool | None
        if last.kind == NodeKind.OUTPUT:
            passed = last.outcome == "pass"
        else:
            onward = edge_from(edges, last.node_id, last.port or "")
            passed = False if onward is None else None  # no edge: the action ended in a dead end
            if onward is not None and self.status == RunStatus.RUNNING:
                visit.add_edge(onward)  # it is in the node the edge leads to
                visit.nodes.append(onward["target_id"])
        if passed is None:
            visit.outcome = self._open_outcome()
        else:
            visit.outcome = "pass" if passed else "fail"
            visit.left_port = "pass" if passed else "error"
        return passed


def build_flow(
    execution: ExecutionRead,
    snapshot_json: str,
    steps: list[ExecutionStepRead],
    outputs: bool,
    start: tuple[str | None, str | None],
) -> ExecutionFlow:
    """The flow of an execution from its snapshot, its steps and where it started (stage id, action id)."""
    try:
        snapshot: Raw = json.loads(snapshot_json)
    except ValueError:
        snapshot = {}
    snapshot.setdefault("nodes", [])
    root_id = snapshot.get("id") or execution.pipeline_id or "root"
    snapshot.setdefault("name", execution.pipeline_name)
    graphs = _graphs(snapshot, root_id)
    replay = _Replay(graphs, root_id, steps, execution.status, start)
    replay.run()
    visits = _finish(replay.visits, execution)
    reached: dict[str, FlowReached] = {}
    for visit in visits:
        entry = reached.setdefault(visit.graph_id, FlowReached(nodes=[], edges=[]))
        entry.nodes += [n for n in dict.fromkeys(visit.nodes) if n not in entry.nodes]
        entry.edges += [e.id for e in visit.edges if e.id not in entry.edges]
    return ExecutionFlow(
        execution=execution,
        root_graph_id=root_id,
        graphs={
            i: FlowGraph(
                id=i,
                kind=g["kind"],
                name=g["name"],
                nodes=[FlowNode.model_validate(n) for n in g["nodes"]],
                edges=[FlowEdge.model_validate(e) for e in g["edges"]],
            )
            for i, g in graphs.items()
        },
        steps=[
            FlowStepRead(
                **{**s.model_dump(), "output": s.output if outputs else ""},
                output_length=len(s.output),
                output_included=outputs,
            )
            for s in steps
        ],
        visits=visits,
        reached=reached,
    )


def _finish(replayed: list[_Visit], execution: ExecutionRead) -> list[FlowVisit]:
    """The visits as models; a pipeline visit spans the steps of everything entered from it."""
    spans: list[list[ExecutionStepRead]] = [list(v.steps) for v in replayed]
    for i in range(len(replayed) - 1, 0, -1):
        parent = replayed[i].parent
        if parent is not None:
            spans[parent] += spans[i]
    out = []
    for i, v in enumerate(replayed):
        steps = spans[i]
        started: datetime | None = min((s.started_at for s in steps), default=None)
        finished: datetime | None = max((s.finished_at for s in steps), default=None)
        if i == 0:
            started, finished = execution.started_at, execution.finished_at
        out.append(
            FlowVisit(
                index=i,
                parent=v.parent,
                graph_id=v.graph_id,
                level=v.level,
                entered_via=v.via,
                nodes=v.nodes,
                edges=[TraversedEdge.model_validate(e) for e in v.edges],
                skipped_nodes=v.skipped,
                outcome=v.outcome,
                left_port=v.left_port,
                first_seq=min((s.seq for s in steps), default=None),
                last_seq=max((s.seq for s in steps), default=None),
                started_at=started,
                finished_at=finished,
            )
        )
    return out
