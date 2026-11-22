"""The run context: variables and the results of the nodes that ran, and the references that read them.

Every execution has a context (``executions.context``, JSON text). The engine adds the result of every
node that ran, and a Code node may set variables with its result protocol (``"vars": {...}``). Later nodes
read both through references in their settings::

    ${node.NAME.output}  ${node.NAME.exit_code}  ${node.NAME.outcome}  ${node.NAME.reason}
    ${node.NAME.data}    ${node.NAME.data.key.sub.0}    ${var.name}    ${card.name}

``${card.NAME}`` is a parameter of the artifact the run belongs to (see ``artifact_types``). The run gets a
copy of the artifact's parameters when it starts, so changing the artifact later does not change a run
that exists: every parameter of the artifact's type is a key (``null`` when it has no value), an artifact
without a type has none.

``NAME`` is the node's name as the editor shows it, with every character outside ``A-Z a-z 0-9 _ -``
replaced by ``_`` (so ``Fetch user`` is ``Fetch_user``). References are replaced literally by text: a value
is never evaluated and never scanned for references again (a response that contains ``${var.x}`` or
``${secret:X}`` stays that text). Secret references (``${secret:NAME}``, see ``credentials.refs``) are replaced in
the same single pass. Anything that cannot be resolved raises :class:`ContextError` with a reason that names
the reference: nothing is ever replaced by an empty string.

Names are not unique. A reference resolves to the node of the frozen pipeline that has that name; two
different nodes with the same name make the reference fail ("ambiguous node name"). A node that ran
several times keeps its latest result.

Shape of the context::

    {"vars": {"name": value},
     "card": {"name": value},
     "nodes": {"Key": {"name", "kind", "outcome", "port", "exit_code", "output", "reason", "data",
                       "at", "truncated"?}}}

Limits: a node keeps at most ``NODE_OUTPUT_LIMIT_BYTES`` of output here (the whole output stays in the
steps of the execution); the whole context at most ``CONTEXT_LIMIT_BYTES``, and the variables alone
``VARS_LIMIT_BYTES``. When the context grows too large the oldest node results lose their output, then
their data, then are dropped; variables are never dropped, a write that does not fit fails instead.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from openartifact.credentials.refs import in_scheme_or_host

if TYPE_CHECKING:
    from openartifact.engine.results import NodeResult

NODE_OUTPUT_LIMIT_BYTES = 4096
CONTEXT_LIMIT_BYTES = 64 * 1024
VARS_LIMIT_BYTES = 32 * 1024
MAX_VARS = 100
MAX_DEPTH = 3
TRUNCATED_MARK = "[output truncated]"
REMOVED_OUTPUT = "[output removed: the context is limited]"
#: Kinds of nodes that have no result of their own (no key in the context, no reference to them).
_NO_RESULT = frozenset({"trigger", "output", "stage", "action", "complete", "pipeline"})

VAR_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_NODE_REFERENCE = re.compile(
    r"node\.(?P<key>[A-Za-z0-9_-]{1,255})\.(?P<field>output|exit_code|outcome|reason|data)"
    r"(?P<path>(?:\.[A-Za-z0-9_-]{1,64}){0,8})"
)
_VAR_REFERENCE = re.compile(r"var\.(?P<name>[a-z][a-z0-9_]{0,63})")
_CARD_REFERENCE = re.compile(r"card\.(?P<name>[a-z][a-z0-9_]{0,31})")
#: What looks like a context reference; :func:`parse` then decides strictly whether it is one.
CANDIDATE = re.compile(r"\$\{((?:node|var|card)\.[^}\r\n]{0,400})\}")
#: One pass over a text for both kinds of references (so that no replaced value is scanned again).
_ANY = re.compile(r"\$\{(?:secret:([^}\r\n]{0,80})|((?:node|var|card)\.[^}\r\n]{0,400}))\}")
_FIELDS = "output, exit_code, outcome, reason, data"
SYNTAX_HINT = (
    "use ${node.NAME.output}, ${node.NAME.exit_code}, ${node.NAME.outcome}, ${node.NAME.reason}, "
    "${node.NAME.data.key}, ${var.name} or ${card.name}"
)


class ContextError(ValueError):
    """A reference or a value cannot be used (the message names it; it never repeats a stored value)."""


# ── names ────────────────────────────────────────────────────────────


def node_key(name: str) -> str:
    """The key of a node in the context: its name with everything outside ``A-Za-z0-9_-`` as ``_``."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", name.strip())[:255] or "_"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _size(value: Any) -> int:
    return len(_json(value).encode("utf-8"))


