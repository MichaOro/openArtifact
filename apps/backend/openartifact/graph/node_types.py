"""The kinds of nodes, as classes: one place that says what a node is and what it may do.

Settings are values the user sets on a node in the inspector. The older ones (``seconds``,
``fail_enabled``) are columns of the node; every newer one lives in the node's ``config`` JSON
object (see :class:`Setting.stored_in`), so a new kind needs no new column.

A :class:`NodeType` describes a kind of node: where it may be used (a pipeline or an action
definition), whether it comes with the graph and stays (``fixed``) or is added through the "+"
menu (``addable``), its ports, its settings and what it links to. ``connect_error`` holds its
connection rules. The base class has the common behaviour; a kind overrides only what differs.
Every kind is registered through :func:`register`, the same way an extension would add one later
(see ADR-014). The editor loads these descriptions (``GET /api/node-types``) and draws from them.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from openartifact.models import GraphKind, NodeKind
from openartifact.secret_refs import (
    SecretReferenceError,
    check_url_references,
    names_in,
    parse_name_lines,
)

if TYPE_CHECKING:
    from openartifact.graph.rules import Endpoint

PIPELINE = GraphKind.PIPELINE
ACTION_DEFINITION = GraphKind.ACTION
#: A timer pauses for one second to one day.
TIMER_MIN_SECONDS = 1
TIMER_MAX_SECONDS = 86400
#: Whether the "+" menu of the browser editor offers the Code and HTTP nodes.
EXECUTION_NODES_ADDABLE = True
CODE_MAX_CHARS = 20000
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
SETTING_TYPES = ("integer", "switch", "text", "lines", "code", "select")
_DEFAULT_MAX_LENGTH = {"text": 2000, "lines": 20000, "code": CODE_MAX_CHARS}


class SettingError(ValueError):
    """A value does not fit the setting it is meant for (the message never repeats the value)."""


def parse_status_spec(spec: str) -> list[tuple[int, int]]:
    """``"200-299, 404"`` as ranges ``[(200, 299), (404, 404)]``; raises :class:`SettingError`."""
    ranges = []
    for part in spec.split(","):
        match = re.fullmatch(r"\s*(\d{3})\s*(?:-\s*(\d{3})\s*)?", part)
        if not match:
            raise SettingError("Use status codes or ranges such as '200-299, 404'")
        low = int(match[1])
        high = int(match[2] or low)
        if not (100 <= low <= high <= 599):
            raise SettingError("Status codes are 100 to 599, a range goes upwards")
        ranges.append((low, high))
    return ranges


def _check_status(value: str) -> None:
    parse_status_spec(value)


def _references(check: Callable[[str], None]) -> Callable[[str], None]:
    """``check`` as a setting rule: a malformed secret reference is a :class:`SettingError`."""

    def rule(value: str) -> None:
        try:
            check(value)
        except SecretReferenceError as error:
            raise SettingError(str(error)) from error

    return rule


def _check_url(value: str) -> None:
    check_url_references(value)


def _check_text_references(value: str) -> None:
    names_in(value)


def _check_secret_names(value: str) -> None:
    parse_name_lines(value)


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
    """A value the user sets on a node in the inspector.

    ``type``: ``integer`` and ``switch`` as before; ``text`` (one line), ``lines`` (several lines),
    ``code`` (several lines, source code) and ``select`` (one of ``options``) are new. Integers
    are bound by ``minimum``/``maximum``, texts by ``max_length``. ``stored_in`` says where the
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
    max_length: int | None = None
    placeholder: str | None = None
    help: str | None = None
    stored_in: str = "column"
    check: Callable[[str], None] | None = None

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
        if self.type in _DEFAULT_MAX_LENGTH:
            data["max_length"] = self.max_length or _DEFAULT_MAX_LENGTH[self.type]
        if self.placeholder is not None:
            data["placeholder"] = self.placeholder
        if self.help is not None:
            data["help"] = self.help
        return data

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
        if self.type == "switch":
            if not isinstance(value, bool):
                raise SettingError(f"'{self.key}' must be true or false")
            return value
        if not isinstance(value, str):
            raise SettingError(f"'{self.key}' must be text")
        if self.type == "select":
            if value not in (self.options or ()):
                raise SettingError(f"'{self.key}' must be one of: {', '.join(self.options or ())}")
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
            "fixed": self.fixed,
            "addable": self.addable,
            "chain": self.chain,
            "ending": self.ending,
            "inputs": [{"name": p.name, "label": p.label} for p in self.inputs],
            "outputs": [{"name": p.name, "label": p.label} for p in self.outputs],
            "settings": [s.describe() for s in self.settings],
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


