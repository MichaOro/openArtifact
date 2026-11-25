"""Card rules (ADR-071): what a lane and the board do with cards, by *when* a condition tree holds *then* an action.

The rules are the ones of the retention (ADR-052) and the guards (ADR-060): a list per place, each with a condition tree
(``rules/tree.py``, fields of ``rules/catalog.py`` ``lane`` and ``board``) and an action. The actions are a small registry
(``ACTIONS``):

- ``set_done`` (lane): the card is drawn as finished (struck through and dimmed);
- ``archive`` (lane, board): the card is hidden from the board's list (``tasks.archived_at``), by the sweeper;
- ``delete`` (board): an *archived* card is deleted for good, by the sweeper; never one with children or a running run;
- ``label`` (lane, board): the card gets a short text in a tone, like the chip *Draft*;
- ``colour`` (lane, board): the card is tinted (fill) or framed (border) in one of a few semantic tones.

*Marks* (done, labels, colour) are derived whenever a card is read from the facts of the moment (time in the lane, time since
the last activity, ...), never stored; ``archive`` and ``delete`` change the data and are done by ``card_sweeper.py``.

A rule **without a condition holds for every card** of its place (a lane that draws its cards as finished is a rule *Set card as
done* without a condition); the retention rules, whose action cannot be undone, do nothing without one. ``delete`` needs a condition.
When several rules say something about one card: labels add up (the same label once), the first matching colour rule wins (the
rules of the card's lane come before those of the board, each in the order of its list), done and archive hold when any rule holds.

The rules are one row of ``app_settings`` (key ``cards.rules``, JSON: ``{"lanes": {lane key: [rule]}, "board": [rule]}``).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models import AppSetting, Lane, PipelineRun, Task, TaskActivity, TaskComment
from openartifact.models.enums import RunStatus
from openartifact.rules import tree
from openartifact.rules.catalog import BOARD, CARD_TONES, LANE, RuleSchema

logger = logging.getLogger(__name__)

KEY = "cards.rules"
LOG_KEY = "cards.rules.log"
MAX_RULES = 20
MAX_NAME = 80
MAX_LABEL = 24
LOG_KEEP = 100
TONES = CARD_TONES
MODES = ("fill", "border")
#: The activity kinds that mean the card came into its lane (a move, or its creation); the others say that something happened.
ENTERED_LANE = ("lane", "created", "unarchived")
#: Activity that is no sign of life of the card (the sweeper's own entry).
NOT_ACTIVITY = ("archived",)
SCHEMAS: dict[str, RuleSchema] = {"lane": LANE, "board": BOARD}
ACTIONS = ("set_done", "archive", "delete", "label", "colour")
_CHUNK = 500


class Condition(tree.ConditionBase):
    """A condition over a card (checked against the ``board`` schema, which has every field a lane rule may use)."""

    SCHEMA: ClassVar[RuleSchema] = BOARD


class Group(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["group"] = "group"
    mode: Literal["all", "any"] = "all"
    items: list[Annotated[Condition | Group, Field(discriminator="type")]] = Field(
        default_factory=list
    )


Group.model_rebuild()


class Rule(BaseModel):
    """*When* the condition tree holds for a card, *then* ``action`` (with its ``params``).

    ``params``: ``label`` needs ``text`` (1 to 24 characters) and ``tone``; ``colour`` needs ``tone`` and may name the ``mode``
    (``fill``, the default, or ``border``); the other actions take none. A rule that is off (``enabled`` false) stays stored and
    holds for nothing; a ``delete`` rule is off until it is switched on.
    """

    model_config = ConfigDict(extra="forbid")

    when: Group = Field(default_factory=Group)
    action: str
    name: str | None = Field(default=None, max_length=MAX_NAME * 4)
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _delete_is_off(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("action") == "delete" and "enabled" not in data:
            return {**data, "enabled": False}
        return data

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
    def _params(self) -> Rule:
        tree.check_bounds(self.when)
        params, action = self.params, self.action
        if action == "label":
            text = params.get("text")
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= MAX_LABEL:
                raise ValueError(f"label: give a text of 1 to {MAX_LABEL} characters")
            if params.get("tone") not in TONES:
                raise ValueError(f"label: tone is one of {', '.join(TONES)}")
            extra = set(params) - {"text", "tone"}
            self.params = {"text": text.strip(), "tone": params["tone"]}
        elif action == "colour":
            if params.get("tone") not in TONES:
                raise ValueError(f"colour: tone is one of {', '.join(TONES)}")
            mode = params.get("mode", "fill")
            if mode not in MODES:
                raise ValueError(f"colour: mode is one of {', '.join(MODES)}")
            extra = set(params) - {"tone", "mode"}
            self.params = {"tone": params["tone"], "mode": mode}
        else:
            extra = set(params)
            self.params = {}
            if action == "delete" and tree.group_is_empty(self.when):
                raise ValueError(
                    "delete: give at least one condition (an empty rule would hit every archived card)"
                )
        if extra:
            raise ValueError(f"{action}: unknown parameter {sorted(extra)[0][:40]!r}")
        return self

    def usable(self) -> bool:
        return self.enabled


class RuleList(BaseModel):
    """The body of ``PUT``: the rules of one place."""

    model_config = ConfigDict(extra="forbid")

    rules: list[Rule] = Field(default_factory=list, max_length=MAX_RULES)


class CardRules(BaseModel):
    """Every rule: per lane (by its key) and for the board."""

    model_config = ConfigDict(extra="forbid")

    lanes: dict[str, list[Rule]] = Field(default_factory=dict)
    board: list[Rule] = Field(default_factory=list, max_length=MAX_RULES)

    def for_card(self, lane: str) -> list[Rule]:
        """The rules that may say something about a card of ``lane``: its lane's first, then the board's; only those that are on."""
        return [r for r in (*self.lanes.get(lane, []), *self.board) if r.enabled]

    def any_on(self) -> bool:
        return any(r.enabled for rules in self.lanes.values() for r in rules) or any(
            r.enabled for r in self.board
        )


class LabelMark(BaseModel):
    text: str
    tone: str


class ColourMark(BaseModel):
    tone: str
    mode: str = "fill"


class CardMarks(BaseModel):
    """What the rules say about a card right now (derived when it is read, not stored)."""

    done: bool = False
    labels: list[LabelMark] = Field(default_factory=list)
    colour: ColourMark | None = None


def check_place(rules: Sequence[Rule], scope: str) -> None:
    """Raise :class:`ValueError` unless every action is one the place offers (``scope``: ``lane`` or ``board``)."""
    offered = tuple(c.key for c in SCHEMAS[scope].consequences)
    for rule in rules:
        if rule.action not in offered:
            raise ValueError(f"{scope} rules offer {', '.join(offered)}, not {rule.action!r}")


# ── storage ───────────────────────────────────────────────────────────


async def load_rules(session: AsyncSession) -> CardRules:
    row = await session.get(AppSetting, KEY)
    if row is None:
        return CardRules()
    try:
        return CardRules.model_validate(json.loads(row.value))
    except (ValueError, ValidationError):
        return (
            CardRules()
        )  # a stored rule that no longer fits does nothing, rather than acting on a guess


async def _store(session: AsyncSession, rules: CardRules) -> None:
    value = json.dumps(rules.model_dump(mode="json"))
    row = await session.get(AppSetting, KEY)
    if row is None:
        session.add(AppSetting(key=KEY, value=value))
    else:
        row.value = value


def is_finished_rule(rule: Rule) -> bool:
    """The rule a lane that draws its cards as finished has: *Set card as done*, on, without a condition."""
    return rule.action == "set_done" and rule.enabled and tree.group_is_empty(rule.when)


async def save_lane_rules(session: AsyncSession, lane: str, rules: Sequence[Rule]) -> CardRules:
    """Replace the rules of one lane; the lane's ``style`` follows (finished while it has the unconditional *done* rule)."""
    check_place(rules, "lane")
    stored = await load_rules(session)
    if rules:
        stored.lanes[lane] = list(rules)
    else:
        stored.lanes.pop(lane, None)
    await _store(session, stored)
    row = await session.get(Lane, lane)
    if row is not None:
        row.style = "finished" if any(is_finished_rule(r) for r in rules) else "normal"
    return stored


