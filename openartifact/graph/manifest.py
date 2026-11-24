"""Node kinds as YAML manifests (ADR-054): one file per kind in ``graph/nodes/``, validated against the models below
(``schema: 1``) and turned into the :class:`~openartifact.graph.node_types.NodeType` the rest of the application uses.

A manifest *declares*: the kind's label, where it may be used, its ports, its settings (with their help, section, level,
group, parent and the *name* of the rule that checks them), how its card looks and where it sits in the "+" menu. It holds
no code. What needs code is chosen by name from a short list: a ``behaviour`` (how the kind connects: ``plain``, ``flow``,
``stage``, ``action``, ``pipeline``, ``output``, ``tool``, ``switch``), a ``check`` rule (``graph/validators.py``) and, for the
card, a few named functions the editor knows (:data:`CLIENT_FUNCTIONS`). A kind that only needs a title, a caption template
and some settings is a manifest and nothing else.

Two conveniences keep the files short: a setting may be ``use: name`` (a snippet of ``_shared.yaml``, with fields overridden
beside it), and a block ``{repeat: N, settings: [...]}`` (or a port with ``repeat``) is written N times, ``{n}`` standing for
the number and ``first:`` giving what only the first copy has. ``_menu.yaml`` orders the clusters of the "+" menu.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from openartifact.graph.validators import VALIDATORS

SCHEMA_VERSION = 1
NODES_DIR = Path(__file__).parent / "nodes"
BEHAVIOURS = ("plain", "flow", "stage", "action", "pipeline", "output", "tool", "switch")
#: The functions of the editor a manifest may name (``tests/js/node-types.test.mjs`` checks that every one exists there).
CLIENT_FUNCTIONS: dict[str, tuple[str, ...]] = {
    "caption": ("if_summary", "switch_summary", "agent_summary"),
    "visible": ("switch_case_used",),
    "label": ("switch_case_label",),
    "size": ("switch_size",),
    "group_used": ("switch_group_used",),
}
#: The filters of a caption template (``static/js/editor/caption.js``).
CAPTION_FILTERS = ("default", "trim", "first_line", "short", "host_path", "field_names")


class ManifestError(ValueError):
    """A manifest is not valid; the message names the file and what is wrong."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VisibleWhen(_Strict):
    """When a port is there: a function of the editor, a field of the node that must be truthy, or a setting of the node
    that must have a value (``setting`` with ``equals``; a setting that is not set counts as its default, and the
    server refuses a connection at a port that is not there, ADR-061)."""

    fn: str | None = None
    node: str | None = None
    setting: str | None = None
    equals: str | None = None

    @model_validator(mode="after")
    def _one(self) -> VisibleWhen:
        if sum(x is not None for x in (self.fn, self.node, self.setting)) != 1:
            raise ValueError("name one of fn, node or setting")
        if (self.setting is None) != (self.equals is None):
            raise ValueError("setting and equals belong together")
        if self.fn is not None and self.fn not in CLIENT_FUNCTIONS["visible"]:
            raise ValueError(
                f"unknown function {self.fn!r}: use {', '.join(CLIENT_FUNCTIONS['visible'])}"
            )
        return self


class PortSpec(_Strict):
    name: str
    label: str
    side: Literal["top", "bottom"] | None = None
    visible_when: VisibleWhen | None = None
    #: A function of the editor that labels the port from the node's settings (a Switch case by its condition).
    label_from: str | None = None
    repeat: int | None = Field(default=None, ge=1, le=50)

    @model_validator(mode="after")
    def _known(self) -> PortSpec:
        if self.label_from is not None and self.label_from not in CLIENT_FUNCTIONS["label"]:
            raise ValueError(f"unknown label function {self.label_from!r}")
        if self.repeat is not None and "{n}" not in self.name:
            raise ValueError("a repeated port has {n} in its name")
        return self


class PortsSpec(_Strict):
    inputs: list[PortSpec] = Field(default_factory=list)
    outputs: list[PortSpec] = Field(default_factory=list)


class SettingSpec(_Strict):
    """One setting; ``use`` takes the rest from a snippet of ``_shared.yaml`` and the fields given here win."""

    use: str | None = None
    key: str | None = None
    label: str | None = None
    type: Literal["integer", "number", "switch", "text", "lines", "code", "select"] | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    default: Any = None
    options: list[str] | None = None
    #: The shown text of an option (the stored value stays what ``options`` says); an option without one is shown as it is.
    option_labels: dict[str, str] | None = None
    max_length: int | None = None
    placeholder: str | None = None
    help: str | None = None
    stored_in: Literal["column", "config"] | None = None
    check: str | None = None
    group: str | None = None
    references: Literal["context", "all"] | None = None
    section: Literal["definition", "behaviour"] | None = None
    level: Literal["core", "optional", "advanced"] | None = None
    inherits: str | None = None
    #: Fields only the first copy of a repeated block has (a help text is said once, not five times).
    first: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _complete(self) -> SettingSpec:
        if self.use is None and not (self.key and self.label and self.type):
            raise ValueError("a setting needs key, label and type (or use a shared one)")
        if self.check is not None and self.check not in VALIDATORS:
            raise ValueError(f"unknown rule {self.check!r}: use {', '.join(sorted(VALIDATORS))}")
        if self.option_labels is not None and self.options is not None:
            unknown = sorted(set(self.option_labels) - set(self.options))
            if unknown:
                raise ValueError(
                    f"option_labels names options that do not exist: {', '.join(unknown)}"
                )
        return self


