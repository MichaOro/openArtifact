"""The kinds of nodes: one place that says what a node is and what it may do.

A kind is *declared* in a YAML manifest (``graph/nodes/<kind>.yaml``, ADR-054; format and rules in
``graph/manifest.py``) and loaded here into a :class:`NodeType`. Settings are values the user sets on a node in
its dialog; the older ones (``seconds``, ``fail_enabled``) are columns of the node, every newer one lives in the node's
``config`` JSON object (see :class:`Setting.stored_in`), so a new kind needs no new column.

A :class:`NodeType` describes a kind of node: where it may be used (a pipeline or an action definition), whether it comes
with the graph and stays (``fixed``) or is added through the "+" menu (``addable``), its ports, its settings and what it
links to. ``connect_error`` holds its connection rules; the few kinds whose rules differ are classes (``behaviour`` in the
manifest picks one), everything else is the base class. The editor loads these descriptions (``GET /api/node-types``) and
draws from them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from openartifact.graph import context_sources
from openartifact.graph.manifest import (
    NODES_DIR,
    PortSpec,
    expand_ports,
    expand_settings,
    load_shared,
    menu_groups,
    read_all,
)
from openartifact.graph.validators import (
    VALIDATORS,
    SettingError,
    parse_status_spec,
)
from openartifact.models import GraphKind, NodeKind

if TYPE_CHECKING:
    from openartifact.graph.rules import Endpoint

__all__ = [
    "IF_ROWS",
    "NODE_TYPES",
    "OPERATORS",
    "RETRY_DEFAULT_TRIES",
    "RETRY_DEFAULT_WAIT_MS",
    "RETRY_MAX_TOTAL_WAIT_MS",
    "RETRY_MAX_TRIES",
    "RETRY_MAX_WAIT_MS",
    "RETRY_MIN_TRIES",
    "SWITCH_CASES",
    "TIMER_MAX_SECONDS",
    "TIMER_MIN_SECONDS",
    "UNARY_OPERATORS",
    "NodeType",
    "Port",
    "Ports",
    "Setting",
    "SettingError",
    "fixed_in",
    "kinds_in",
    "node_type",
    "parse_status_spec",
    "register",
    "retry_error",
    "switch_case_used",
]

PIPELINE = GraphKind.PIPELINE
ACTION_DEFINITION = GraphKind.ACTION
#: A timer pauses for one second to one day (its manifest says the same; a test keeps them equal).
TIMER_MIN_SECONDS = 1
TIMER_MAX_SECONDS = 86400
#: Rows of an If node and cases of a Switch node (``engine/branching.py``); the manifests repeat their blocks this often.
IF_ROWS = 5
SWITCH_CASES = 6
OPERATORS = (
    "equals",
    "not equals",
    "contains",
    "not contains",
    "starts with",
    "ends with",
    "is empty",
    "is not empty",
    "greater than",
    "less than",
    "greater or equal",
    "less or equal",
    "is true",
    "is false",
)
#: Operators that look at the left side only (the right side is ignored).
UNARY_OPERATORS = frozenset({"is empty", "is not empty", "is true", "is false"})
_DEFAULT_MAX_LENGTH = {"text": 2000, "lines": 20000, "code": 20000}
#: *Retry on fail* (ADR-073): how many tries in all (the first one included), how long to wait between two, and how long all the waits of
#: one node may add up to. A node tries again only itself, never the run; the bounds keep a node from holding a run for hours.
RETRY_MIN_TRIES = 2
RETRY_MAX_TRIES = 10
RETRY_DEFAULT_TRIES = 3
RETRY_MAX_WAIT_MS = 10 * 60 * 1000
RETRY_DEFAULT_WAIT_MS = 1000
RETRY_MAX_TOTAL_WAIT_MS = 30 * 60 * 1000
#: The parts of a node's dialog and the ways a setting may be disclosed (``Setting.section`` / ``Setting.level``).
SECTIONS = ("definition", "behaviour")
LEVELS = ("core", "optional", "advanced")


class Ports:
    """The names of the connectors that the rules and the engine refer to."""

    IN = "in"
    OUT = "out"
    START = "start"
    END = "end"
    PASS = "pass"
    ERROR = "error"
    FAIL = "fail"
    YES = "yes"
    NO = "no"
    ELSE = "else"

    @staticmethod
    def case(number: int) -> str:
        return f"case_{number}"

    #: The attachment of tools (ADR-040): the Agent node's input and a tool node's output.
    TOOLS = "tools"
    TOOL = "tool"


class FailureMode:
    """The values of the setting *If the node fails* / *If the action fails* (``on_failure``, ADR-061)."""

    FAIL = "fail"  # stop: the failure ends the action (and, for an action, the run)
    CONTINUE = "continue"  # go on through On Pass, the error stays as data
    ERROR_OUTPUT = (
        "error_output"  # go on through the error output, which exists only with this value
    )


@dataclass(frozen=True)
class Port:
    """A connector of a node. ``side``: where the editor draws it when not on the usual side (inputs left,
    outputs right): ``bottom`` for the Tools port of an Agent node, ``top`` for the port of a tool node."""

    name: str
    label: str
    side: str | None = None
    #: When the port is there: ``{"fn": ...}``, ``{"node": field}`` or ``{"setting": key, "equals": value}``
    #: (see ``graph/manifest.py``).
    visible_when: dict[str, str] | None = None
    #: A function of the editor that labels the port from the node's settings (a Switch case by its condition).
    label_from: str | None = None

    def describe(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name, "label": self.label}
        if self.side is not None:
            data["side"] = self.side
        if self.visible_when is not None:
            data["visible_when"] = self.visible_when
        if self.label_from is not None:
            data["label_from"] = self.label_from
        return data


@dataclass(frozen=True)
class Setting:
    """A value the user sets on a node in the inspector.

    ``type``: ``integer`` and ``switch`` as before; ``text`` (one line), ``lines`` (several lines),
    ``code`` (several lines, source code), ``select`` (one of ``options``) and ``number`` (a whole or
    decimal number) are new. Numbers are bound by ``minimum``/``maximum``, texts by ``max_length``. ``stored_in`` says where the
    value lives: the node's column of the same name (``"column"``, the older settings) or its
    ``config`` object (``"config"``). ``check`` is an extra rule for a text (not sent to the editor).
    """

    key: str
    label: str
    type: str
    minimum: int | None = None
    maximum: int | None = None
    default: Any = None
    options: tuple[str, ...] | None = None
    #: The shown text of an option (the stored value stays the option); not part of equality or the hash.
    option_labels: dict[str, str] | None = field(default=None, hash=False, compare=False)
    #: Options shown greyed that cannot be chosen yet; the options of this select by the value of another setting
    #: (``{"setting": key, "map": {value: [options]}}``); the setting is only drawn while another has one of
    #: these values (``{"setting": key, "values": [...]}``); the name of the line it shares with its neighbours.
    disabled_options: tuple[str, ...] | None = None
    options_by: dict[str, Any] | None = field(default=None, hash=False, compare=False)
    shown_when: dict[str, Any] | None = field(default=None, hash=False, compare=False)
    line: str | None = None
    #: The credential types a ``credential`` setting accepts; the stored value is the name of a credential.
    credential_types: tuple[str, ...] | None = None
    max_length: int | None = None
    placeholder: str | None = None
    help: str | None = None
    stored_in: str = "column"
    check: Callable[[str], None] | None = None
    #: Settings of one group (a condition row) are shown together under this title.
    group: str | None = None
    #: What the editor may suggest while the user types ``${``: ``"context"`` (node results and
    #: variables) or ``"all"`` (and secret names). ``None``: the text takes no references.
    references: str | None = None
    #: Where the setting goes in the node's dialog (ADR-053): ``"definition"`` (what the node is, the left
    #: column) or ``"behaviour"`` (how it runs: timeouts, limits, failure handling; the right column).
    section: str = "definition"
    #: How prominent it is: ``"core"`` (always shown), ``"optional"`` (shown once it is set or added) or
    #: ``"advanced"`` (folded under *Advanced*, open while one of them is set). Not a third column.
    level: str = "core"
    #: The parent a value that is not set comes from (``"agent"``), when there really is one; ``None``: not
    #: set means the setting's own default.
    inherits: str | None = None

    def __post_init__(self) -> None:
        if self.section not in SECTIONS:
            raise ValueError(f"section of '{self.key}' must be one of: {', '.join(SECTIONS)}")
        if self.level not in LEVELS:
            raise ValueError(f"level of '{self.key}' must be one of: {', '.join(LEVELS)}")
        if self.inherits is not None and not self.inherits:
            raise ValueError(f"inherits of '{self.key}' names the parent, or is None")

    @classmethod
    def of(cls, data: dict[str, Any]) -> Setting:
        """A setting from the plain dict of a manifest (its ``check`` is the name of a rule of ``validators.py``)."""
        fields = dict(data)
        if (name := fields.pop("check", None)) is not None:
            fields["check"] = VALIDATORS[name]
        for name in ("options", "disabled_options", "credential_types"):
            if name in fields:
                fields[name] = tuple(fields[name])
        return cls(**fields)

    def describe(self) -> dict[str, Any]:
        """The editor's description; the old keys keep their meaning, new ones are only added."""
        data: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "default": self.default,
            "stored_in": self.stored_in,
        }
        if self.options is not None:
            data["options"] = list(self.options)
        if self.option_labels is not None:
            data["option_labels"] = dict(self.option_labels)
        for name in ("disabled_options", "options_by", "shown_when", "line", "credential_types"):
            if (value := getattr(self, name)) is not None:
                data[name] = list(value) if isinstance(value, tuple) else value
        if self.type == "retry":
            data["limits"] = {
                "max_tries": [RETRY_MIN_TRIES, RETRY_MAX_TRIES, RETRY_DEFAULT_TRIES],
                "wait_ms": [0, RETRY_MAX_WAIT_MS, RETRY_DEFAULT_WAIT_MS],
                "total_wait_ms": RETRY_MAX_TOTAL_WAIT_MS,
            }
        if self.type == "sources":
            data.update(context_sources.describe())
        if self.type in _DEFAULT_MAX_LENGTH:
            data["max_length"] = self.max_length or _DEFAULT_MAX_LENGTH[self.type]
        if self.placeholder is not None:
            data["placeholder"] = self.placeholder
        if self.help is not None:
            data["help"] = self.help
        if self.group is not None:
            data["group"] = self.group
        if self.references is not None:
            data["references"] = self.references
        data["section"] = self.section
        data["level"] = self.level
        data["inherits"] = self.inherits
        return data

    def _retry(self, value: Any) -> dict[str, Any]:
        problem = retry_error(value)
        if problem:
            raise SettingError(problem)
        return {
            "enabled": value.get("enabled", True),
            "max_tries": value.get("max_tries", RETRY_DEFAULT_TRIES),
            "wait_ms": value.get("wait_ms", RETRY_DEFAULT_WAIT_MS),
        }

    def validate(self, value: Any) -> Any:
        """The value as it is stored, or :class:`SettingError`."""
        if self.type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise SettingError(f"'{self.key}' must be a whole number")
            if (self.minimum is not None and value < self.minimum) or (
                self.maximum is not None and value > self.maximum
            ):
                raise SettingError(f"'{self.key}' must be {self.minimum} to {self.maximum}")
            return value
        if self.type == "number":
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise SettingError(f"'{self.key}' must be a number")
            if (self.minimum is not None and value < self.minimum) or (
                self.maximum is not None and value > self.maximum
            ):
                raise SettingError(f"'{self.key}' must be {self.minimum} to {self.maximum}")
            return value
        if self.type == "switch":
            if not isinstance(value, bool):
                raise SettingError(f"'{self.key}' must be true or false")
            return value
        if self.type == "retry":
            return self._retry(value)
        if self.type == "sources":
            try:
                return context_sources.normalise(value)
            except ValueError as error:
                raise SettingError(str(error)) from error
        if self.type == "size":
            low, high = self.minimum or 0, self.maximum
            if not _whole(value) or value < low or (high is not None and value > high):
                span = (
                    f"{_bytes_text(low)} to {_bytes_text(high)}"
                    if high
                    else f"at least {_bytes_text(low)}"
                )
                raise SettingError(f"{self.label} must be a whole number of bytes, {span}")
            return value
        if not isinstance(value, str):
            raise SettingError(f"'{self.key}' must be text")
        if self.type == "select":
            if value not in (self.options or ()):
                raise SettingError(f"'{self.key}' must be one of: {', '.join(self.options or ())}")
            if value in (self.disabled_options or ()):
                raise SettingError(f"'{self.key}': '{value}' is not available yet")
            return value
        if "\x00" in value:
            raise SettingError(f"'{self.key}' must not contain NUL characters")
        if len(value) > (self.max_length or _DEFAULT_MAX_LENGTH.get(self.type, 2000)):
            raise SettingError(f"'{self.key}' is too long")
        if self.type == "text" and ("\n" in value or "\r" in value):
            raise SettingError(f"'{self.key}' is a single line")
        if self.check is not None:
            self.check(value)
        return value


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _bytes_text(value: int) -> str:
    """A size in words for a message: ``1 KiB``, ``64 MiB``, ``1500 bytes``."""
    for unit, factor in (("MiB", 1024**2), ("KiB", 1024)):
        if value >= factor and value % factor == 0:
            return f"{value // factor} {unit}"
    return f"{value} bytes"