class _ExecutionType(NodeType):
    """A step of an action definition that does work and ends in On Pass or On Fail."""

    scopes = frozenset({ACTION_DEFINITION})
    addable = EXECUTION_NODES_ADDABLE
    chain = True
    inputs = (Port(Ports.IN, "Input"),)
    outputs = (Port(Ports.PASS, "On Pass"), Port(Ports.FAIL, "On Fail"))


class CodeType(_ExecutionType):
    """Runs shell or Python text stored in the node. It runs with the rights of the application."""

    kind = NodeKind.CODE
    label = "Code"
    settings = (
        Setting(
            "language",
            "Language",
            "select",
            default="sh",
            options=("sh", "python"),
            stored_in="config",
        ),
        Setting(
            "code",
            "Code",
            "code",
            default="",
            max_length=CODE_MAX_CHARS,
            stored_in="config",
            help=(
                "Stored and shown in plain text, so no secrets in here: ${secret:NAME} is not "
                "replaced in code. List the secrets the code needs in 'Secrets' below; they come "
                "as environment variables."
            ),
        ),
        Setting(
            "secrets",
            "Secrets",
            "lines",
            default="",
            max_length=2000,
            placeholder="API_KEY",
            stored_in="config",
            help=(
                "One secret name per line (capitals, digits, underscores). Each is available to "
                "the code as an environment variable of that name, for example $API_KEY or "
                "os.environ['API_KEY']. Manage the values under Secrets; a missing secret fails "
                "the node."
            ),
            check=_references(_check_secret_names),
        ),
        Setting(
            "timeout_seconds",
            "Timeout (seconds)",
            "integer",
            minimum=1,
            maximum=600,
            default=30,
            stored_in="config",
        ),
    )


class HttpType(_ExecutionType):
    """Calls an HTTP address and passes when the status is one of the accepted ones."""

    kind = NodeKind.HTTP
    label = "HTTP request"
    settings = (
        Setting(
            "method", "Method", "select", default="GET", options=HTTP_METHODS, stored_in="config"
        ),
        Setting(
            "url",
            "URL",
            "text",
            default="",
            placeholder="https://example.org/hook",
            stored_in="config",
            help=(
                "Use ${secret:NAME} for a stored secret in the path or the query (it is "
                "percent-encoded there); not in the scheme or host."
            ),
            check=_references(_check_url),
        ),
        Setting(
            "headers",
            "Headers",
            "lines",
            default="",
            placeholder="Name: value",
            stored_in="config",
            help=(
                "One 'Name: value' per line, stored in plain text: put a secret in as "
                "${secret:NAME}, for example 'Authorization: Bearer ${secret:API_TOKEN}'."
            ),
            check=_references(_check_text_references),
        ),
        Setting(
            "body",
            "Body",
            "lines",
            default="",
            stored_in="config",
            help=(
                "Sent as it is, stored in plain text: put a secret in as ${secret:NAME}, which "
                "is replaced by its value when the node runs."
            ),
            check=_references(_check_text_references),
        ),
        Setting(
            "timeout_seconds",
            "Timeout (seconds)",
            "integer",
            minimum=1,
            maximum=120,
            default=30,
            stored_in="config",
        ),
        Setting(
            "success_status",
            "Success status",
            "text",
            default="200-299",
            max_length=100,
            stored_in="config",
            help="Comma-separated codes or ranges, for example 200-299, 404.",
            check=_check_status,
        ),
    )


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
    CodeType(),
    HttpType(),
):
    register(_type)
