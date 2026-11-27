"""What the card rules change in the data (ADR-071): archive and delete, and the count of cards a rule would hit.

Marks (done, labels, colour) are derived when a card is read (``card_rules.marks_for``); this module is the part that acts.
It looks at every card in one pass (the facts of all cards are read with three grouped queries), so a board of a thousand cards costs
the same few queries as a board of ten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.activity.recorder import SYSTEM, record
from openartifact.activity.schemas import ActivityRead
from openartifact.comments.schemas import Author
from openartifact.models import Task
from openartifact.tasks import card_rules
from openartifact.tasks.card_rules import CardRules, Rule

SAMPLE = 10


@dataclass
class Plan:
    """What a pass would do: the cards to archive, the ones to delete, and the ones a delete rule hits but must spare."""

    archive: list[Task] = field(default_factory=list)
    delete: list[Task] = field(default_factory=list)
    spared: dict[str, str] = field(default_factory=dict)
    rule_of: dict[str, str] = field(default_factory=dict)


async def plan(session: AsyncSession, rules: CardRules, now: datetime) -> Plan:
    """What the rules do to the cards now: archive a visible card any archive rule holds for, delete an archived one any
    delete rule holds for (never one with children or a running run)."""
    result = Plan()
    if not any(r.action in ("archive", "delete") for r in _all(rules)):
        return result
    tasks = list((await session.scalars(select(Task).where(Task.technical.is_(False)))).all())
    facts = await card_rules.load_facts(session, tasks, now)
    for task in tasks:
        if task.archived_at is None:
            if card_rules.wants("archive", task, rules, facts[task.id]):
                result.archive.append(task)
        else:
            hit = card_rules.wants("delete", task, rules, facts[task.id])
            if hit:
                result.delete.append(task)
                result.rule_of[task.id] = hit[0].name or hit[0].action
    busy = await card_rules.running_ids(session, [t.id for t in result.archive])
    result.archive = [
        t for t in result.archive if t.id not in busy
    ]  # a card that is being processed stays
    blocked = await card_rules.delete_blockers(session, [t.id for t in result.delete])
    result.spared = {t.id: blocked[t.id] for t in result.delete if t.id in blocked}
    result.delete = [t for t in result.delete if t.id not in blocked]
    return result


def _all(rules: CardRules) -> list[Rule]:
    return [r for lane in rules.lanes.values() for r in lane if r.enabled] + [
        r for r in rules.board if r.enabled
    ]


async def archive(
    session: AsyncSession, tasks: list[Task], now: datetime, actor: Author = SYSTEM
) -> list[ActivityRead]:
    """Set ``archived_at`` (the card's ``updated_at`` stays: archiving is no sign of life) and note it in the activity."""
    entries = []
    for task in tasks:
        await session.execute(
            update(Task)
            .where(Task.id == task.id)
            .values(archived_at=now, archived_from_status=task.status, updated_at=task.updated_at)
        )
        entries.append(await record(session, task.id, "archived", actor, {}, at=now))
    return entries


def log_entry(task: Task, why: str, now: datetime) -> dict[str, Any]:
    return {
        "number": task.number,
        "title": task.title[:80],
        "lane": task.status,
        "rule": why,
        "at": now.astimezone(UTC).isoformat(),
    }


@dataclass
class Preview:
    """How many cards one rule hits now (``count``), a few of them (``cards``), and for ``delete`` the ones it would spare."""

    count: int
    cards: list[dict[str, Any]]
    spared: list[dict[str, Any]] = field(default_factory=list)


async def preview(
    session: AsyncSession, rule: Rule, lane: str | None, now: datetime | None = None
) -> Preview:
    """The cards a rule would hit if it were on: of one lane (``lane``) or of the board; ``delete`` only archived cards."""
    now = now or datetime.now(UTC)
    tasks = [
        t
        for t in (
            await session.scalars(
                select(Task).where(Task.technical.is_(False)).order_by(Task.number)
            )
        ).all()
        if (lane is None or t.status == lane)
        and ((t.archived_at is not None) == (rule.action == "delete"))
    ]
    facts = await card_rules.load_facts(session, tasks, now)
    hit = [
        t for t in tasks if card_rules.holds(rule.model_copy(update={"enabled": True}), facts[t.id])
    ]
    spared: dict[str, str] = {}
    if rule.action == "delete":
        spared = await card_rules.delete_blockers(session, [t.id for t in hit])

    def row(task: Task) -> dict[str, Any]:
        return {"id": task.id, "number": task.number, "title": task.title, "lane": task.status}

    sure = [t for t in hit if t.id not in spared]
    return Preview(
        count=len(sure),
        cards=[row(t) for t in sure[:SAMPLE]],
        spared=[{**row(t), "why": spared[t.id]} for t in hit if t.id in spared][:SAMPLE],
    )