def retry_error(value: Any) -> str | None:
    """Why ``value`` is no *Retry on fail* setting (``None``: it is one): ``{"enabled", "max_tries", "wait_ms"}``, in plain words."""
    if not isinstance(value, dict):
        return "Retry on fail must be an object with enabled, max_tries and wait_ms"
    unknown = sorted(set(value) - {"enabled", "max_tries", "wait_ms"})
    if unknown:
        return f"Retry on fail has no '{unknown[0][:40]}': use enabled, max_tries and wait_ms"
    if not isinstance(value.get("enabled", True), bool):
        return "Retry on fail: enabled must be true or false"
    tries, wait = (
        value.get("max_tries", RETRY_DEFAULT_TRIES),
        value.get("wait_ms", RETRY_DEFAULT_WAIT_MS),
    )
    if not _whole(tries) or not RETRY_MIN_TRIES <= tries <= RETRY_MAX_TRIES:
        return f"Max. tries must be a whole number from {RETRY_MIN_TRIES} to {RETRY_MAX_TRIES} (the first try counts)"
    if not _whole(wait) or not 0 <= wait <= RETRY_MAX_WAIT_MS:
        return f"The wait between tries must be from 0 to {RETRY_MAX_WAIT_MS // 60000} minutes"
    if (tries - 1) * wait > RETRY_MAX_TOTAL_WAIT_MS:
        return (
            f"{tries} tries with {wait} ms between them wait {(tries - 1) * wait // 60000} minutes in all, "
            f"more than the {RETRY_MAX_TOTAL_WAIT_MS // 60000} minutes allowed: use fewer tries or a shorter wait"
        )
    return None