class RepeatSpec(_Strict):
    repeat: int = Field(ge=1, le=50)
    settings: list[SettingSpec]


class SizeSpec(_Strict):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class CaptionSpec(_Strict):
    """The line under a card's name: a template (``{key|filter}``, ``{@seconds}``, ``{?flag:text}``) or a named function."""

    template: str | None = None
    fn: str | None = None

    @model_validator(mode="after")
    def _one(self) -> CaptionSpec:
        if (self.template is None) == (self.fn is None):
            raise ValueError("name either template or fn")
        if self.fn is not None and self.fn not in CLIENT_FUNCTIONS["caption"]:
            raise ValueError(f"unknown caption function {self.fn!r}")
        if self.template is not None:
            for name in re.findall(r"\|([a-z_]+)", self.template):
                if name not in CAPTION_FILTERS:
                    raise ValueError(f"unknown filter {name!r}: use {', '.join(CAPTION_FILTERS)}")
        return self


class VariablesSpec(_Strict):
    """Where a kind declares the run variables it sets: a setting holding one name per line, or ``name = value`` lines."""

    setting: str = Field(min_length=1)
    format: Literal["lines", "assignments"]


class UiSpec(_Strict):
    icon: str | None = None
    #: The colour of the card: the name of a token ``--node-<color>`` in tokens.css (no CSS per kind, ADR-054).
    color: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]*$")
    #: The glyph of a step of this kind in the history when it differs from the card's (else ``icon``, else the menu glyph).
    step_icon: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]*$")
    size: SizeSpec | None = None
    port_labels: bool | None = None
    caption: CaptionSpec | None = None
    #: The inspector block that stands in for the plain settings (``agent``).
    block: Literal["agent"] | None = None
    size_fn: str | None = None
    group_used_fn: str | None = None

    @model_validator(mode="after")
    def _known(self) -> UiSpec:
        if self.size_fn is not None and self.size_fn not in CLIENT_FUNCTIONS["size"]:
            raise ValueError(f"unknown size function {self.size_fn!r}")
        if (
            self.group_used_fn is not None
            and self.group_used_fn not in CLIENT_FUNCTIONS["group_used"]
        ):
            raise ValueError(f"unknown function {self.group_used_fn!r}")
        return self


class MenuSpec(_Strict):
    group: str
    order: int = 0