async def save_board_rules(session: AsyncSession, rules: Sequence[Rule]) -> CardRules:
    check_place(rules, "board")
    stored = await load_rules(session)
    stored.board = list(rules)
    await _store(session, stored)
    return stored


async def set_lane_finished(session: AsyncSession, lane: str, finished: bool) -> None:
    """The old switch of a lane (``style``) as a rule: on adds the unconditional *done* rule, off removes it (others stay)."""
    stored = await load_rules(session)
    others = [r for r in stored.lanes.get(lane, []) if not is_finished_rule(r)]
    if finished:
        others.insert(0, Rule(action="set_done"))
    if others:
        stored.lanes[lane] = others
    else:
        stored.lanes.pop(lane, None)
    await _store(session, stored)


async def finished_lanes(session: AsyncSession) -> set[str]:
    """The lanes that have the unconditional *done* rule (what ``LaneRead.style`` ``finished`` says)."""
    stored = await load_rules(session)
    return {lane for lane, rules in stored.lanes.items() if any(is_finished_rule(r) for r in rules)}


# ── facts ─────────────────────────────────────────────────────────────


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _chunks(ids: Sequence[str]) -> Iterable[Sequence[str]]:
    for start in range(0, len(ids), _CHUNK):
        yield ids[start : start + _CHUNK]


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


