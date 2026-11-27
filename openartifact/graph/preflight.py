"""The check before a graph is published (ADR-082): does everything it refers to exist?

It reads the **draft** of an action or a pipeline as data and runs nothing. For every setting of every node it looks at each ``${...}``:
a node by its id or its name, a card field, a secret, an input of the graph itself, a variable; and at the inputs a node maps and the
outputs a node declares. What it finds is a list of **findings**, each an *error* (something that cannot work: the reference names a node
that is not there, a secret that does not exist, a required input without a value) or a *warning* (something that may work: the node is
not in front of this one on every path, the variable is only set by a script, the node belongs to another action).

Only what is published runs, so a draft may be wrong; the check is asked for when someone publishes (the browser asks for it first and
shows the findings; the API refuses to publish over findings unless the caller acknowledges them), never when a draft is saved. It does
not need a run, so a dry run can ask the same question.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.artifact_fields.service import field_specs
from openartifact.engine.context import (
    BUILT_IN_CARD,
    NO_RESULT_KINDS,
    PLACEMENT_KINDS,
    Reference,
    node_key,
    references_in,
)
from openartifact.engine.fields import FieldsError, parse_fields
from openartifact.graph.content import graph_of
from openartifact.graph.contract import consumer_findings
from openartifact.graph.observe import describe, of_content
from openartifact.graph.observe_state import published_setting
from openartifact.graph.publishing import graph_for_run
from openartifact.models import Graph, NodeKind, Secret

Level = Literal["error", "warning"]

_SECRET = re.compile(r"\$\{secret:([^}\r\n]{1,80})\}")
#: Kinds that can set variables in ways the check cannot read (a script, an agent).
_UNREADABLE_SETTERS = {"code"}


@dataclass(frozen=True)
class Finding:
    """One thing the check found; ``node_id`` and ``node_name`` say where (the name is what the editor shows), ``code`` is stable."""

    level: Level
    code: str
    node_id: str | None
    node_name: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "node_id": self.node_id,
            "node_name": self.node_name,
            "message": self.message,
        }


def _strings(value: Any) -> Iterator[str]:
    """Every text in a setting value, however deep (a mapping value, an output value, a prompt)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _strings(item)


def _label(node: Mapping[str, Any]) -> str:
    return str(node.get("label") or node.get("name") or "")


def _ancestors(start: str, edges: list[Mapping[str, Any]]) -> set[str]:
    """The nodes from which ``start`` can be reached along the connections."""
    incoming: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        incoming[str(edge["target_id"])].append(str(edge["source_id"]))
    seen: set[str] = set()
    queue = deque([start])
    while queue:
        for before in incoming.get(queue.popleft(), []):
            if before not in seen:
                seen.add(before)
                queue.append(before)
    return seen


def _declared(graph: Mapping[str, Any] | None, kind: str, key: str) -> list[dict[str, Any]]:
    if graph is None:
        return []
    for node in graph["nodes"]:
        if node["kind"] == kind:
            value = (node.get("config") or {}).get(key)
            return [dict(f) for f in value] if isinstance(value, list) else []
    return []


def _variables_set(nodes: list[Mapping[str, Any]]) -> set[str] | None:
    """The variables the Edit Fields nodes of a graph set; ``None`` when a script or another node may set more (the check cannot tell)."""
    names: set[str] = set()
    for node in nodes:
        if node["kind"] in _UNREADABLE_SETTERS:
            return None
        if node["kind"] == "set":
            try:
                names |= set(parse_fields(str((node.get("config") or {}).get("fields") or "")))
            except FieldsError:
                continue
    return names