def _render(value: Any) -> str:
    """Text as it is, everything else as compact JSON."""
    return value if isinstance(value, str) else _json(value)


# ── variables ────────────────────────────────────────────────────────


def _check_value(value: Any, depth: int) -> None:
    if value is None or isinstance(value, bool | int | str):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContextError("a number must be finite")
        return
    if isinstance(value, list | dict):
        if depth >= MAX_DEPTH:
            raise ContextError(f"lists and objects may be nested at most {MAX_DEPTH} levels")
        items = value.values() if isinstance(value, dict) else value
        if isinstance(value, dict) and not all(isinstance(k, str) for k in value):
            raise ContextError("object keys must be text")
        for item in items:
            _check_value(item, depth + 1)
        return
    raise ContextError("a value must be text, a number, true, false, null, a list or an object")


def check_vars(raw: Any) -> dict[str, Any]:
    """The variables a node reports, checked: names ``[a-z][a-z0-9_]{0,63}``, JSON values.

    Raises :class:`ContextError` with the reason (the first problem found).
    """
    if not isinstance(raw, dict):
        raise ContextError("'vars' must be an object of name: value")
    if len(raw) > MAX_VARS:
        raise ContextError(f"at most {MAX_VARS} variables per node")
    for name, value in raw.items():
        if not isinstance(name, str) or not VAR_NAME.fullmatch(name):
            shown = str(name)[:40]
            raise ContextError(
                f"variable name '{shown}' is not valid: lowercase letters, digits and underscores, "
                "starting with a letter, at most 64 characters"
            )
        try:
            _check_value(value, 0)
        except ContextError as error:
            raise ContextError(f"variable '{name}': {error}") from error
    return raw


# ── the context ──────────────────────────────────────────────────────


def _cap_output(text: str) -> tuple[str, bool]:
    raw = text.encode("utf-8")
    if len(raw) <= NODE_OUTPUT_LIMIT_BYTES:
        return text, False
    kept = raw[:NODE_OUTPUT_LIMIT_BYTES].decode("utf-8", errors="ignore")
    return f"{kept}\n{TRUNCATED_MARK}", True


class RunContext:
    """The variables and node results of one execution; ``dumps`` is what is stored."""

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        data = data or {}
        raw_vars, raw_nodes, raw_card = data.get("vars"), data.get("nodes"), data.get("card")
        self.vars: dict[str, Any] = dict(raw_vars) if isinstance(raw_vars, dict) else {}
        self.card: dict[str, Any] = dict(raw_card) if isinstance(raw_card, dict) else {}
        self.nodes: dict[str, dict[str, Any]] = (
            {k: dict(v) for k, v in raw_nodes.items() if isinstance(v, dict)}
            if isinstance(raw_nodes, dict)
            else {}
        )

    @classmethod
    def initial(cls, card: Mapping[str, Any]) -> RunContext:
        """The context a run starts with: the artifact's parameters as ``card``, nothing else."""
        return cls({"card": dict(card)})

    @classmethod
    def loads(cls, text: str | None) -> RunContext:
        """The context of a stored text; anything that is not a context object is an empty one."""
        try:
            data = json.loads(text or "{}")
        except ValueError:
            data = None
        return cls(data if isinstance(data, dict) else None)

    def to_data(self) -> dict[str, Any]:
        return {"vars": self.vars, "card": self.card, "nodes": self.nodes}

    def dumps(self) -> str:
        return _json(self.to_data())

    def set_vars(self, new: Mapping[str, Any]) -> None:
        """Merge variables (checked by :func:`check_vars`); nothing changes if they do not fit."""
        merged = {**self.vars, **new}
        if _size(merged) > VARS_LIMIT_BYTES:
            raise ContextError(
                f"the variables would exceed the limit of {VARS_LIMIT_BYTES // 1024} KiB"
            )
        self.vars = merged

    def record(self, node: Mapping[str, Any], result: NodeResult, port: str | None) -> None:
        """Store the result of a node that ran under its key; an earlier result of the key is replaced."""
        output, cut = _cap_output(result.output)
        entry: dict[str, Any] = {
            "name": node["name"],
            "kind": str(node["kind"]),
            "outcome": result.outcome,
            "port": port,
            "exit_code": result.exit_code,
            "output": output,
            "reason": result.reason,
            "data": result.data,
            "at": _now(),
        }
        if cut:
            entry["truncated"] = True
        key = node_key(str(node["name"]))
        self.nodes.pop(key, None)  # the order of the keys is the order of recency
        self.nodes[key] = entry
        self._fit()

    def _fit(self) -> None:
        """Make the context fit its limit: the oldest results lose output, then data, then go."""
        if _size(self.to_data()) <= CONTEXT_LIMIT_BYTES:
            return
        older = list(self.nodes)[:-1]
        for step in ("output", "data", "node"):
            for key in older:
                if key not in self.nodes:
                    continue
                if step == "node":
                    del self.nodes[key]
                elif step == "output":
                    self.nodes[key]["output"] = REMOVED_OUTPUT
                    self.nodes[key]["truncated"] = True
                else:
                    self.nodes[key]["data"] = None
                if _size(self.to_data()) <= CONTEXT_LIMIT_BYTES:
                    return


