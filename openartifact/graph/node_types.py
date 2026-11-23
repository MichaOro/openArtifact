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

from openartifact.agents import schemas as agent_rules
from openartifact.agents.render import MappingError, parse_mapping, prompt_problems
from openartifact.credentials.refs import (
    SecretReferenceError,
    check_url_references,
    names_in,
    parse_name_lines,
)
from openartifact.engine.context import VAR_NAME, ContextError, check_url_placement
from openartifact.engine.fields import FieldsError, parse_fields
from openartifact.models import GraphKind, NodeKind

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
MAX_DECLARED_VARIABLES = 100
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
#: Conditions of an If node and cases of a Switch node (see ``engine/branching.py``).
IF_ROWS = 5
SWITCH_CASES = 6
CONDITION_TEXT_CHARS = 500
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
    try:
        check_url_placement(value)
    except ContextError as error:
        raise SettingError(str(error)) from error


def _check_text_references(value: str) -> None:
    names_in(value)


def _check_secret_names(value: str) -> None:
    parse_name_lines(value)


def _check_variable_names(value: str) -> None:
    names = [line.strip() for line in value.splitlines() if line.strip()]
    if len(names) > MAX_DECLARED_VARIABLES:
        raise SettingError(f"At most {MAX_DECLARED_VARIABLES} variables")
    for name in names:
        if not VAR_NAME.fullmatch(name):
            raise SettingError(
                "One variable name per line: lowercase letters, digits and underscores, "
                "starting with a letter"
            )


def _check_condition_text(value: str) -> None:
    """A condition reads the run context only: a secret in it could be leaked by branching on it."""
    if "${secret" in value:
        raise SettingError(
            "${secret:NAME} cannot be used in a condition: a branch could reveal the secret"
        )
    _check_text_references(value)


def _check_agent_inputs(value: str) -> None:
    """The input mapping of an agent node: ``name = value`` per line, no secret as a source."""
    try:
        parse_mapping(value)
    except MappingError as error:
        raise SettingError(str(error)) from error
    _check_text_references(value)


def _check_agent_prompt(value: str) -> None:
    """A prompt a node sets for itself follows the agent's rule: only ``${input.NAME}``."""
    for problem in prompt_problems(value, None, "Prompt"):
        raise SettingError(problem)


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


@dataclass(frozen=True)
class Port:
    """A connector of a node."""

    name: str
    label: str


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
        if self.group is not None:
            data["group"] = self.group
        if self.references is not None:
            data["references"] = self.references
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
    #: Config settings whose text may hold ``${node...}`` / ``${var...}`` (checked for hints on save).
    reference_keys: ClassVar[tuple[str, ...]] = ()

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


#: Shared by the execution nodes: what a failure of the node does to the way on.
ON_FAILURE = Setting(
    "on_failure",
    "If the node fails",
    "select",
    default="fail",
    options=("fail", "continue"),
    stored_in="config",
    help=(
        "fail (the default): leave by On Fail, the action fails if nothing is connected there. "
        "continue: leave by On Pass although the node failed (fail open); the step still shows "
        "the failure and its reason."
    ),
)


class _ExecutionType(NodeType):
    """A step of an action definition that does work and ends in On Pass or On Fail."""

    scopes = frozenset({ACTION_DEFINITION})
    addable = EXECUTION_NODES_ADDABLE
    chain = True
    inputs = (Port(Ports.IN, "Input"),)
    outputs: ClassVar[tuple[Port, ...]] = (Port(Ports.PASS, "On Pass"), Port(Ports.FAIL, "On Fail"))


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
                "replaced in code, and neither are ${node...} or ${var...}. List the secrets the "
                "code needs in 'Secrets' below; they come as environment variables. The run "
                "context (variables and earlier results) is the file context.json in the working "
                "directory. To set variables, print a last line like "
                '{"ok": true, "vars": {"name": "value"}}.'
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
            "sets_variables",
            "Sets variables",
            "lines",
            default="",
            max_length=2000,
            placeholder="ticket_priority",
            stored_in="config",
            help=(
                'Optional: the variable names this code sets (one per line, as in "vars"). '
                "Documents the node and feeds the suggestions; a difference between this list and "
                "what the code really sets is noted in the step, it does not fail the node."
            ),
            check=_check_variable_names,
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
        ON_FAILURE,
    )