class _Checker:
    def __init__(
        self,
        graph: Mapping[str, Any],
        definitions: Mapping[str, Mapping[str, Any]],
        card_fields: set[str],
        secrets: set[str],
        elsewhere_names: set[str],
    ) -> None:
        self.graph = graph
        self.nodes: list[Mapping[str, Any]] = list(graph["nodes"])
        self.edges: list[Mapping[str, Any]] = list(graph["edges"])
        self.by_id = {str(n["id"]): n for n in self.nodes}
        self.definitions = definitions
        self.card_fields = card_fields
        self.secrets = secrets
        self.elsewhere_names = elsewhere_names
        self.inputs = {f["name"] for f in _declared(graph, NodeKind.TRIGGER, "inputs")}
        self.variables = _variables_set(self.nodes) if graph["kind"] == "action" else None
        self.by_key: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for node in self.nodes:
            if node["kind"] not in NO_RESULT_KINDS or node["kind"] in PLACEMENT_KINDS:
                self.by_key[node_key(str(node["name"]))].append(node)
        self.findings: list[Finding] = []

    def add(self, level: Level, code: str, node: Mapping[str, Any], message: str) -> None:
        item = Finding(level, code, str(node["id"]), _label(node), message)
        if item not in self.findings:
            self.findings.append(item)

    # ── what a node's settings refer to ──────────────────────────────

    def check_node(self, node: Mapping[str, Any]) -> None:
        before = _ancestors(str(node["id"]), self.edges)
        for text in _strings(node.get("config") or {}):
            for name in _SECRET.findall(text):
                if name not in self.secrets:
                    self.add("error", "secret_missing", node, f"the secret '{name}' does not exist")
            for shown, ref, problem in references_in(text):
                if ref is None:
                    self.add("error", "reference_malformed", node, f"{shown}: {problem}")
                else:
                    self.check_reference(node, shown, ref, before)

    def check_reference(
        self, node: Mapping[str, Any], shown: str, ref: Reference, before: set[str]
    ) -> None:
        if ref.kind == "card":
            if ref.name not in BUILT_IN_CARD and ref.name not in self.card_fields:
                self.add(
                    "error",
                    "card_field_missing",
                    node,
                    f"{shown}: the artifact has no field '{ref.name}'",
                )
        elif ref.kind == "input":
            if ref.name not in self.inputs:
                listed = ", ".join(sorted(self.inputs)) or "none"
                self.add(
                    "error",
                    "input_missing",
                    node,
                    f"{shown}: this {self.graph['kind']} declares no input '{ref.name}' (its inputs: {listed}); declare it on the Trigger",
                )
        elif ref.kind == "var":
            if self.variables is not None and ref.name not in self.variables:
                self.add(
                    "warning",
                    "variable_unknown",
                    node,
                    f"{shown}: no Edit Fields node of this action sets '{ref.name}'; it must be set before this node runs",
                )
        elif ref.node_id:
            self.check_node_by_id(node, shown, ref, before)
        else:
            self.check_node_by_name(node, shown, ref)

    def check_node_by_id(
        self, node: Mapping[str, Any], shown: str, ref: Reference, before: set[str]
    ) -> None:
        target = self.by_id.get(ref.node_id)
        if target is None:
            self.add(
                "error",
                "node_missing",
                node,
                f"{shown}: it refers to a node that does not exist any more (deleted, or in another {self.graph['kind']})",
            )
            return
        name = _label(target)
        if ref.node_id not in before and ref.node_id != str(node["id"]):
            self.add(
                "warning",
                "node_not_before",
                node,
                f"{shown}: '{name}' is not in front of this node on every path, so it may not have run yet",
            )
        if target["kind"] in PLACEMENT_KINDS:
            self.check_placement_output(node, shown, ref, target)
        elif target["kind"] in NO_RESULT_KINDS:
            self.add("error", "node_no_result", node, f"{shown}: '{name}' leaves no result to read")

    def check_placement_output(
        self, node: Mapping[str, Any], shown: str, ref: Reference, target: Mapping[str, Any]
    ) -> None:
        name = _label(target)
        definition = self.definitions.get(str(target.get("definition_id") or ""))
        ends = NodeKind.COMPLETE if target["kind"] == "pipeline" else NodeKind.OUTPUT
        outputs = _declared(definition, ends, "outputs")
        inputs = _declared(definition, NodeKind.TRIGGER, "inputs")
        if not outputs and not inputs:
            self.add(
                "error",
                "placement_no_contract",
                node,
                f"{shown}: '{name}' declares no inputs or outputs, so it leaves no result of its own; declare outputs on its Output node",
            )
        elif ref.field == "data" and ref.path and outputs:
            declared = {o["name"] for o in outputs}
            if ref.path[0] not in declared:
                self.add(
                    "error",
                    "output_missing",
                    node,
                    f"{shown}: '{name}' has no output '{ref.path[0]}' (its outputs: {', '.join(sorted(declared))})",
                )
        elif ref.field == "data" and ref.path and not outputs:
            self.add(
                "error",
                "output_missing",
                node,
                f"{shown}: '{name}' declares no outputs, so it has no data '{ref.path[0]}'",
            )

    def check_node_by_name(self, node: Mapping[str, Any], shown: str, ref: Reference) -> None:
        found = self.by_key.get(ref.name, [])
        if len(found) > 1:
            self.add(
                "error",
                "name_ambiguous",
                node,
                f"{shown}: {len(found)} nodes are called '{ref.name}'; refer to the one you mean by its id (pick it in the list)",
            )
        elif not found:
            if ref.name in self.elsewhere_names:
                self.add(
                    "warning",
                    "node_elsewhere",
                    node,
                    f"{shown}: '{ref.name}' belongs to another action; it works only when that action ran before in the same run",
                )
            else:
                self.add("error", "node_missing", node, f"{shown}: no node is named '{ref.name}'")

    # ── the inputs a node maps ────────────────────────────────────────

    def check_mapping(self, node: Mapping[str, Any]) -> None:
        if node["kind"] not in PLACEMENT_KINDS or not node.get("definition_id"):
            return
        definition = self.definitions.get(str(node["definition_id"]))
        declared = _declared(definition, NodeKind.TRIGGER, "inputs")
        mapped = (node.get("config") or {}).get("input_values") or {}
        name = _label(node)
        for spec in declared:
            given = str(mapped.get(spec["name"]) or "").strip()
            has_default = bool(str(spec.get("default") or "").strip())
            if spec["required"] and not given and not has_default:
                self.add(
                    "error",
                    "input_not_given",
                    node,
                    f"'{name}' needs the input '{spec['name']}' (required) and it has no value here; give it one on this node",
                )
        known = {s["name"] for s in declared}
        for given_name in mapped:
            if given_name not in known:
                self.add(
                    "warning",
                    "input_unknown",
                    node,
                    f"'{name}' gives a value to '{given_name}', which the {node['kind']} does not declare",
                )