class PlaceholderSpec(_Strict):
    """An entry of the "+" menu that is no kind of node: a place held for a feature that is coming (``_menu.yaml``)."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=40)
    icon: str = Field(min_length=1)
    group: str
    order: int = 0
    scopes: list[Literal["pipeline", "action"]] = Field(min_length=1)
    soon: bool = True


class NodeManifest(_Strict):
    """What a file in ``graph/nodes/`` says about one kind of node."""

    schema_version: int = Field(alias="schema")
    kind: str
    label: str
    behaviour: Literal[
        "plain", "flow", "stage", "action", "pipeline", "output", "tool", "switch"
    ] = "plain"
    scopes: list[Literal["pipeline", "action"]] = ["pipeline"]
    fixed: bool = False
    addable: bool = False
    chain: bool = False
    ending: bool = False
    tool: bool = False
    #: A guard may be attached to a node of this kind inside an action definition (the kind runs as a step).
    guardable: bool = False
    #: The node leaves ``output`` and ``data`` in the run context for later nodes (the ``${(Name).output}`` suggestions).
    produces_result: bool = False
    #: The flow panel shows how long a step of this kind took (it is a step that takes time worth showing).
    timed: bool = False
    #: Keys of ``data`` the kind always leaves (dotted paths), offered after ``${(Name).data.``.
    result_data: list[str] = Field(default_factory=list)
    #: The run variables the node sets, read from one of its settings (offered as ``${var.name}``).
    variables: VariablesSpec | None = None
    links_to: Literal["pipeline", "action"] | None = None
    default_size: SizeSpec | None = None
    reference_keys: list[str] = Field(default_factory=list)
    menu: MenuSpec | None = None
    #: The glyph before the name in every menu that lists the kind (the "+" menus); else ``ui.icon``. The card keeps its own look.
    menu_icon: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]*$")
    ports: PortsSpec = Field(default_factory=PortsSpec)
    ui: UiSpec = Field(default_factory=UiSpec)
    settings: list[RepeatSpec | SettingSpec] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def _version(self) -> NodeManifest:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"schema {self.schema_version} is not known (this application reads schema {SCHEMA_VERSION})"
            )
        return self


def schema() -> dict[str, Any]:
    """The JSON Schema of a manifest (what an author of a node validates against)."""
    return NodeManifest.model_json_schema(by_alias=True)


# ── reading ──────────────────────────────────────────────────────────


def _substitute(value: Any, n: int) -> Any:
    if isinstance(value, str):
        return value.replace("{n}", str(n))
    if isinstance(value, list):
        return [_substitute(v, n) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v, n) for k, v in value.items()}
    return value


def load_shared(directory: Path = NODES_DIR) -> dict[str, dict[str, Any]]:
    """The snippets of ``_shared.yaml`` by name."""
    path = directory / "_shared.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(name): dict(spec) for name, spec in (data.get("settings") or {}).items()}


def menu_groups(directory: Path = NODES_DIR) -> list[str]:
    """The clusters of the "+" menu in their order (a kind in another cluster is listed last, under that name)."""
    path = directory / "_menu.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return [str(g) for g in (data or {}).get("groups", [])]


def read_placeholders(directory: Path = NODES_DIR) -> list[PlaceholderSpec]:
    """The placeholder entries of ``_menu.yaml`` (valid, with unique keys that are no kind and a known cluster)."""
    path = directory / "_menu.yaml"
    data = (yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}) or {}
    groups = [str(g) for g in data.get("groups", [])]
    kinds = {p.stem for p in directory.glob("*.yaml") if not p.name.startswith("_")}
    found: list[PlaceholderSpec] = []
    for entry in data.get("placeholders") or []:
        try:
            spec = PlaceholderSpec.model_validate(entry)
        except ValidationError as error:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()
            )
            raise ManifestError(f"{path.name}: placeholders: {problems}") from error
        if spec.group not in groups:
            raise ManifestError(
                f"{path.name}: placeholder {spec.key!r}: unknown cluster {spec.group!r}"
            )
        if spec.key in kinds or spec.key in {p.key for p in found}:
            raise ManifestError(
                f"{path.name}: placeholder {spec.key!r} is a kind or is declared twice"
            )
        found.append(spec)
    return found


def expand_settings(
    specs: list[RepeatSpec | SettingSpec], shared: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """The settings as plain dicts: shared snippets filled in, repeated blocks written out."""
    result: list[dict[str, Any]] = []

    def one(spec: SettingSpec, n: int | None) -> None:
        data = spec.model_dump(exclude_unset=True)
        first = data.pop("first", None)
        if (use := data.pop("use", None)) is not None:
            if use not in shared:
                raise ValueError(f"no shared setting named {use!r}")
            data = {**shared[use], **data}
        if n is not None:
            data = _substitute(data, n)
            if n == 1 and first:
                data.update(_substitute(first, n))
        result.append(data)

    for spec in specs:
        if isinstance(spec, RepeatSpec):
            for n in range(1, spec.repeat + 1):
                for inner in spec.settings:
                    one(inner, n)
        else:
            one(spec, None)
    return result


def expand_ports(specs: list[PortSpec]) -> list[PortSpec]:
    out: list[PortSpec] = []
    for spec in specs:
        if spec.repeat is None:
            out.append(spec)
            continue
        for n in range(1, spec.repeat + 1):
            data = _substitute(spec.model_dump(exclude={"repeat"}), n)
            out.append(PortSpec(**data))
    return out


def read(path: Path) -> NodeManifest:
    """One manifest file; raises :class:`ManifestError` naming the file."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ManifestError(f"{path.name}: not valid YAML: {error}") from error
    try:
        return NodeManifest.model_validate(data)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()
        )
        raise ManifestError(f"{path.name}: {problems}") from error


def kind_order(directory: Path = NODES_DIR) -> list[str]:
    """The kinds in the order ``_menu.yaml`` lists them (kinds it does not list follow, by name)."""
    path = directory / "_menu.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return [str(k) for k in (data or {}).get("kinds", [])]


def read_all(directory: Path = NODES_DIR) -> list[NodeManifest]:
    """Every kind of a directory (``_menu.yaml`` and ``_shared.yaml`` are not kinds), in the listed order."""
    manifests = [read(p) for p in sorted(directory.glob("*.yaml")) if not p.name.startswith("_")]
    order = kind_order(directory)
    return sorted(
        manifests, key=lambda m: (order.index(m.kind) if m.kind in order else len(order), m.kind)
    )