async def load_facts(
    session: AsyncSession, tasks: Sequence[Task], now: datetime
) -> dict[str, dict[str, Any]]:
    """The facts every condition reads, per task id; three grouped queries however many cards there are.

    *Time in the lane* counts from the card's last move (or its creation); *time since the last activity* from the newest of its
    activity, comments and last change; *time since archived* only exists for an archived card (a condition on it never holds for
    another).
    """
    ids = [t.id for t in tasks]
    entered: dict[str, datetime] = {}
    active: dict[str, datetime] = {}
    for chunk in _chunks(ids):
        rows = await session.execute(
            select(TaskActivity.task_id, TaskActivity.kind, func.max(TaskActivity.created_at))
            .where(TaskActivity.task_id.in_(chunk))
            .group_by(TaskActivity.task_id, TaskActivity.kind)
        )
        for task_id, kind, moment in rows:
            moment = _aware(moment)
            if kind in ENTERED_LANE and moment > entered.get(task_id, moment):
                entered[task_id] = moment
            elif kind in ENTERED_LANE:
                entered.setdefault(task_id, moment)
            if kind not in NOT_ACTIVITY and moment > active.get(task_id, moment):
                active[task_id] = moment
            elif kind not in NOT_ACTIVITY:
                active.setdefault(task_id, moment)
        comments = await session.execute(
            select(TaskComment.task_id, func.max(TaskComment.created_at))
            .where(TaskComment.task_id.in_(chunk))
            .group_by(TaskComment.task_id)
        )
        for task_id, moment in comments:
            moment = _aware(moment)
            active[task_id] = max(active.get(task_id, moment), moment)
    facts: dict[str, dict[str, Any]] = {}
    for task in tasks:
        created = _aware(task.created_at)
        since = max(entered.get(task.id, created), created)
        latest = max(active.get(task.id, created), _aware(task.updated_at), created)
        found: dict[str, Any] = {
            "lane": task.status,
            "in_lane": max((now - since).total_seconds(), 0.0),
            "idle": max((now - latest).total_seconds(), 0.0),
            "age": max((now - created).total_seconds(), 0.0),
            "title": task.title,
            "body": task.body or "",
            "has_parent": "yes" if task.parent_id else "no",
        }
        if task.archived_at is not None:
            found["archived_for"] = max((now - _aware(task.archived_at)).total_seconds(), 0.0)
        try:
            values = json.loads(task.field_values or "{}")
        except ValueError:
            values = {}
        for name, value in values.items():
            text = _as_text(value)
            if text is not None:
                found[f"field.{name}"] = text
        facts[task.id] = found
    return facts


# ── evaluation ────────────────────────────────────────────────────────


