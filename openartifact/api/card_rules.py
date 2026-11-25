"""Card rule routes (ADR-071): the rules of a lane (``/api/lanes/{status}/rules``) and of the board (``/api/board/rules``).

The conditions and actions are described by ``GET /api/rules/schemas`` (purposes ``lane`` and ``board``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from openartifact.api.contract import GATED, errors
from openartifact.api.deps import ServiceDep
from openartifact.tasks.card_rules import Rule, RuleList

router = APIRouter(prefix="/api", tags=["card rules"], responses=GATED)

RULES_DESCRIPTION = (
    "The rules, in the order they are looked at: each ``{{when, action, name, enabled, params}}``. ``when`` is a condition tree "
    "like the retention rules' (fields from ``GET /api/rules/schemas`` purpose ``{purpose}``); a rule without a condition holds "
    "for every card of its place. Actions: {actions}. ``label`` takes ``params`` ``text`` and ``tone``, ``colour`` takes ``tone`` "
    "and ``mode`` (``fill`` or ``border``); tones are green, red, yellow, blue, neutral. At most 20 rules."
)


class RulesAnswer(RuleList):
    """The rules of one place."""


class CardPreviewWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: Rule


class CardPreviewCard(BaseModel):
    id: str
    number: int
    title: str
    lane: str
    why: str | None = None


class CardPreviewRead(BaseModel):
    """How many cards a rule would hit now, a few of them, and (``delete``) the ones it would spare and why."""

    count: int
    cards: list[CardPreviewCard]
    spared: list[CardPreviewCard]


class SweepRead(BaseModel):
    """What a pass of the rules does (or, as a dry run, would do)."""

    archive: int
    delete: int
    spared: int
    dry_run: bool


class DeletionRead(BaseModel):
    number: int | None
    title: str
    lane: str
    rule: str
    at: datetime


def _preview(found: Any) -> CardPreviewRead:
    return CardPreviewRead(
        count=found.count,
        cards=[CardPreviewCard(**c) for c in found.cards],
        spared=[CardPreviewCard(**c) for c in found.spared],
    )


@router.get(
    "/lanes/{status}/rules",
    response_model=RulesAnswer,
    summary="The rules of a lane",
    description=RULES_DESCRIPTION.format(
        purpose="lane", actions="``set_done``, ``archive``, ``label``, ``colour``"
    ),
    responses=errors(404, 422),
)
async def lane_rules(status: str, service: ServiceDep) -> RulesAnswer:
    return RulesAnswer(rules=await service.lane_card_rules(status))


@router.put(
    "/lanes/{status}/rules",
    response_model=RulesAnswer,
    summary="Replace the rules of a lane",
    description=RULES_DESCRIPTION.format(
        purpose="lane", actions="``set_done``, ``archive``, ``label``, ``colour``"
    )
    + " ``set_done`` without a condition is what the lane style ``finished`` is (the style follows the rules). 422 for an action a "
    "lane does not offer. Publishes ``cards.rules.changed``, ``board.lanes`` and ``board.resync``; archiving is done at once.",
    responses=errors(404, 422, write=True, body=True),
)
async def put_lane_rules(status: str, payload: RuleList, service: ServiceDep) -> RulesAnswer:
    return RulesAnswer(rules=await service.save_lane_rules(status, payload.rules))


@router.post(
    "/lanes/{status}/rules/preview",
    response_model=CardPreviewRead,
    summary="How many cards a rule of a lane would hit",
    description="Reads only: the cards of this lane the rule would hit now (``count``, ten of them in ``cards``).",
    responses=errors(404, 422, write=True, body=True),
)
async def preview_lane_rule(
    status: str, payload: CardPreviewWrite, service: ServiceDep
) -> CardPreviewRead:
    return _preview(await service.preview_rule(payload.rule, status))


@router.get(
    "/board/rules",
    response_model=RulesAnswer,
    summary="The rules of the board",
    description=RULES_DESCRIPTION.format(
        purpose="board", actions="``archive``, ``delete``, ``label``, ``colour``"
    ),
)
async def board_rules(service: ServiceDep) -> RulesAnswer:
    return RulesAnswer(rules=(await service.card_rules()).board)


@router.put(
    "/board/rules",
    response_model=RulesAnswer,
    summary="Replace the rules of the board",
    description=RULES_DESCRIPTION.format(
        purpose="board", actions="``archive``, ``delete``, ``label``, ``colour``"
    )
    + " ``delete`` removes only cards that are already archived, needs a condition, is off until switched on, and never touches "
    "a card with children or a running run. 422 for an action the board does not offer (``set_done``). Publishes "
    "``cards.rules.changed`` and ``board.resync``.",
    responses=errors(422, write=True, body=True),
)
async def put_board_rules(payload: RuleList, service: ServiceDep) -> RulesAnswer:
    return RulesAnswer(rules=await service.save_board_rules(payload.rules))


@router.post(
    "/board/rules/preview",
    response_model=CardPreviewRead,
    summary="How many cards a rule of the board would hit",
    description="Reads only: the cards the rule would hit now. For ``delete`` only archived cards count and the ones it would "
    "spare (children, a running run) are listed in ``spared`` with the reason: the dry run of a deletion.",
    responses=errors(422, write=True, body=True),
)
async def preview_board_rule(payload: CardPreviewWrite, service: ServiceDep) -> CardPreviewRead:
    return _preview(await service.preview_rule(payload.rule, None))


@router.post(
    "/board/rules/sweep",
    response_model=SweepRead,
    summary="Apply the archive and delete rules now",
    description="Does what the sweeper does every few minutes. With ``dry_run`` nothing changes and the answer says what would.",
    responses=errors(422, write=True),
)
async def sweep(service: ServiceDep, dry_run: bool = Query(default=False)) -> SweepRead:
    todo = await service.sweep(dry_run=dry_run)
    return SweepRead(
        archive=len(todo.archive), delete=len(todo.delete), spared=len(todo.spared), dry_run=dry_run
    )


@router.get(
    "/board/rules/deletions",
    response_model=list[DeletionRead],
    summary="What the rules deleted",
    description="The last 100 cards a rule deleted, newest first: number, title, lane, the rule and when.",
)
async def deletions(service: ServiceDep) -> list[dict[str, Any]]:
    return await service.deletion_log()