class NodeType:
    """What every kind of node has. Built from a manifest; the subclasses below only differ in ``connect_error``."""

    def __init__(
        self,
        *,
        kind: NodeKind,
        label: str,
        behaviour: str = "plain",
        scopes: frozenset[GraphKind] = frozenset({PIPELINE}),
        purposes: frozenset[str] = frozenset({"pipeline", "guard"}),
        requires: str | None = None,
        fixed: bool = False,
        addable: bool = False,
        chain: bool = False,
        ending: bool = False,
        inputs: tuple[Port, ...] = (),
        outputs: tuple[Port, ...] = (),
        settings: tuple[Setting, ...] = (),
        links_to: GraphKind | None = None,
        size: tuple[float, float] | None = None,
        tool: bool = False,
        guardable: bool = False,
        produces_result: bool = False,
        timed: bool = False,
        result_data: tuple[str, ...] = (),
        variables: dict[str, str] | None = None,
        reference_keys: tuple[str, ...] = (),
        menu: dict[str, Any] | None = None,
        menu_icon: str | None = None,
        ui: dict[str, Any] | None = None,
    ) -> None:
        self.kind = kind
        self.label = label
        self.behaviour = behaviour
        self.guardable = guardable  # a guard may watch a node of this kind in an action (ADR-060)
        self.produces_result = (
            produces_result  # leaves output/data for later nodes (the reference suggestions)
        )
        self.timed = timed  # the flow panel shows how long a step took
        self.result_data = result_data  # keys of `data` it always leaves
        self.variables = variables  # the setting it sets run variables from
        self.scopes = scopes
        #: The kinds of action definition it may be used in (``pipeline`` and/or ``guard``, ADR-067) and the right it needs
        #: (a hook for planned per-person rights, not evaluated yet).
        self.purposes = purposes
        self.requires = requires
        self.fixed = fixed  # comes with the graph, cannot be added or deleted
        self.addable = addable  # offered in the "+" menu
        self.chain = chain  # a step of the main line (new ones are placed after these)
        self.ending = ending  # the end of the main line (moves on to make room)
        self.inputs = inputs
        self.outputs = outputs
        self.settings = settings
        self.links_to = links_to  # the kind of graphs row ``definition_id`` points at
        self.size = size  # only stages store a size of their own
        #: A tool node: no flow ports, attached to the Tools port of an Agent node, run only when the agent calls it.
        self.tool = tool
        #: Config settings whose text may hold ``${node...}`` / ``${var...}`` (checked for hints on save).
        self.reference_keys = reference_keys
        self.menu = menu
        self.menu_icon = menu_icon  # the glyph of the kind in the menus that list it
        self.ui = ui or {}

    @property
    def default_name(self) -> str:
        return self.label

    def input_names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.inputs)

    def output_names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.outputs)

    def port_hidden(self, config: dict[str, Any] | None, name: str) -> bool:
        """Whether the port is not there for a node with this config: its ``visible_when`` names a setting that does not
        have the value (an unset one counts as its default). Other kinds of ``visible_when`` are the editor's business."""
        port = next((p for p in (*self.inputs, *self.outputs) if p.name == name), None)
        when = port.visible_when if port else None
        if not when or "setting" not in when:
            return False
        setting = next((s for s in self.settings if s.key == when["setting"]), None)
        if setting is None:
            return False
        value = (config or {}).get(setting.key, setting.default)
        return bool(value != when["equals"])

    @property
    def config_settings(self) -> tuple[Setting, ...]:
        """The settings kept in the node's ``config`` object."""
        return tuple(s for s in self.settings if s.stored_in == "config")

    def effective_config(self, stored: dict[str, Any] | None) -> dict[str, Any]:
        """The kind's config settings: what is stored, the defaults for the rest."""
        stored = stored or {}
        return {s.key: stored.get(s.key, s.default) for s in self.config_settings}

    def merge_config(
        self, stored: dict[str, Any] | None, changes: dict[str, Any]
    ) -> dict[str, Any]:
        """``stored`` with ``changes`` validated and merged per key (``None`` resets a key).

        Raises :class:`SettingError` for an unknown key or a value that does not fit.
        """
        known = {s.key: s for s in self.config_settings}
        merged = dict(stored or {})
        for key, value in changes.items():
            if key not in known:
                raise SettingError(f"A {self.kind.value} has no setting '{key}'")
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = known[key].validate(value)
        return merged

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
            "purposes": sorted(self.purposes),
            "requires": self.requires,
            "fixed": self.fixed,
            "addable": self.addable,
            "chain": self.chain,
            "ending": self.ending,
            "inputs": [p.describe() for p in self.inputs],
            "outputs": [p.describe() for p in self.outputs],
            "tool": self.tool,
            "guardable": self.guardable,
            "produces_result": self.produces_result,
            "timed": self.timed,
            "result_data": list(self.result_data),
            "variables": self.variables,
            "settings": [s.describe() for s in self.settings],
            "links_to": self.links_to.value if self.links_to else None,
            "behaviour": self.behaviour,
            "menu": self.menu,
            "menu_icon": self.menu_icon,
            "ui": self.ui,
        }