def holds(rule: Rule, facts: Mapping[str, Any]) -> bool:
    """Whether a rule that is on holds for one card (no condition: for every card)."""
    return rule.enabled and (tree.group_is_empty(rule.when) or tree.evaluate(rule.when, facts))


def marks_of(
    lane: str, rules: CardRules, facts: Mapping[str, Any], *, archived: bool = False
) -> CardMarks | None:
    """The marks of one card, or ``None`` when no rule says anything about it."""
    marks = CardMarks()
    seen: set[tuple[str, str]] = set()
    for rule in rules.for_card(lane):
        if rule.action not in ("set_done", "label", "colour") or not holds(rule, facts):
            continue
        if rule.action == "set_done":
            marks.done = True
        elif rule.action == "label":
            key = (rule.params["text"], rule.params["tone"])
            if key not in seen:
                seen.add(key)
                marks.labels.append(LabelMark(text=key[0], tone=key[1]))
        elif marks.colour is None:
            marks.colour = ColourMark(tone=rule.params["tone"], mode=rule.params["mode"])
    if not (marks.done or marks.labels or marks.colour):
        return None
    return marks


async def marks_for(
    session: AsyncSession, tasks: Sequence[Task], now: datetime | None = None
) -> dict[str, CardMarks]:
    """The marks of the cards that have any, by task id (nothing is queried while no rule is on)."""
    if not tasks:
        return {}
    rules = await load_rules(session)
    if not rules.any_on():
        return {}
    facts = await load_facts(session, tasks, now or datetime.now(UTC))
    found: dict[str, CardMarks] = {}
    for task in tasks:
        marks = marks_of(task.status, rules, facts[task.id], archived=task.archived_at is not None)
        if marks is not None:
            found[task.id] = marks
    return found


def wants(action: str, task: Task, rules: CardRules, facts: Mapping[str, Any]) -> list[Rule]:
    """The rules with ``action`` that hold for a card (empty: none)."""
    return [r for r in rules.for_card(task.status) if r.action == action and holds(r, facts)]


# ── deleting: what is never deleted ───────────────────────────────────


async def running_ids(session: AsyncSession, ids: Sequence[str]) -> set[str]:
    """The cards among ``ids`` that a run is running on."""
    found: set[str] = set()
    for chunk in _chunks(list(ids)):
        found |= set(
            await session.scalars(
                select(PipelineRun.task_id).where(
                    PipelineRun.task_id.in_(chunk), PipelineRun.status == RunStatus.RUNNING
                )
            )
        )
    return found


async def delete_blockers(session: AsyncSession, ids: Sequence[str]) -> dict[str, str]:
    """Why a card must not be deleted by a rule: it has children (they would lose their parent), or a run is running."""
    blocked: dict[str, str] = {}
    for chunk in _chunks(list(ids)):
        parents = await session.scalars(
            select(Task.parent_id).where(Task.parent_id.in_(chunk)).distinct()
        )
        for parent in parents:
            blocked[parent] = "it has child cards"
        running = await session.scalars(
            select(PipelineRun.task_id).where(
                PipelineRun.task_id.in_(chunk), PipelineRun.status == RunStatus.RUNNING
            )
        )
        for task_id in running:
            blocked[task_id] = "it is being processed"
    return blocked


async def append_log(session: AsyncSession, entries: Sequence[dict[str, Any]]) -> None:
    """Remember what a rule deleted (the last ``LOG_KEEP``): the card's activity goes with the card."""
    if not entries:
        return
    row = await session.get(AppSetting, LOG_KEY)
    kept: list[dict[str, Any]] = []
    if row is not None:
        try:
            kept = list(json.loads(row.value))
        except ValueError:
            kept = []
    kept = [*entries, *kept][:LOG_KEEP]
    value = json.dumps(kept)
    if row is None:
        session.add(AppSetting(key=LOG_KEY, value=value))
    else:
        row.value = value


async def read_log(session: AsyncSession) -> list[dict[str, Any]]:
    row = await session.get(AppSetting, LOG_KEY)
    if row is None:
        return []
    try:
        return list(json.loads(row.value))
    except ValueError:
        return []
