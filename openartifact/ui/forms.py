"""Configuration windows as data (ADR-062): the form of a window (its sections, fields and layout) is a YAML manifest in
``ui/forms/``, validated against the models below (``schema: 1``) and served to the browser, which draws every form with one
component (``static/js/components/form-view.js``).

A manifest *declares*: the sections with their column, the fields of each section with their widget, label, help
(shown in a tooltip), placeholder, options, limits and when they are there (``visible_when``), and which fields are
``advanced`` (folded away until asked for). It holds no code. A widget is chosen by *name* from the registry of the
browser (``static/js/components/form-widgets.js``: the built-in ones; an application or a third party adds more with
``registerWidget`` there and :func:`register_widget` here). Texts are English in the manifest; a locale file overrides them by
key (``forms.<form>.sections.<section>.title``,
``forms.<form>.fields.<key>.label`` / ``.help`` / ``.placeholder`` and ``.options.<value>``), and what it does
not override stays English, like the texts of the node kinds (ADR-056).
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from openartifact import i18n

SCHEMA_VERSION = 1
FORMS_DIR = Path(__file__).parent / "forms"
#: The widgets every form can use (``static/js/components/form-widgets.js``).
BUILT_IN_WIDGETS: tuple[str, ...] = (
    "text",
    "number",
    "textarea",
    "tags",
    "select",
    "choice",
    "chips",
    "switch",
    "readonly",
)
#: Widgets the application registers in the browser for what the built-in ones cannot be (a rule tree, rows of steps, a
#: picker of an action). A third party adds one with :func:`register_widget`.
CUSTOM_WIDGETS: set[str] = {
    "rule-tree",
    "escalation-steps",
    "action-picker",
    "limit",
    "optional-number",
}
KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class FormError(ValueError):
    """A form manifest is not valid; the message names the file and what is wrong."""


def register_widget(name: str) -> None:
    """Allow forms to name a widget the browser registers (``registerWidget(name, factory)``)."""
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        raise ValueError(f"a widget name is lowercase letters, digits and dashes: {name!r}")
    CUSTOM_WIDGETS.add(name)


def widgets() -> tuple[str, ...]:
    """Every widget a form may name."""
    return (*BUILT_IN_WIDGETS, *sorted(CUSTOM_WIDGETS))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OptionSpec(_Strict):
    value: str
    label: str


class VisibleWhen(_Strict):
    """A field is there while another field of the form has a value: ``equals`` one value or is one of ``in``."""

    field: str
    equals: str | int | bool | None = None
    in_: list[str | int | bool] | None = Field(default=None, alias="in")

    @model_validator(mode="after")
    def _one(self) -> VisibleWhen:
        if (self.equals is None) == (self.in_ is None):
            raise ValueError("name one of equals or in")
        return self


class FieldSpec(_Strict):
    key: str
    widget: str
    label: str
    help: str | None = None
    placeholder: str | None = None
    #: The section title already says what the field is: its label stays for screen readers only.
    hide_label: bool = False
    options: list[OptionSpec] = []
    default: Any = None
    required: bool = False
    min: float | None = None
    max: float | None = None
    step: float | None = None
    advanced: bool = False
    visible_when: VisibleWhen | None = None
    #: Free settings of a widget (a rule tree names its schema); no code.
    config: dict[str, Any] = {}

    @model_validator(mode="after")
    def _check(self) -> FieldSpec:
        if not KEY.fullmatch(self.key):
            raise ValueError(f"field key {self.key!r}: lowercase words joined by dots")
        if self.widget not in widgets():
            raise ValueError(f"unknown widget {self.widget!r}: use {', '.join(widgets())}")
        picks = self.widget in ("select", "choice", "chips")
        if picks and not self.options and not self.config.get("options_from_code"):
            raise ValueError(f"a {self.widget} needs options (or config.options_from_code)")
        if self.widget not in ("select", "choice", "chips") and self.options:
            raise ValueError(f"a {self.widget} takes no options")
        if self.advanced and self.required:
            raise ValueError("a required field cannot be advanced")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min is above max")
        return self


class SectionSpec(_Strict):
    key: str
    title: str
    #: 1 or 2: the column the section sits in on a wide window; ``auto`` fills the shorter column; ``full``: a row of its
    #: own across the whole width (a rule builder wants room).
    column: Literal[1, 2, "auto", "full"] = "auto"
    #: How much room it takes when the columns are balanced (default: its number of fields).
    weight: int | None = Field(default=None, ge=1, le=20)
    #: The tab of the page the section belongs to (a page that has tabs draws the form once per tab); ``None``: not in a tab.
    tab: str | None = None
    fields: list[FieldSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> SectionSpec:
        if not NAME.fullmatch(self.key):
            raise ValueError(f"section key {self.key!r}: lowercase letters, digits and underscores")
        return self


class FormManifest(_Strict):
    schema_version: int = Field(alias="schema")
    name: str
    #: How many columns a wide window has (a narrow one always has one).
    columns: Literal[1, 2] = 2
    #: The width of the form in rem on a wide window (the window around it is as wide as its content); without it the
    #: columns take what their content wants, up to the dialog's cap.
    width: int | None = Field(default=None, ge=24, le=64)
    sections: list[SectionSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> FormManifest:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema must be {SCHEMA_VERSION}")
        if not NAME.fullmatch(self.name):
            raise ValueError(f"name {self.name!r}: lowercase letters, digits and underscores")
        sections = [s.key for s in self.sections]
        if len(set(sections)) != len(sections):
            raise ValueError("section keys must be unique")
        fields = [f for s in self.sections for f in s.fields]
        keys = [f.key for f in fields]
        if len(set(keys)) != len(keys):
            raise ValueError(
                f"field keys must be unique: {sorted({k for k in keys if keys.count(k) > 1})}"
            )
        known = set(keys)
        for f in fields:
            if f.visible_when is not None:
                if f.visible_when.field == f.key:
                    raise ValueError(f"{f.key}: visible_when names the field itself")
                if f.visible_when.field not in known:
                    raise ValueError(
                        f"{f.key}: visible_when names {f.visible_when.field!r}, which is no field"
                    )
        return self


def read(path: Path) -> FormManifest:
    """Read and validate one manifest; any problem is a :class:`FormError` that names the file."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise FormError(f"{path.name}: cannot be read: {error}") from error
    if not isinstance(data, dict):
        raise FormError(f"{path.name}: a form manifest is a mapping")
    try:
        form = FormManifest.model_validate(data)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"]
            for e in error.errors()
        )
        raise FormError(f"{path.name}: {problems}") from error
    if path.stem != form.name:
        raise FormError(
            f"{path.name}: the file is named {path.stem!r} but the form is {form.name!r}"
        )
    return form