class HttpType(_ExecutionType):
    """Calls an HTTP address and passes when the status is one of the accepted ones."""

    kind = NodeKind.HTTP
    label = "HTTP request"
    reference_keys = ("url", "headers", "body")
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
            references="all",
            help=(
                "Use ${secret:NAME} for a stored secret and ${node.NAME.output} or ${var.NAME} for "
                "the result of an earlier node or a variable in the path or the query (replaced "
                "text is percent-encoded there); not in the scheme or host."
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
            references="all",
            help=(
                "One 'Name: value' per line, stored in plain text: put a secret in as "
                "${secret:NAME}, for example 'Authorization: Bearer ${secret:API_TOKEN}'. "
                "${node.NAME.output} and ${var.NAME} insert an earlier result or variable."
            ),
            check=_references(_check_text_references),
        ),
        Setting(
            "body",
            "Body",
            "lines",
            default="",
            stored_in="config",
            references="all",
            help=(
                "Sent as it is, stored in plain text: put a secret in as ${secret:NAME}, which "
                "is replaced by its value when the node runs. ${node.NAME.output}, "
                "${node.NAME.data.key} and ${var.NAME} insert an earlier node's result or a "
                "variable (NAME: the node's name with spaces as _)."
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
        ON_FAILURE,
    )


def _if_settings() -> tuple[Setting, ...]:
    rows: list[Setting] = []
    for n in range(1, IF_ROWS + 1):
        group = f"Condition {n}"
        rows += [
            Setting(
                f"left_{n}",
                "Value",
                "text",
                default="",
                max_length=CONDITION_TEXT_CHARS,
                placeholder="${var.priority}" if n == 1 else None,
                stored_in="config",
                group=group,
                references="context",
                help="Text, may hold ${node.NAME.output} or ${var.name}. Empty: the row is unused."
                if n == 1
                else None,
                check=_check_condition_text,
            ),
            Setting(
                f"operator_{n}",
                "Operator",
                "select",
                default="equals",
                options=OPERATORS,
                stored_in="config",
                group=group,
            ),
            Setting(
                f"right_{n}",
                "Compare with",
                "text",
                default="",
                max_length=CONDITION_TEXT_CHARS,
                stored_in="config",
                group=group,
                references="context",
                help="Ignored by is empty, is not empty, is true and is false." if n == 1 else None,
                check=_check_condition_text,
            ),
        ]
    return (
        Setting(
            "combine",
            "Conditions",
            "select",
            default="all",
            options=("all", "any"),
            stored_in="config",
            help="all: every used condition must hold (and). any: one is enough (or).",
        ),
        Setting(
            "case_sensitive",
            "Case sensitive",
            "switch",
            default=True,
            stored_in="config",
            help="Off: texts are compared without regard to upper and lower case.",
        ),
        *rows,
    )


class IfType(_ExecutionType):
    """Compares values of the run context and leaves by Yes, No or Else (cannot be evaluated)."""

    kind = NodeKind.IF
    label = "If"
    outputs = (Port(Ports.YES, "Yes"), Port(Ports.NO, "No"), Port(Ports.ELSE, "Else"))
    settings = _if_settings()
    reference_keys = tuple(
        f"{side}_{n}" for n in range(1, IF_ROWS + 1) for side in ("left", "right")
    )


def switch_case_used(config: dict[str, Any] | None, port: str) -> bool:
    """Whether a case of a Switch is in use: it has a value, or an operator that needs none (``is empty``
    ...). An unused case has no output: the editor hides it and the rules refuse a connection from it."""
    config = config or {}
    number = port.removeprefix("case_")
    operator = str(config.get(f"case_operator_{number}") or "equals")
    value = config.get(port)
    return operator in UNARY_OPERATORS or (isinstance(value, str) and bool(value.strip()))


def _switch_case(n: int) -> tuple[Setting, Setting]:
    group = f"Case {n}"
    return (
        Setting(
            f"case_operator_{n}",
            "Operator",
            "select",
            default="equals",
            options=OPERATORS,
            stored_in="config",
            group=group,
        ),
        Setting(
            Ports.case(n),
            "Compare with",
            "text",
            default="",
            max_length=CONDITION_TEXT_CHARS,
            stored_in="config",
            group=group,
            references="context",
            help=(
                "Text, may hold ${node.NAME.output} or ${var.name}. Empty (and an operator that needs a "
                "value): the case is unused and its output is hidden."
            )
            if n == 1
            else None,
            check=_check_condition_text,
        ),
    )


class SwitchType(_ExecutionType):
    """Compares one value with up to six cases, each with its own operator, and leaves by the first case that
    holds, or Else. A case without an operator compares with ``equals`` (Switches of before ADR-039)."""

    kind = NodeKind.SWITCH
    label = "Switch"
    outputs = (
        *(Port(Ports.case(n), f"Case {n}") for n in range(1, SWITCH_CASES + 1)),
        Port(Ports.ELSE, "Else"),
    )
    settings = (
        Setting(
            "value",
            "Value",
            "text",
            default="",
            max_length=CONDITION_TEXT_CHARS,
            placeholder="${var.priority}",
            stored_in="config",
            references="context",
            help="Text, may hold ${node.NAME.output} or ${var.name}.",
            check=_check_condition_text,
        ),
        *(setting for n in range(1, SWITCH_CASES + 1) for setting in _switch_case(n)),
        Setting(
            "case_sensitive",
            "Case sensitive",
            "switch",
            default=True,
            stored_in="config",
            help="Off: texts are compared without regard to upper and lower case.",
        ),
    )
    reference_keys = ("value", *(Ports.case(n) for n in range(1, SWITCH_CASES + 1)))

    def connect_error(
        self, source: Endpoint, source_port: str, target: Endpoint, target_port: str
    ) -> str | None:
        if source_port.startswith("case_") and not switch_case_used(source.config, source_port):
            return f"{source_port.replace('_', ' ').capitalize()} is unused: give it a value first"
        return super().connect_error(source, source_port, target, target_port)


def _check_fields(value: str) -> None:
    """The fields of an Edit Fields node: ``name = value`` per line, variable names, no secret."""
    try:
        parse_fields(value)
    except FieldsError as error:
        raise SettingError(str(error)) from error


class SetType(_ExecutionType):
    """Edit Fields: sets variables of the run (``${var.NAME}``) from text and references, without code.

    One ``name = value`` per line; the value may hold ``${node...}``, ``${var...}`` and ``${card...}``. With
    ``value_types`` ``detect`` a value that is a JSON number, ``true``, ``false``, ``null``, an object or a
    list is stored as that, otherwise as text (see ``engine/fields.py``).
    """

    kind = NodeKind.SET
    label = "Edit Fields"
    settings = (
        Setting(
            "fields",
            "Fields",
            "lines",
            default="",
            max_length=20000,
            placeholder="priority = ${node.Classify.output}",
            stored_in="config",
            references="context",
            help=(
                "One 'name = value' per line. Each sets the variable ${var.name} for the nodes after this "
                "one (names: lowercase letters, digits and underscores). A value may hold "
                "${node.NAME.output}, ${node.NAME.data.key}, ${var.name} or ${card.name}; secrets cannot be "
                "used, a variable is plain data."
            ),
            check=_check_fields,
        ),
        Setting(
            "value_types",
            "Value types",
            "select",
            default="text",
            options=("text", "detect"),
            stored_in="config",
            help=(
                "text: every value is stored as text. detect: a value that is a number, true, false, null, "
                "a JSON object or a JSON list is stored as that."
            ),
        ),
        ON_FAILURE,
    )
    reference_keys = ("fields",)


def _override(key: str, label: str, type_: str, **more: Any) -> Setting:
    """A setting of an agent node that overrides the agent's: not set (``None``) means inherited."""
    return Setting(key, label, type_, default=None, stored_in="config", **more)


class AgentType(_ExecutionType):
    """Runs a centrally defined agent: one request to a model, the answer is the node's output.

    The node holds a reference to the agent (``agent_id``), the mapping of the agent's inputs to the
    run context (``inputs``) and overrides. Every override setting has no default: a value that is not
    set is inherited from the agent's published version when an execution starts
    (``agents/resolve.py``), a value that is set replaces that one field, and saving ``null`` resets
    it. The bounds are the agent's own (``agents/schemas.py``).
    """

    kind = NodeKind.AGENT
    label = "Agent"
    settings = (
        Setting(
            "agent_id",
            "Agent",
            "text",
            default="",
            max_length=36,
            stored_in="config",
            help="The agent this node runs (managed under Agents).",
        ),
        Setting(
            "inputs",
            "Inputs",
            "lines",
            default="",
            max_length=20000,
            placeholder="ticket = ${node.Fetch_ticket.output}",
            stored_in="config",
            references="context",
            help=(
                "One 'name = value' per line for the inputs the agent declares. The value is text "
                "and may hold ${node.NAME.output}, ${node.NAME.data.key}, ${var.name} or "
                "${card.name}; secrets cannot be used."
            ),
            check=_references(_check_agent_inputs),
        ),
        _override("system_prompt_enabled", "Use a system prompt", "switch"),
        _override(
            "system_prompt",
            "System prompt",
            "lines",
            max_length=agent_rules.PROMPT_MAX_CHARS,
            check=_check_agent_prompt,
        ),
        _override(
            "user_prompt",
            "User prompt",
            "lines",
            max_length=agent_rules.PROMPT_MAX_CHARS,
            check=_check_agent_prompt,
        ),
        _override("provider_id", "Provider", "text", max_length=36),
        _override("model", "Model", "text", max_length=agent_rules.MODEL_ID_MAX),
        _override(
            "temperature",
            "Temperature",
            "number",
            minimum=agent_rules.TEMPERATURE_MIN,
            maximum=agent_rules.TEMPERATURE_MAX,
        ),
        _override(
            "max_tokens",
            "Max tokens",
            "integer",
            minimum=agent_rules.MAX_TOKENS_MIN,
            maximum=agent_rules.MAX_TOKENS_MAX,
        ),
        _override(
            "request_timeout_seconds",
            "Request timeout (seconds)",
            "integer",
            minimum=agent_rules.REQUEST_TIMEOUT_MIN,
            maximum=agent_rules.REQUEST_TIMEOUT_MAX,
        ),
        _override(
            "total_timeout_seconds",
            "Time limit of the node (seconds)",
            "integer",
            minimum=agent_rules.TOTAL_TIMEOUT_MIN,
            maximum=agent_rules.TOTAL_TIMEOUT_MAX,
        ),
        _override(
            "retries",
            "Retries",
            "integer",
            minimum=agent_rules.RETRIES_MIN,
            maximum=agent_rules.RETRIES_MAX,
        ),
        ON_FAILURE,
    )
    reference_keys = ("inputs",)


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
    IfType(),
    SwitchType(),
    AgentType(),
    SetType(),
):
    register(_type)
