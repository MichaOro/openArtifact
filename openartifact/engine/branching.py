"""The If and Switch nodes: compare values of the run context and choose the way on.

Everything is plain text. The sides of a comparison are the node's texts with their ``${node...}`` /
``${var...}`` references replaced (:meth:`RunView.render`); a reference that cannot be resolved sends the
node to *Else* with a reason that names it. Secrets are never replaced here. There is no scripting,
no pattern matching and no loop.

Comparison rules (both sides are trimmed of white space first):

* ``equals`` / ``not equals``: numbers when both sides are numbers, text otherwise.
* ``contains``, ``starts with``, ``ends with`` (and ``not contains``): text.
* ``greater than``, ``less than``, ``greater or equal``, ``less or equal``: both sides must be numbers.
* ``is true`` / ``is false``: the left side must be ``true`` or ``false`` (JSON spelling).
* ``is empty`` / ``is not empty``: empty text, ``null``, ``[]`` or ``{}``.

A number is ``[+-]digits[.digits][e[+-]digits]``. A side that must be a number or a boolean and is not
sends the node to *Else*. Text is compared case-sensitively unless ``case_sensitive`` is off.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from openartifact.engine.context import ContextError, RunView
from openartifact.engine.results import NodeResult
from openartifact.graph.node_types import IF_ROWS, SWITCH_CASES, UNARY_OPERATORS, Ports

SHOWN_CHARS = 200
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


class UnevaluableError(ValueError):
    """A condition cannot be decided (the message is the reason shown in the step)."""


def _shown(text: str) -> str:
    return text if len(text) <= SHOWN_CHARS else f"{text[:SHOWN_CHARS]}…"


def _number(text: str) -> Decimal | None:
    if not _NUMBER.fullmatch(text):
        return None
    try:
        return Decimal(text)
    except ArithmeticError:
        return None


def _is_empty(text: str) -> bool:
    if text == "" or text[0] not in "n[{":
        return text == ""
    try:
        return json.loads(text) in (None, [], {})
    except ValueError:
        return False


def compare(left: str, operator: str, right: str, *, case_sensitive: bool = True) -> bool:
    """Whether ``left operator right`` holds; :class:`UnevaluableError` if the operands do not fit."""
    left, right = left.strip(), right.strip()
    if operator == "is empty":
        return _is_empty(left)
    if operator == "is not empty":
        return not _is_empty(left)
    if operator in ("is true", "is false"):
        if left not in ("true", "false"):
            raise UnevaluableError("the value is not true or false")
        return (left == "true") == (operator == "is true")
    a, b = _number(left), _number(right)
    if operator in ("greater than", "less than", "greater or equal", "less or equal"):
        if a is None or b is None:
            raise UnevaluableError("both sides must be numbers for " + operator)
        return {
            "greater than": a > b,
            "less than": a < b,
            "greater or equal": a >= b,
            "less or equal": a <= b,
        }[operator]
    if operator in ("equals", "not equals") and a is not None and b is not None:
        return (a == b) == (operator == "equals")
    if not case_sensitive:
        left, right = left.casefold(), right.casefold()
    match operator:
        case "equals":
            return left == right
        case "not equals":
            return left != right
        case "contains":
            return right in left
        case "not contains":
            return right not in left
        case "starts with":
            return left.startswith(right)
        case "ends with":
            return left.endswith(right)
    raise UnevaluableError(f"unknown operator '{operator[:40]}'")


def evaluate_if(config: dict[str, Any], view: RunView) -> NodeResult:
    """The result of an If node: port *yes* / *no*, or *else* (outcome fail) when it cannot be decided."""
    case_sensitive = config.get("case_sensitive", True) is not False
    rows: list[dict[str, Any]] = []
    error: str | None = None
    for n in range(1, IF_ROWS + 1):
        raw_left = str(config.get(f"left_{n}") or "")
        if not raw_left.strip():
            continue
        operator = str(config.get(f"operator_{n}") or "equals")
        row: dict[str, Any] = {"left": "", "operator": operator, "right": "", "result": None}
        rows.append(row)
        try:
            left = view.render(raw_left)
            row["left"] = _shown(left)
            right = ""
            if operator not in UNARY_OPERATORS:
                right = view.render(str(config.get(f"right_{n}") or ""))
                row["right"] = _shown(right)
            row["result"] = compare(left, operator, right, case_sensitive=case_sensitive)
        except (ContextError, UnevaluableError) as problem:
            error = error or f"Condition {n}: {problem}"
    if error is None and not rows:
        error = "No condition is set"
    if error is not None:
        return NodeResult(
            "fail",
            output=Ports.ELSE,
            reason=error,
            port=Ports.ELSE,
            data={"condition": None, "rows": rows},
        )
    results = [bool(r["result"]) for r in rows]
    holds = all(results) if config.get("combine") != "any" else any(results)
    port = Ports.YES if holds else Ports.NO
    return NodeResult("pass", output=port, port=port, data={"condition": holds, "rows": rows})


def evaluate_switch(config: dict[str, Any], view: RunView) -> NodeResult:
    """The result of a Switch node: the first matching case, *else* (pass) when none matches, *else*
    (fail) when the value cannot be resolved."""
    try:
        value = view.render(str(config.get("value") or ""))
    except ContextError as problem:
        return NodeResult(
            "fail",
            output=Ports.ELSE,
            reason=str(problem),
            port=Ports.ELSE,
            data={"value": None, "matched": None},
        )
    folded = (
        value.strip()
        if config.get("case_sensitive", True) is not False
        else value.strip().casefold()
    )
    matched: str | None = None
    for n in range(1, SWITCH_CASES + 1):
        case = str(config.get(Ports.case(n)) or "").strip()
        if (
            case
            and (case if config.get("case_sensitive", True) is not False else case.casefold())
            == folded
        ):
            matched = Ports.case(n)
            break
    port = matched or Ports.ELSE
    return NodeResult(
        "pass", output=port, port=port, data={"value": _shown(value), "matched": matched}
    )