# ── the nodes of a frozen pipeline ───────────────────────────────────


@dataclass(frozen=True)
class NodeDefinition:
    """A node of an action definition that can have a result: who it is, for the error texts."""

    node_id: str
    name: str
    kind: str
    where: str

    def describe(self) -> str:
        return f'"{self.name}" ({self.kind}) in action "{self.where}"'


@dataclass(frozen=True)
class NodeIndex:
    """The nodes of a frozen pipeline by key, to tell which node a name stands for."""

    by_key: dict[str, list[NodeDefinition]] = field(default_factory=dict)

    @classmethod
    def of_graphs(cls, graphs: Iterable[Mapping[str, Any]]) -> NodeIndex:
        """The result-bearing nodes of action definitions (``{"name", "nodes"}`` graphs)."""
        by_key: dict[str, list[NodeDefinition]] = {}
        for graph in graphs:
            for node in graph["nodes"]:
                if str(node["kind"]) in _NO_RESULT:
                    continue
                found = NodeDefinition(
                    node["id"], node["name"], str(node["kind"]), str(graph.get("name", ""))
                )
                by_key.setdefault(node_key(node["name"]), []).append(found)
        return cls(by_key)

    @classmethod
    def of_snapshot(cls, snapshot: Mapping[str, Any]) -> NodeIndex:
        return cls.of_graphs(snapshot.get("definitions", {}).values())

    def lookup(self, key: str) -> NodeDefinition:
        """The one node with this key; :class:`ContextError` if there is none or more than one."""
        found = {d.node_id: d for d in self.by_key.get(key, [])}
        if not found:
            raise ContextError(f'no node is named "{key}"')
        if len(found) > 1:
            listed = " and ".join(d.describe() for d in found.values())
            raise ContextError(f'ambiguous node name "{key}": {listed}; rename one of them')
        return next(iter(found.values()))


# ── references ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Reference:
    """A parsed ``${node...}``, ``${var...}`` or ``${card...}``: ``kind`` is ``node``, ``var`` or ``card``."""

    kind: str
    name: str  # the node key or the variable name
    field: str = ""
    path: tuple[str, ...] = ()


def parse(body: str) -> Reference:
    """The reference that ``body`` (the text inside ``${...}``) spells; :class:`ContextError` if malformed."""
    if match := _VAR_REFERENCE.fullmatch(body):
        return Reference("var", match["name"])
    if match := _CARD_REFERENCE.fullmatch(body):
        return Reference("card", match["name"])
    match = _NODE_REFERENCE.fullmatch(body)
    if match is None or (match["path"] and match["field"] != "data"):
        raise ContextError(f"malformed reference ${{{body[:80]}}}: {SYNTAX_HINT}")
    path = tuple(match["path"].split(".")[1:]) if match["path"] else ()
    return Reference("node", match["key"], match["field"], path)


