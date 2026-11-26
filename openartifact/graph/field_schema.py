"""A flat list of fields as a schema, and the check of a document against it (ADR-080).

One small module that says what a schema of fields is, how a stored list is checked, what a model is told (a JSON schema of an object) and
how a document it hands over is validated. It does not know the node that uses it: the Hand Over Tool (``agents/local_tools.py``) is the
first user, and whatever needs "the model answers in this shape" later uses the same list, the same editor (``components/schema-fields.js``)
and the same :func:`validate`.

A **field** is ``{"name", "type", "required", "description", "choices"?}``:

- ``text``: a text of at most :data:`MAX_TEXT_CHARS` characters;
- ``number``: a number (whole or decimal, not a boolean, not a text);
- ``boolean``: ``true`` or ``false``;
- ``choice``: one of the ``choices`` (2 to :data:`MAX_CHOICES` texts), as a text;
- ``list``: a list of at most :data:`MAX_LIST_ITEMS` texts, each of at most :data:`MAX_ITEM_CHARS` characters.

The schema is **flat**: no field holds an object or a list of objects. A document may hold the fields of the schema and nothing else.
Validation is plain data checking; nothing in a document is read as a reference or executed, and it comes back to the writer as the
exact list of what is wrong (all of it at once, so one more try can fix it).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

MAX_FIELDS = 30
MAX_DESCRIPTION_CHARS = 300
MAX_CHOICES = 20
MAX_CHOICE_CHARS = 60
MAX_TEXT_CHARS = 8000
MAX_LIST_ITEMS = 50
MAX_ITEM_CHARS = 500
#: The size of a whole document (UTF-8 bytes of its JSON): the bounds of the setting and its default.
MIN_DOCUMENT_BYTES, MAX_DOCUMENT_BYTES, DEFAULT_DOCUMENT_BYTES = 1024, 65536, 16384

NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")
TYPES = ("text", "number", "boolean", "choice", "list")
TYPE_LABELS = {
    "text": "Text",
    "number": "Number",
    "boolean": "True or false",
    "choice": "Choice",
    "list": "List of texts",
}


def coerce(field: Mapping[str, Any], text: str) -> Any:
    """The value a text stands for in the type of ``field`` (an input given as text, an output built from references);
    :class:`ValueError` says in plain words why it does not fit. A text field keeps the text; a number is read as a whole or decimal
    number; a boolean is ``true`` or ``false``; a choice is one of its values; a list is a JSON list of texts or one text per line."""
    name, kind = field["name"], field["type"]
    if kind == "text":
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError(f"'{name}' is longer than {MAX_TEXT_CHARS} characters")
        return text
    if kind == "number":
        try:
            number = float(text.strip())
        except ValueError:
            raise ValueError(f"'{name}' must be a number, not '{text[:40]}'") from None
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError(f"'{name}' must be a finite number")
        return int(number) if number.is_integer() else number
    if kind == "boolean":
        lowered = text.strip().lower()
        if lowered not in ("true", "false"):
            raise ValueError(f"'{name}' must be true or false, not '{text[:40]}'")
        return lowered == "true"
    if kind == "choice":
        if text not in field["choices"]:
            raise ValueError(f"'{name}' must be one of: {', '.join(field['choices'])}")
        return text
    items: Any
    stripped = text.strip()
    if stripped.startswith("["):
        try:
            items = json.loads(stripped)
        except ValueError:
            raise ValueError(f"'{name}' must be a list of texts") from None
    else:
        items = [line for line in text.splitlines() if line.strip()]
    problem = _problem(field, items)
    if problem:
        raise ValueError(problem)
    return items


def describe(extra: str | None = None) -> dict[str, Any]:
    """What an editor needs to draw the list: the types, the bounds (and which extra text a field carries)."""
    return {
        **({"field_extra": extra} if extra else {}),
        "field_types": list(TYPES),
        "max_fields": MAX_FIELDS,
        "field_limits": {
            "name_chars": 32,
            "description_chars": MAX_DESCRIPTION_CHARS,
            "choices": [2, MAX_CHOICES],
            "choice_chars": MAX_CHOICE_CHARS,
        },
    }


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value: Any) -> bool:
    return (
        isinstance(value, int | float) and not isinstance(value, bool) and value == value
    )  # not NaN


#: A list of fields may carry one more text per field: the default of an input (``default``) or the value of an output (``value``), ADR-083.
EXTRAS = ("default", "value")
MAX_EXTRA_CHARS = 2000


def normalise(value: Any, extra: str | None = None) -> list[dict[str, Any]]:
    """The list as it is stored; :class:`ValueError` with a plain message when it is no list of fields.

    With ``extra`` (``"default"`` or ``"value"``) every field may carry that one more text, kept as written (it may hold references).
    """
    if not isinstance(value, list):
        raise ValueError("The fields must be a list")
    if len(value) > MAX_FIELDS:
        raise ValueError(f"At most {MAX_FIELDS} fields")
    seen: set[str] = set()
    stored: list[dict[str, Any]] = []
    for position, item in enumerate(value, start=1):
        if not isinstance(item, Mapping):
            raise ValueError(f"Field {position} must be an object")
        allowed = {
            "name",
            "type",
            "required",
            "description",
            "choices",
            *([extra] if extra else []),
        }
        unknown = sorted(set(item) - allowed)
        if unknown:
            raise ValueError(f"Field {position} has no option '{unknown[0][:40]}'")
        name = item.get("name")
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise ValueError(
                f"Field {position}: the name is lowercase letters, digits and _, starting with a letter (at most 32 characters)"
            )
        if name in seen:
            raise ValueError(f"The field '{name}' is there twice")
        seen.add(name)
        kind = item.get("type", "text")
        if kind not in TYPES:
            raise ValueError(f"Field '{name}': the type is one of {', '.join(TYPES)}")
        required = item.get("required", False)
        if not isinstance(required, bool):
            raise ValueError(f"Field '{name}': required is true or false")
        description = item.get("description", "")
        if not isinstance(description, str) or len(description) > MAX_DESCRIPTION_CHARS:
            raise ValueError(
                f"Field '{name}': the description is a text of at most {MAX_DESCRIPTION_CHARS} characters"
            )
        entry: dict[str, Any] = {
            "name": name,
            "type": kind,
            "required": required,
            "description": description.strip(),
        }
        choices = item.get("choices")
        if kind == "choice":
            if (
                not isinstance(choices, list)
                or not all(isinstance(c, str) for c in choices)
                or not 2 <= len(cleaned := [c.strip() for c in choices if c.strip()]) <= MAX_CHOICES
            ):
                raise ValueError(f"Field '{name}': a choice needs 2 to {MAX_CHOICES} values")
            if any(len(c) > MAX_CHOICE_CHARS for c in cleaned):
                raise ValueError(
                    f"Field '{name}': a value is at most {MAX_CHOICE_CHARS} characters"
                )
            if len(set(cleaned)) != len(cleaned):
                raise ValueError(f"Field '{name}': a value is there twice")
            entry["choices"] = cleaned
        elif choices not in (None, []):
            raise ValueError(f"Field '{name}': only a choice has values")
        if extra and item.get(extra) not in (None, ""):
            text = item[extra]
            if not isinstance(text, str) or len(text) > MAX_EXTRA_CHARS:
                raise ValueError(
                    f"Field '{name}': the {extra} is a text of at most {MAX_EXTRA_CHARS} characters"
                )
            entry[extra] = text
        stored.append(entry)
    return stored


def fields_error(value: Any, extra: str | None = None) -> str | None:
    """Why ``value`` is no list of fields (plain words), or ``None``."""
    try:
        normalise(value, extra)
    except ValueError as error:
        return str(error)
    return None


def json_schema(fields: list[dict[str, Any]]) -> dict[str, Any]:
    """What the model is told: a JSON schema of an object with exactly these fields (``additionalProperties`` false)."""
    properties: dict[str, Any] = {}
    for field in fields:
        kind = field["type"]
        found: dict[str, Any]
        if kind == "number":
            found = {"type": "number"}
        elif kind == "boolean":
            found = {"type": "boolean"}
        elif kind == "choice":
            found = {"type": "string", "enum": list(field["choices"])}
        elif kind == "list":
            found = {"type": "array", "items": {"type": "string"}, "maxItems": MAX_LIST_ITEMS}
        else:
            found = {"type": "string", "maxLength": MAX_TEXT_CHARS}
        if field.get("description"):
            found["description"] = field["description"]
        properties[field["name"]] = found
    return {
        "type": "object",
        "properties": properties,
        "required": [f["name"] for f in fields if f["required"]],
        "additionalProperties": False,
    }


def _problem(field: Mapping[str, Any], value: Any) -> str | None:
    name, kind = field["name"], field["type"]
    if kind == "text":
        if not isinstance(value, str):
            return f"'{name}' must be a text"
        if len(value) > MAX_TEXT_CHARS:
            return f"'{name}' is longer than {MAX_TEXT_CHARS} characters"
    elif kind == "number":
        if not _number(value):
            return f"'{name}' must be a number"
    elif kind == "boolean":
        if not isinstance(value, bool):
            return f"'{name}' must be true or false"
    elif kind == "choice":
        if value not in field["choices"]:
            return f"'{name}' must be one of: {', '.join(field['choices'])}"
    elif kind == "list":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return f"'{name}' must be a list of texts"
        if len(value) > MAX_LIST_ITEMS:
            return f"'{name}' has more than {MAX_LIST_ITEMS} entries"
        if any(len(v) > MAX_ITEM_CHARS for v in value):
            return f"'{name}' has an entry longer than {MAX_ITEM_CHARS} characters"
    return None


def validate(
    fields: list[dict[str, Any]], document: Any, max_bytes: int = DEFAULT_DOCUMENT_BYTES
) -> list[str]:
    """What is wrong with ``document`` against ``fields``: the problems in plain words, empty when it fits.

    A field that is not required may be left out or be ``null``; a required one may be neither. A key the schema does not have is a
    problem (the message names the fields there are). The whole document is at most ``max_bytes`` of JSON.
    """
    if not isinstance(document, Mapping):
        return ["the document must be an object with the fields below"]
    problems: list[str] = []
    known = {f["name"]: f for f in fields}
    for key in document:
        if key not in known:
            listed = ", ".join(known) or "none"
            problems.append(f"unknown field '{str(key)[:40]}' (the fields are: {listed})")
    for field in fields:
        name = field["name"]
        if name not in document or document[name] is None:
            if field["required"]:
                problems.append(f"'{name}' is required")
            continue
        problem = _problem(field, document[name])
        if problem:
            problems.append(problem)
    if not problems:
        try:
            size = len(json.dumps(document, ensure_ascii=False).encode("utf-8"))
        except (TypeError, ValueError):
            return ["the document cannot be stored as JSON"]
        if size > max_bytes:
            problems.append(
                f"the document is {size} bytes, more than the limit of {max_bytes} bytes"
            )
    return problems


def clean(fields: list[dict[str, Any]], document: Mapping[str, Any]) -> dict[str, Any]:
    """The document as stored: the schema's fields in the schema's order, left-out and ``null`` fields dropped."""
    return {f["name"]: document[f["name"]] for f in fields if document.get(f["name"]) is not None}