class StageType(NodeType):
    """A container of actions. ``start`` and ``end`` each serve both sides: ``start`` receives from
    before and feeds the first action, ``end`` receives from the actions and leads on."""

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


def switch_case_used(config: dict[str, Any] | None, port: str) -> bool:
    """Whether a case of a Switch is in use: it has a value, or an operator that needs none (``is empty``
    ...). An unused case has no output: the editor hides it and the rules refuse a connection from it."""
    config = config or {}
    number = port.removeprefix("case_")
    operator = str(config.get(f"case_operator_{number}") or "equals")
    value = config.get(port)
    return operator in UNARY_OPERATORS or (isinstance(value, str) and bool(value.strip()))


class SwitchType(NodeType):
    """Compares one value with up to six cases and leaves by the first that holds, or Else; an unused case has no output."""

    def connect_error(
        self, source: Endpoint, source_port: str, target: Endpoint, target_port: str
    ) -> str | None:
        if source_port.startswith("case_") and not switch_case_used(source.config, source_port):
            return f"{source_port.replace('_', ' ').capitalize()} is unused: give it a value first"
        return super().connect_error(source, source_port, target, target_port)


class ToolType(NodeType):
    """A tool of an agent (ADR-040): attached from below to the Tools port of an Agent node and run only when
    the model calls it. It has no flow ports, so the engine never walks it."""

    def connect_error(
        self, source: Endpoint, source_port: str, target: Endpoint, target_port: str
    ) -> str | None:
        if target.kind is not NodeKind.AGENT or target_port != Ports.TOOLS:
            return "A tool attaches to the Tools port of an Agent node"
        return None