def references_in(text: str) -> list[tuple[str, Reference | None, str]]:
    """Every context reference candidate of ``text`` as ``(text, parsed or None, problem)``."""
    found: list[tuple[str, Reference | None, str]] = []
    for match in CANDIDATE.finditer(text):
        try:
            found.append((match[0], parse(match[1]), ""))
        except ContextError as error:
            found.append((match[0], None, str(error)))
    return found


def _walk(value: Any, path: tuple[str, ...], where: str) -> Any:
    for segment in path:
        if isinstance(value, dict) and segment in value:
            value = value[segment]
        elif isinstance(value, list) and segment.isdigit() and int(segment) < len(value):
            value = value[int(segment)]
        else:
            raise ContextError(f"{where} has no '{segment}'")
    return value


def resolve(ref: Reference, context: RunContext, index: NodeIndex) -> Any:
    """The value a reference stands for; :class:`ContextError` if it cannot be resolved."""
    if ref.kind == "var":
        if ref.name not in context.vars:
            raise ContextError(f"variable '{ref.name}' is not set")
        return context.vars[ref.name]
    if ref.kind == "card":
        if ref.name not in context.card:
            raise ContextError(f'the artifact has no parameter "{ref.name}"')
        return context.card[ref.name]
    index.lookup(ref.name)  # unknown or ambiguous names fail even if something ran under the key
    entry = context.nodes.get(ref.name)
    if entry is None:
        raise ContextError(f'node "{ref.name}" has not run yet')
    value = entry.get(ref.field)
    if ref.field != "data":
        return value
    if ref.path and value is None:
        raise ContextError(f'node "{ref.name}" has no data')
    return _walk(value, ref.path, f'the data of node "{ref.name}"')


@dataclass(frozen=True)
class RunView:
    """What a node may read of its run: the context and the nodes of the frozen pipeline."""

    context: RunContext = field(default_factory=RunContext)
    index: NodeIndex = field(default_factory=NodeIndex)

    def render(
        self,
        text: str,
        *,
        secrets: Mapping[str, str] | None = None,
        percent_encode: bool = False,
    ) -> str:
        """``text`` with its references replaced, in one pass (replaced values are not scanned again).

        Secret references whose name is not in ``secrets`` stay as they are; a context reference that
        cannot be resolved raises :class:`ContextError`. In a URL pass ``percent_encode``.
        """

        def put(match: re.Match[str]) -> str:
            if match[1] is not None:
                value = (secrets or {}).get(match[1])
                if value is None:
                    return match[0]
            else:
                try:
                    value = _render(resolve(parse(match[2]), self.context, self.index))
                except ContextError as error:
                    raise ContextError(f"{match[0]}: {error}") from error
            return quote(value, safe="") if percent_encode else value

        return _ANY.sub(put, text)

    def dumps(self) -> str:
        return self.context.dumps()


def check_url_placement(url: str) -> None:
    """A context reference is allowed in the path and the query of a URL, not in the scheme or host.

    Raises :class:`ContextError`.
    """
    if CANDIDATE.search(url) and in_scheme_or_host(url, CANDIDATE):
        raise ContextError(
            "a ${node...}, ${var...} or ${card...} reference is allowed in the path, the query, the headers "
            "and the body, not in the scheme or the host of the address"
        )


def problems(text: str, local: NodeIndex, elsewhere: Callable[[str], bool]) -> list[str]:
    """Hints about the context references of a setting, for the time it is saved (it is still saved).

    ``local`` holds the nodes of the action the setting belongs to; ``elsewhere(key)`` says whether any
    other action has a node with that key (the pipeline that runs it decides at run time). Variables
    are set while a run goes on, so only their syntax is checked.
    """
    hints = []
    for shown, ref, problem in references_in(text):
        if ref is None:
            hints.append(problem)
        elif ref.kind == "node":
            if len({d.node_id for d in local.by_key.get(ref.name, [])}) > 1:
                try:
                    local.lookup(ref.name)
                except ContextError as error:
                    hints.append(f"{shown}: {error}")
            elif ref.name not in local.by_key and not elsewhere(ref.name):
                hints.append(f'{shown}: no node is named "{ref.name}"')
    return hints
