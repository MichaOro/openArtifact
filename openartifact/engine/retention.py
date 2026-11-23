"""Retention rules (ADR-052): what happens to finished executions, for all artifacts.

The rules are a list; each says *when* (a condition tree) *then* an action. The only action so far is ``delete``
(for good, with the steps); ``ACTIONS`` is where another one (archive, notify) would be added.

A condition tree is: a group says *all* or *any* of its items must hold; an item is a condition or an inner group.
A condition tests one field of an execution: ``status`` and ``started_by`` (is / is not one of some values),
``pipeline`` (is / is not / contains a name, ignoring case), ``age`` (older than some seconds, counted from the
start) or ``position`` (beyond the newest N executions of the same artifact: *keep the last N*). An execution that the tree matches is deleted for good, with its steps; a running one never is, and an
empty group matches nothing, so an empty rule deletes nothing.

The rules are applied when something happens to the history (an execution is added or finishes) and when the rules
are saved: nothing runs on a timer. They are one row of ``app_settings`` (key ``history.rules``, JSON).
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import ColumnElement, and_, false, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from openartifact.models import AppSetting, Execution
from openartifact.models.enums import RunStatus, StartedBy

KEY = "history.rules"
MAX_DEPTH = 4  # a group inside a group inside ...
MAX_CONDITIONS = 50  # in one rule
MAX_RULES = 20
#: What a rule can do. Only deleting exists; another action is an entry here and a branch where the rules are applied.
ACTIONS = ("delete",)
MIN_AGE_SECONDS, MAX_AGE_SECONDS = 60, 10 * 365 * 24 * 3600
#: What a status condition may name: a running execution is never deleted, so it cannot be a target.
STATUSES = (RunStatus.DONE, RunStatus.FAILED, RunStatus.STOPPED)
FIELDS: dict[str, tuple[str, ...]] = {
    "status": ("is", "is_not"),
    "started_by": ("is", "is_not"),
    "pipeline": ("is", "is_not", "contains"),
    "age": ("older_than",),
    "position": ("beyond",),
}
MAX_POSITION = 100_000


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["condition"] = "condition"
    field: str
    op: str
    value: list[str] | str | int

    @model_validator(mode="after")
    def _fits(self) -> Condition:
        if self.field not in FIELDS:
            raise ValueError(f"unknown field {self.field[:40]!r}: use {', '.join(FIELDS)}")
        if self.op not in FIELDS[self.field]:
            raise ValueError(
                f"{self.field}: the operator {self.op!r} does not fit; use {', '.join(FIELDS[self.field])}"
            )
        if self.field in ("status", "started_by"):
            allowed = (
                [str(s) for s in STATUSES]
                if self.field == "status"
                else [str(s) for s in StartedBy]
            )
            if not isinstance(self.value, list) or not self.value:
                raise ValueError(f"{self.field}: name at least one of {', '.join(allowed)}")
            bad = [v for v in self.value if v not in allowed]
            if bad:
                note = " (a running execution is never deleted)" if bad[0] == "running" else ""
                raise ValueError(
                    f"{self.field}: {str(bad[0])[:40]!r} is not one of {', '.join(allowed)}{note}"
                )
        elif self.field == "pipeline":
            if not isinstance(self.value, str) or not 1 <= len(self.value.strip()) <= 120:
                raise ValueError("pipeline: give a name of 1 to 120 characters")
        elif self.field == "position":
            if (
                isinstance(self.value, bool)
                or not isinstance(self.value, int)
                or not 1 <= self.value <= MAX_POSITION
            ):
                raise ValueError(
                    f"position: give how many of the newest to keep, 1 to {MAX_POSITION}"
                )
        else:
            if (
                isinstance(self.value, bool)
                or not isinstance(self.value, int)
                or not MIN_AGE_SECONDS <= self.value <= MAX_AGE_SECONDS
            ):
                raise ValueError(f"age: give seconds, {MIN_AGE_SECONDS} (a minute) or more")
        return self


class Group(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["group"] = "group"
    mode: Literal["all", "any"] = "all"
    items: list[Annotated[Condition | Group, Field(discriminator="type")]] = Field(
        default_factory=list
    )


Group.model_rebuild()


class Rule(BaseModel):
    """*When* a condition tree holds, *then* an action on the execution."""

    model_config = ConfigDict(extra="forbid")

    when: Group = Field(default_factory=Group)
    action: str = "delete"

    @field_validator("action")
    @classmethod
    def _known(cls, action: str) -> str:
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action[:40]!r}: use {', '.join(ACTIONS)}")
        return action

    @model_validator(mode="after")
    def _bounded(self) -> Rule:
        def walk(group: Group, depth: int) -> int:
            if depth > MAX_DEPTH:
                raise ValueError(f"groups are nested too deep (at most {MAX_DEPTH} levels)")
            return sum(walk(i, depth + 1) if isinstance(i, Group) else 1 for i in group.items)

        if walk(self.when, 1) > MAX_CONDITIONS:
            raise ValueError(f"at most {MAX_CONDITIONS} conditions in a rule")
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


def group_is_empty(group: Group) -> bool:
    """No condition anywhere in the group (an inner group that is empty counts as nothing)."""
    return all(group_is_empty(i) if isinstance(i, Group) else False for i in group.items)


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
    return [r for r in rules.rules if r.action == action and not group_is_empty(r.when)]


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
    """How many executions each rule matches on its own (an empty rule: none)."""
    counts = []
    for rule in rules.rules:
        if group_is_empty(rule.when):
            counts.append(0)
            continue
        counts.append(
            await session.scalar(
                select(func.count()).select_from(Execution).where(matching(rule, now))
            )
            or 0
        )
    return counts