async def _observe_findings(
    session: AsyncSession, graph_id: str, content: dict[str, Any]
) -> list[Finding]:
    """A change of the observe mode goes live with the publication (ADR-088): said as a warning the owner confirms."""
    graph = await session.get(Graph, graph_id)
    if graph is None or graph.kind != "pipeline":
        return []
    draft = of_content(content)
    now = await published_setting(session, graph)
    if draft == now:
        return []
    if draft is not None and now is None:
        text = (
            f"Observe mode will be switched on with this publication ({describe(draft)}): from then on every run of this pipeline, "
            "from any start, is a dry run that changes nothing"
        )
        code = "observe_on"
    elif draft is None:
        text = "Observe mode will be switched off with this publication: the pipeline runs for real again"
        code = "observe_off"
    else:
        text = f"Observe mode will change with this publication (from {describe(now)} to {describe(draft)}) and its observation starts again"
        code = "observe_changed"
    return [Finding("warning", code, None, content["name"], text)]


async def check(session: AsyncSession, graph_id: str) -> list[Finding]:
    """The findings for the draft of the graph ``graph_id`` (an action or a pipeline), errors first. Reads only."""
    content = await graph_of(session, graph_id, mocks=True)
    definition_ids = {
        str(n["definition_id"])
        for n in content["nodes"]
        if n.get("definition_id") and n["kind"] in (NodeKind.ACTION, NodeKind.PIPELINE)
    }
    # what a placement is checked against is the contract of the version that RUNS (published, else the draft: graph/contract.py), not the
    # draft of the action that may be half edited
    definitions = {i: await graph_for_run(session, i) for i in sorted(definition_ids)}
    fields = {spec.name for spec in await field_specs(session)}
    secrets = set(await session.scalars(select(Secret.name)))
    others = (await session.execute(select(Graph.id, Graph.kind).where(Graph.id != graph_id))).all()
    elsewhere: set[str] = set()
    for other_id, other_kind in others:
        if other_kind != "action":
            continue
        other = await graph_of(session, other_id)
        elsewhere |= {
            node_key(str(n["name"])) for n in other["nodes"] if n["kind"] not in NO_RESULT_KINDS
        }
    checker = _Checker(content, definitions, fields, secrets, elsewhere)
    for node in content["nodes"]:
        checker.check_node(node)
        checker.check_mapping(node)
    found = sorted(checker.findings, key=lambda f: (f.level != "error", f.node_name, f.code))
    mocks = sum(1 for n in content["nodes"] if (n.get("mock") or {}).get("enabled"))
    if mocks:  # a mock lives in the draft only (ADR-087): the owner should know it stays behind
        found.append(
            Finding(
                "warning",
                "mocks_not_published",
                None,
                content["name"],
                f"{mocks} mock(s) are set in this draft; they are not published and a real run never uses them",
            )
        )
    found.extend(await _observe_findings(session, graph_id, content))
    # publishing this graph changes its contract for the graphs that run it: said as warnings, the owner decides
    for item in await consumer_findings(session, graph_id):
        found.append(Finding("warning", item["code"], None, item["where"], item["message"]))
    return found
