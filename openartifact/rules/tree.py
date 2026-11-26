"""The condition tree of a rule and its in-memory evaluator.

A tree is a group: it says *all* or *any* of its items must hold; an item is a condition or an inner group. A
condition is ``{"type": "condition", "field", "op", "value"}``; which fields, operators and values fit is the
schema's (:mod:`openartifact.rules.catalog`). Each purpose binds the base classes here to its schema
(``engine/retention.py``: ``Condition``, ``Group``; ``guards/schemas.py``: ``GuardCondition``, ``GuardGroup``), so
the stored JSON is the same shape everywhere.

Two evaluators read the same tree: the retention rules compile it to SQL (``engine/retention.py``), the guards
evaluate it here over a mapping of facts (``evaluate``). Both agree on the meaning:

- a group with nothing in it (counting inner groups that are empty too) is false at the top and is left out of
  the group around it, so an empty rule matches nothing;
- ``is`` / ``is_not`` test a choice (one of some values) or a text (ignoring case), ``contains`` a part of a text;
- ``older_than`` is *more than* N seconds, ``beyond`` is *at least* N newer ones (*keep the last N*);
- ``at_least`` / ``below`` / ``equals`` compare numbers, counts and durations (seconds);
- a fact that is missing (``None``) makes every condition on it false: an unknown never fires a rule.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict, model_validator

if TYPE_CHECKING:
    from openartifact.rules.catalog import RuleSchema

MAX_DEPTH = 4  # a group inside a group inside ...
MAX_CONDITIONS = 50  # in one rule


class ConditionBase(BaseModel):
    """One test of one field; a subclass names the schema it is checked against (``SCHEMA``)."""

    model_config = ConfigDict(extra="forbid")
    SCHEMA: ClassVar[RuleSchema]

    type: Literal["condition"] = "condition"
    field: str
    op: str
    value: list[str] | str | int | float

    @model_validator(mode="after")
    def _fits(self) -> ConditionBase:
        self.SCHEMA.check(self)
        return self


class Item(Protocol):
    type: str


def group_is_empty(group: Any) -> bool:
    """No condition anywhere in the group (an inner group that is empty counts as nothing)."""
    return all(group_is_empty(i) if i.type == "group" else False for i in group.items)


def check_bounds(
    group: Any, max_depth: int = MAX_DEPTH, max_conditions: int = MAX_CONDITIONS
) -> None:
    """Raise :class:`ValueError` when the tree is nested deeper or holds more conditions than allowed."""

    def walk(node: Any, depth: int) -> int:
        if depth > max_depth:
            raise ValueError(f"groups are nested too deep (at most {max_depth} levels)")
        return sum(walk(i, depth + 1) if i.type == "group" else 1 for i in node.items)

    if walk(group, 1) > max_conditions:
        raise ValueError(f"at most {max_conditions} conditions in a rule")


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def holds(condition: Any, facts: Mapping[str, Any]) -> bool:
    """Whether one condition holds for ``facts`` (a missing fact: never)."""
    fact = facts.get(condition.field)
    if fact is None:
        return False
    op, value = condition.op, condition.value
    if op in ("is", "is_not"):
        if isinstance(value, list):
            hit = str(fact) in {str(v) for v in value}
        else:
            hit = str(fact).strip().lower() == str(value).strip().lower()
        return hit if op == "is" else not hit
    if op == "contains":
        return str(value).strip().lower() in str(fact).lower()
    number, limit = _number(fact), _number(value)
    if number is None or limit is None:
        return False
    if op == "older_than":
        return number > limit
    if op in ("beyond", "at_least"):
        return number >= limit
    if op == "below":
        return number < limit
    if op == "equals":
        return number == limit
    raise ValueError(f"unknown operator {op!r}")


def evaluate(group: Any, facts: Mapping[str, Any]) -> bool:
    """Whether the tree holds for ``facts``; the in-memory twin of the SQL compiler of the retention rules."""
    parts = [
        evaluate(i, facts) if i.type == "group" else holds(i, facts)
        for i in group.items
        if not (i.type == "group" and group_is_empty(i))
    ]
    if not parts:
        return False
    return all(parts) if group.mode == "all" else any(parts)


def fields_of(group: Any) -> set[str]:
    """Every field the tree tests."""
    found: set[str] = set()
    for item in group.items:
        found |= fields_of(item) if item.type == "group" else {item.field}
    return found
