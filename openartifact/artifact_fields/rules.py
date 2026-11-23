"""Artifact fields and the validation of their values (pure functions, no database; ADR-044).

The fields (``FieldSpec``) are ``text``, ``number``, ``boolean`` or ``choice``. Every problem is a sentence
that starts with ``Field NAME:``, so that a client can show it at the field; all problems of one request are
returned together, one per line.
"""

from __future__ import annotations

import difflib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

FIELD_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")
KINDS = ("text", "number", "boolean", "choice")
LABEL_MAX = 60
MAX_FIELDS = 30
MIN_OPTIONS, MAX_OPTIONS, OPTION_MAX = 1, 20, 40
DEFAULT_TEXT_LENGTH = 200
MAX_TEXT_LENGTH = 1000
#: All field values of an artifact together, as JSON text.
VALUES_LIMIT_BYTES = 4096


@dataclass(frozen=True)
class FieldSpec:
    """One artifact field, as the validation needs it."""

    name: str
    label: str
    kind: str
    default: Any = None
    options: tuple[str, ...] = ()
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    integer_only: bool = False
    #: A choice that holds several of its values (a list), ADR-050.
    multiple: bool = False


def _shown(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else f'"{value}"'
    return text if len(text) <= 60 else text[:57] + '..."'


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


# ── values ───────────────────────────────────────────────────────────


def check_value(spec: FieldSpec, value: Any) -> tuple[Any, str]:
    """``(normalised value, "")`` or ``(None, problem)``; ``value`` is neither ``None`` nor an empty text."""
    kind = spec.kind
    if kind == "text":
        if not isinstance(value, str):
            return None, f"{_shown(value)} is not text"
        limit = spec.max_length or DEFAULT_TEXT_LENGTH
        if len(value) > limit:
            return None, f"at most {limit} characters (got {len(value)})"
        return value, ""
    if kind == "boolean":
        if not isinstance(value, bool):
            return None, f"{_shown(value)} is not true or false"
        return value, ""
    if kind == "number":
        if not _is_number(value) or not math.isfinite(value):
            return None, f"{_shown(value)} is not a number"
        if spec.integer_only and value != int(value):
            return None, f"{_shown(value)} is not a whole number"
        number = int(value) if spec.integer_only else value
        if spec.min_value is not None and number < spec.min_value:
            return None, f"{_shown(value)} is below the minimum {_number(spec.min_value)}"
        if spec.max_value is not None and number > spec.max_value:
            return None, f"{_shown(value)} is above the maximum {_number(spec.max_value)}"
        return number, ""
    if spec.multiple:
        if not isinstance(value, list):
            return None, f"{_shown(value)} is not a list of values"
        chosen: list[str] = []
        for item in value:
            one, problem = _one_option(spec, item)
            if problem:
                return None, problem
            if one in chosen:
                return None, f"{_shown(one)} is chosen twice"
            chosen.append(one)
        return chosen, ""
    return _one_option(spec, value)


def _one_option(spec: FieldSpec, value: Any) -> tuple[Any, str]:
    if not isinstance(value, str) or value not in spec.options:
        close = difflib.get_close_matches(
            str(value).lower(), [o.lower() for o in spec.options], n=1, cutoff=0.6
        )
        message = f"{_shown(value)} is not one of {', '.join(spec.options)}"
        if close:
            message += f'. Did you mean "{next(o for o in spec.options if o.lower() == close[0])}"?'
        return None, message
    return value, ""


def _number(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def is_blank(value: Any) -> bool:
    return value is None or value == [] or (isinstance(value, str) and not value.strip())


def validate_values(
    fields: list[FieldSpec], values: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """The values to store and every problem found: unknown names, wrong kinds and limits. A ``None`` or
    blank value means "not set" and is left out (it then reads as the default)."""
    by_name = {f.name: f for f in fields}
    problems: list[str] = []
    for name, value in values.items():
        if (
            name not in by_name and value is not None
        ):  # ``null`` may clear a value of a removed field
            valid = ", ".join(by_name) or "none"
            problems.append(f"Field {str(name)[:40]}: there is no such field (fields: {valid})")
    stored: dict[str, Any] = {}
    for spec in fields:
        raw = values.get(spec.name)
        if is_blank(raw):
            continue
        value, problem = check_value(spec, raw)
        if problem:
            problems.append(f"Field {spec.name}: {problem}")
        else:
            stored[spec.name] = value
    size = len(json.dumps(stored, ensure_ascii=False, separators=(",", ":")).encode())
    if size > VALUES_LIMIT_BYTES:
        problems.append(
            f"Field values are limited to {VALUES_LIMIT_BYTES // 1024} KiB (got {size} bytes)"
        )
    return stored, problems


def with_defaults(fields: list[FieldSpec], values: Mapping[str, Any]) -> dict[str, Any]:
    """The values of a new artifact: what was given, the defaults for the rest."""
    filled = dict(values)
    for spec in fields:
        if is_blank(filled.get(spec.name)) and not is_blank(spec.default):
            filled[spec.name] = spec.default
    return filled


def card_values(fields: list[FieldSpec], stored: Mapping[str, Any]) -> dict[str, Any]:
    """What a run sees as ``card`` (and the card shows): every field with its stored value, else its
    default, else ``None``; names that are not fields (anymore) are left out."""
    card: dict[str, Any] = {}
    for spec in fields:
        value = stored.get(spec.name)
        card[spec.name] = spec.default if value is None else value
    return card


# ── definitions ──────────────────────────────────────────────────────


def check_definition(spec: FieldSpec) -> list[str]:
    """Problems with a field definition (its default is checked like a value)."""
    name = spec.name
    problems: list[str] = []

    def bad(text: str) -> None:
        problems.append(f"Field {name[:40]}: {text}")

    if not FIELD_NAME.fullmatch(name):
        bad(
            "the name is lowercase letters, digits and underscores, starting with a letter, 1-32 characters"
        )
    if not spec.label.strip() or len(spec.label) > LABEL_MAX:
        bad(f"the label is 1-{LABEL_MAX} characters")
    if spec.kind not in KINDS:
        bad(f"the kind must be {', '.join(KINDS)}")
        return problems
    if spec.kind == "choice":
        options = spec.options
        if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
            bad(f"a choice has {MIN_OPTIONS} to {MAX_OPTIONS} allowed values")
        elif len(set(options)) != len(options):
            bad("the allowed values must be different from each other")
        if any(not o.strip() or len(o) > OPTION_MAX for o in options):
            bad(f"each allowed value is 1-{OPTION_MAX} characters")
    elif spec.options:
        bad("only a choice has allowed values")
    if spec.multiple and spec.kind != "choice":
        bad("only a choice can allow several values")
    if (
        spec.kind == "text"
        and spec.max_length is not None
        and not (1 <= spec.max_length <= MAX_TEXT_LENGTH)
    ):
        bad(f"the maximum length is 1-{MAX_TEXT_LENGTH}")
    if spec.kind != "text" and spec.max_length is not None:
        bad("only text has a maximum length")
    if spec.kind != "number" and (
        spec.min_value is not None or spec.max_value is not None or spec.integer_only
    ):
        bad("only a number has a minimum, a maximum or a whole-number setting")
    if (
        spec.min_value is not None
        and spec.max_value is not None
        and spec.min_value > spec.max_value
    ):
        bad("the minimum is above the maximum")
    if not problems and not is_blank(spec.default):
        _, problem = check_value(spec, spec.default)
        if problem:
            bad(f"the default {problem}")
    return problems


def check_definitions(fields: list[FieldSpec]) -> list[str]:
    """Problems with the field list: its size, duplicate names and every field's own problems."""
    problems: list[str] = []
    if len(fields) > MAX_FIELDS:
        problems.append(f"There are at most {MAX_FIELDS} artifact fields")
    seen: set[str] = set()
    for spec in fields:
        if spec.name in seen:
            problems.append(f"Field {spec.name[:40]}: the name is used twice")
        seen.add(spec.name)
        problems.extend(check_definition(spec))
    return problems
