"""The Edit Fields node: variables of the run set from text and references, without code (ADR-039).

``fields`` is one ``name = value`` per line. Each value is filled from the run context in one pass
(:meth:`RunView.render`; a value is never evaluated and never scanned again) and stored as the variable
``name``, which later nodes read as ``${var.name}``. With ``value_types`` ``detect`` a value that is valid JSON
and a number, ``true``, ``false``, ``null``, an object or a list is stored as that; anything else stays text.
The variables go through the same checks as a Code node's (``check_vars``: names, nesting, count, size).

A secret is never a source: a variable is plain data that every later node and the history can read.
"""

from __future__ import annotations

import json
from typing import Any

from openartifact.engine.context import VAR_NAME, ContextError, RunView, check_vars
from openartifact.engine.results import NodeResult, failed

MAX_FIELDS = 100


class FieldsError(ValueError):
    """The fields text is not ``name = value`` per line (the message names the line)."""


def parse_fields(text: str) -> dict[str, str]:
    """``{name: value template}`` in the order of the lines; :class:`FieldsError` for a wrong line."""
    fields: dict[str, str] = {}
    lines = [(n, line) for n, line in enumerate(text.splitlines(), start=1) if line.strip()]
    if len(lines) > MAX_FIELDS:
        raise FieldsError(f"At most {MAX_FIELDS} fields")
    for number, line in lines:
        name, equals, value = line.partition("=")
        name = name.strip().removeprefix("var.")
        if not equals:
            raise FieldsError(f"Line {number} is not 'name = value'")
        if not VAR_NAME.fullmatch(name):
            raise FieldsError(
                f"Line {number}: '{name[:40]}' is not a variable name (lowercase letters, digits and "
                "underscores, starting with a letter)"
            )
        if name in fields:
            raise FieldsError(f"Field '{name}' is set twice")
        if "${secret" in value:
            raise FieldsError(
                "${secret:NAME} cannot be a field: a variable is plain data that later nodes and the "
                "history show"
            )
        fields[name] = value.strip()
    return fields


def _typed(text: str) -> Any:
    """A JSON number, boolean, null, object or list as that value; any other text as it is."""
    stripped = text.strip()
    if not stripped or stripped[0] not in '-0123456789tfn[{"':
        return text
    try:
        value = json.loads(stripped)
    except ValueError:
        return text
    return text if isinstance(value, str) else value  # a quoted JSON string stays as written


def run_set(config: dict[str, Any], view: RunView) -> NodeResult:
    """Fill every field and hand the engine the variables (it stores them only when the node passes)."""
    try:
        templates = parse_fields(str(config.get("fields") or ""))
    except FieldsError as error:
        return failed(str(error))
    if not templates:
        return failed("No field is set")
    detect = config.get("value_types") == "detect"
    values: dict[str, Any] = {}
    for name, template in templates.items():
        try:
            text = view.render(template)
        except ContextError as error:
            return failed(f"Field '{name}': {error}")
        values[name] = _typed(text) if detect else text
    try:
        check_vars(values)
    except ContextError as error:
        return failed(f"Invalid fields: {error}")
    return NodeResult(
        "pass",
        output=json.dumps(values, ensure_ascii=False, separators=(",", ":")),
        data={"fields": list(values)},
        variables=values,
    )