#: What a manifest's ``behaviour`` means on the server: how the kind connects. The rest is the base class.
BEHAVIOURS: dict[str, type[NodeType]] = {
    "plain": NodeType,
    "flow": NodeType,
    "pipeline": NodeType,
    "output": NodeType,
    "stage": StageType,
    "action": ActionType,
    "switch": SwitchType,
    "tool": ToolType,
}

NODE_TYPES: dict[NodeKind, NodeType] = {}


def register(node_type: NodeType) -> NodeType:
    """Make a kind of node known (the built-in kinds are loaded from their manifests the same way)."""
    NODE_TYPES[node_type.kind] = node_type
    return node_type


def node_type(kind: NodeKind | str) -> NodeType:
    return NODE_TYPES[NodeKind(kind)]


def step_icon(kind: str) -> str | None:
    """The glyph of a step of this kind in the history: the manifest's ``ui.step_icon``, else the card's icon, else its menu glyph.

    A kind the application does not know (a step of an older version) has none, and the history shows its plain glyph."""
    try:
        view = node_type(kind)
    except ValueError:
        return None
    ui = view.ui or {}
    return ui.get("step_icon") or ui.get("icon") or view.menu_icon


def kinds_in(scope: GraphKind, purpose: str | None = None) -> set[NodeKind]:
    """The kinds a pipeline (``pipeline``) or an action definition (``action``) may contain; for an action definition of a
    ``purpose`` (``pipeline`` or ``guard``, ADR-067) only the kinds that may be used there."""
    return {
        t.kind
        for t in NODE_TYPES.values()
        if scope in t.scopes
        and (purpose is None or scope != GraphKind.ACTION or purpose in t.purposes)
    }


