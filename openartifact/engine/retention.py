"""Retention rules (ADR-052): what happens to finished executions, for all artifacts.

The rules are a list; each says *when* (a condition tree) *then* an action. The only action so far is ``delete``
(for good, with the steps); ``ACTIONS`` is where another one (archive, notify) would be added.

A condition tree is: a group says *all* or *any* of its items must hold; an item is a condition or an inner group.
A condition tests one field of an execution: ``status`` and ``started_by`` (is / is not one of some values),
``pipeline`` (is / is not / contains a name, ignoring case), ``age`` (older than some seconds, counted from the
start) or ``position`` (beyond the newest N executions of the same artifact: *keep the last N*). The fields and
their checks are the ``retention`` schema of ``rules/catalog.py``; the tree is the one of ``rules/tree.py``, which
also evaluates it in memory (the guards do); this module compiles it to SQL. An execution that the tree matches is deleted for good, with its steps; a running one never is, and an
empty group matches nothing, so an empty rule deletes nothing.

The rules are applied when something happens to the history (an execution is added or finishes) and when the rules
are saved: nothing runs on a timer. They are one row of ``app_settings`` (key ``history.rules``, JSON).
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import ColumnElement, and_, false, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from openartifact.models import AppSetting, Execution
from openartifact.models.enums import RunStatus
from openartifact.rules import catalog, tree
from openartifact.rules.catalog import RETENTION, RuleSchema

KEY = "history.rules"
MAX_DEPTH = tree.MAX_DEPTH
MAX_CONDITIONS = tree.MAX_CONDITIONS
MAX_RULES = 20
#: What a rule can do (the consequences of the ``retention`` schema). Only deleting exists; another action is an
#: entry in ``rules/catalog.py`` and a branch where the rules are applied.
ACTIONS = tuple(c.key for c in RETENTION.consequences if c.available)
MIN_AGE_SECONDS, MAX_AGE_SECONDS = catalog.MIN_AGE_SECONDS, catalog.MAX_AGE_SECONDS
STATUSES = catalog.RETENTION_STATUSES
FIELDS: dict[str, tuple[str, ...]] = {f.key: f.operators for f in RETENTION.fields}
MAX_POSITION = catalog.MAX_POSITION


class Condition(tree.ConditionBase):
    """A condition of a retention rule (checked against the ``retention`` schema)."""

    SCHEMA: ClassVar[RuleSchema] = RETENTION


class Group(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["group"] = "group"
    mode: Literal["all", "any"] = "all"
    items: list[Annotated[Condition | Group, Field(discriminator="type")]] = Field(
        default_factory=list
    )


Group.model_rebuild()


MAX_NAME = 80


class Rule(BaseModel):
    """*When* a condition tree holds, *then* an action on the execution.

    A rule may have a ``name`` (a label for the list, at most 80 characters; blank is no name) and a switch
    ``enabled``: a rule that is off stays stored but is never applied and matches nothing. Rules stored before
    these two existed read as unnamed and on.
    """

    model_config = ConfigDict(extra="forbid")

    when: Group = Field(default_factory=Group)
    action: str = "delete"
    name: str | None = Field(default=None, max_length=MAX_NAME * 4)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _label(cls, name: str | None) -> str | None:
        if name is None:
            return None
        name = name.strip()
        if len(name) > MAX_NAME:
            raise ValueError(f"the name is at most {MAX_NAME} characters")
        return name or None

    @field_validator("action")
    @classmethod
    def _known(cls, action: str) -> str:
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action[:40]!r}: use {', '.join(ACTIONS)}")
        return action

    @model_validator(mode="after")
    def _bounded(self) -> Rule:
        tree.check_bounds(self.when, MAX_DEPTH, MAX_CONDITIONS)
        return self


class Rules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[Rule] = Field(default_factory=list, max_length=MAX_RULES)


def _like_escaped(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _condition(c: Condition, now: Any) -> ColumnElement[bool]:
    if c.field == "age":
        cutoff = (now - timedelta(seconds=int(c.value))).replace(tzinfo=None)  # type: ignore[arg-type]
        older: ColumnElement[bool] = Execution.started_at < cutoff
        return older
    if c.field == "position":
        # beyond the newest N of its artifact: at least N executions of the same artifact are newer
        newer = aliased(Execution)
        count = (
            select(func.count())
            .where(newer.task_id == Execution.task_id, newer.number > Execution.number)
            .correlate(Execution)
            .scalar_subquery()
        )
        beyond: ColumnElement[bool] = count >= int(c.value)  # type: ignore[arg-type]
        return beyond
    if c.field in ("status", "started_by"):
        column = Execution.status if c.field == "status" else Execution.started_by
        listed = column.in_([str(v) for v in c.value])  # type: ignore[union-attr]
        return listed if c.op == "is" else not_(listed)
    name = str(c.value).strip().lower()
    column_name = func.lower(Execution.pipeline_name)
    if c.op == "contains":
        return column_name.like(f"%{_like_escaped(name)}%", escape="\\")
    return column_name == name if c.op == "is" else column_name != name


def where(group: Group, now: Any) -> ColumnElement[bool]:
    """The SQL condition a group stands for; a group with nothing in it (counting inner groups that are empty too)
    is false at the top and is left out of the group around it."""
    parts = [
        where(i, now) if isinstance(i, Group) else _condition(i, now)
        for i in group.items
        if not (isinstance(i, Group) and group_is_empty(i))
    ]
    if not parts:
        return false()
    combined: ColumnElement[bool] = and_(*parts) if group.mode == "all" else or_(*parts)
    return combined


group_is_empty = tree.group_is_empty


def matching(rule: Rule, now: Any) -> ColumnElement[bool]:
    """Finished executions one rule matches (a running one never)."""
    return and_(Execution.status != RunStatus.RUNNING, where(rule.when, now))


def _legacy(data: Any) -> Any:
    """Rules stored as one tree before actions existed become one rule that deletes."""
    if isinstance(data, dict) and isinstance(data.get("rules"), dict):
        return {"rules": [{"when": data["rules"], "action": "delete"}]}
    return data


async def load_rules(session: AsyncSession) -> Rules:
    row = await session.get(AppSetting, KEY)
    if row is None:
        return Rules()
    try:
        return Rules.model_validate(_legacy(json.loads(row.value)))
    except (ValueError, ValidationError):
        return (
            Rules()
        )  # a stored rule that no longer fits does nothing, rather than acting on a guess


async def save_rules(session: AsyncSession, rules: Rules) -> None:
    value = json.dumps(rules.model_dump(mode="json"))
    row = await session.get(AppSetting, KEY)
    if row is None:
        session.add(AppSetting(key=KEY, value=value))
    else:
        row.value = value


def _usable(rules: Rules, action: str) -> list[Rule]:
    return [
        r for r in rules.rules if r.enabled and r.action == action and not group_is_empty(r.when)
    ]


async def matching_ids(
    session: AsyncSession, rules: Rules, now: Any, action: str = "delete"
) -> list[tuple[str, str]]:
    """``(task id, execution id)`` of the finished executions any rule with this action matches, each once."""
    usable = _usable(rules, action)
    if not usable:
        return []
    clause = or_(*[matching(r, now) for r in usable])
    rows = await session.execute(select(Execution.task_id, Execution.id).where(clause))
    return [(r.task_id, r.id) for r in rows]


async def count_per_rule(session: AsyncSession, rules: Rules, now: Any) -> list[int]:
    """How many executions each rule matches on its own (an empty rule or one that is off: none)."""
    counts = []
    for rule in rules.rules:
        if not rule.enabled or group_is_empty(rule.when):
            counts.append(0)
            continue
        counts.append(
            await session.scalar(
                select(func.count()).select_from(Execution).where(matching(rule, now))
            )
            or 0
        )
    return counts