def read_all(directory: Path | None = None) -> dict[str, FormManifest]:
    """Every form of ``directory`` (default: the shipped ones) by name."""
    forms: dict[str, FormManifest] = {}
    for path in sorted((directory or FORMS_DIR).glob("*.yaml")):
        form = read(path)
        forms[form.name] = form
    return forms


FORMS: dict[str, FormManifest] = read_all()


def describe(form: FormManifest) -> dict[str, Any]:
    """The form as the browser gets it (English; :func:`localize` puts a language in)."""
    return form.model_dump(by_alias=True, exclude_none=True, exclude_defaults=False)


def _own(language: str, key: str) -> str | None:
    if language == i18n.DEFAULT_LANGUAGE or language not in i18n.languages():
        return None
    return i18n.messages(language).get(key)


def localize(description: dict[str, Any], language: str) -> dict[str, Any]:
    """The description with the language's overrides put in (a copy; English: as it is)."""
    if language == i18n.DEFAULT_LANGUAGE or language not in i18n.languages():
        return description
    out = copy.deepcopy(description)
    base = f"forms.{out['name']}"
    for section in out["sections"]:
        sbase = f"{base}.sections.{section['key']}"
        section["title"] = _own(language, f"{sbase}.title") or section["title"]
        for field in section["fields"]:
            fbase = f"{base}.fields.{field['key']}"
            for name in ("label", "help", "placeholder"):
                if field.get(name) and (text := _own(language, f"{fbase}.{name}")):
                    field[name] = text
            for option in field.get("options") or []:
                if text := _own(language, f"{fbase}.options.{option['value']}"):
                    option["label"] = text
    return out