def fixed_in(scope: GraphKind) -> list[NodeType]:
    """The kinds that come with a new graph of that scope, in order (start first)."""
    return [t for t in NODE_TYPES.values() if scope in t.scopes and t.fixed]


def _port(spec: PortSpec) -> Port:
    return Port(
        spec.name,
        spec.label,
        spec.side,
        spec.visible_when.model_dump(exclude_none=True) if spec.visible_when else None,
        spec.label_from,
    )


def load(directory: Any = NODES_DIR) -> list[NodeType]:
    """Read the manifests of a directory and register what they declare (the built-in kinds at import)."""
    shared = load_shared(directory)
    groups = menu_groups(directory)
    loaded = []
    for manifest in read_all(directory):
        settings = tuple(Setting.of(data) for data in expand_settings(manifest.settings, shared))
        menu = None
        if manifest.menu is not None:
            name = manifest.menu.group
            if name not in groups:
                groups.append(name)
            menu = {"group": name, "group_index": groups.index(name), "order": manifest.menu.order}
        ui = manifest.ui.model_dump(exclude_none=True)
        node = BEHAVIOURS[manifest.behaviour](
            kind=NodeKind(manifest.kind),
            label=manifest.label,
            behaviour=manifest.behaviour,
            scopes=frozenset(GraphKind(s) for s in manifest.scopes),
            purposes=frozenset(manifest.purposes),
            requires=manifest.requires,
            fixed=manifest.fixed,
            addable=manifest.addable,
            chain=manifest.chain,
            ending=manifest.ending,
            inputs=tuple(_port(p) for p in expand_ports(manifest.ports.inputs)),
            outputs=tuple(_port(p) for p in expand_ports(manifest.ports.outputs)),
            settings=settings,
            links_to=GraphKind(manifest.links_to) if manifest.links_to else None,
            size=(float(manifest.default_size.width), float(manifest.default_size.height))
            if manifest.default_size
            else None,
            tool=manifest.tool,
            guardable=manifest.guardable,
            produces_result=manifest.produces_result,
            timed=manifest.timed,
            result_data=tuple(manifest.result_data),
            variables=manifest.variables.model_dump() if manifest.variables else None,
            reference_keys=tuple(manifest.reference_keys),
            menu=menu,
            menu_icon=manifest.menu_icon or manifest.ui.icon,
            ui=ui,
        )
        loaded.append(register(node))
    return loaded


load()
