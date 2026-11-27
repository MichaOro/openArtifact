"""Lane routes (prefix ``/api/lanes``): the lanes of the board, adding, renaming and deleting them.

The artifact API names a lane by its ``status`` (the lane's key, which never changes); the title is
what the user sees and can be changed.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from openartifact.api.contract import GATED, errors
from openartifact.api.deps import ServiceDep
from openartifact.tasks.lanes import LANE_STYLES, MAX_LANES, NOT_EMPTY_MESSAGE, TITLE_MAX_LENGTH
from openartifact.tasks.schemas import LaneRead, LaneUpdate, LaneWrite

router = APIRouter(prefix="/api/lanes", tags=["lanes"], responses=GATED)

TITLE_RULES = (
    f"The title is trimmed, 1 to {TITLE_MAX_LENGTH} characters, without control characters, and "
    "differs from the other lanes' titles (ignoring case), else 422."
)
LANES_DESCRIPTION = (
    "The lanes in board order: ``id`` (a uuid: never changes, says nothing, survives a rename), ``title`` (the name the user gives), "
    "``status`` (the key artifacts carry in storage: made once from the first title, it no longer matches the title after a rename; kept for the web page), "
    "``key`` (its DOM form), ``position``, ``hue``, ``style`` (``normal`` or ``finished``: how its cards are drawn), "
    "``artifact_count`` and ``deletable`` (empty and not the last lane). Wherever a lane is named (a card's ``status``, the lane in a path) "
    "its title, its ``id`` or its ``status`` key is taken, in that order."
)
CREATE_DESCRIPTION = (
    f"Append a lane. {TITLE_RULES} A board has at most {MAX_LANES} lanes (422). Returns the lanes "
    "and publishes ``board.lanes``."
)
UPDATE_DESCRIPTION = (
    "Change a lane's ``title`` and/or ``style`` (its ``id`` and ``status`` key stay); at least one is required "
    f"(422). {TITLE_RULES} ``style`` is one of {', '.join(f'``{s}``' for s in LANE_STYLES)}: in a "
    "``finished`` lane the card titles are struck through and dimmed, nothing else changes. Returns "
    "the lanes and publishes ``board.lanes``."
)
DELETE_DESCRIPTION = (
    f'Delete a lane. 409 with "{NOT_EMPTY_MESSAGE}" while it holds artifacts, and for the last '
    "lane. Returns the remaining lanes and publishes ``board.lanes``."
)


@router.get(
    "", response_model=list[LaneRead], summary="List the lanes", description=LANES_DESCRIPTION
)
async def list_lanes(service: ServiceDep) -> list[LaneRead]:
    return await service.lanes()


@router.post(
    "",
    response_model=list[LaneRead],
    status_code=status.HTTP_201_CREATED,
    summary="Add a lane",
    description=CREATE_DESCRIPTION,
    responses=errors(422, write=True, body=True),
)
async def create_lane(payload: LaneWrite, service: ServiceDep) -> list[LaneRead]:
    return await service.create_lane(payload.title)


@router.put(
    "/{status}",
    response_model=list[LaneRead],
    summary="Change a lane",
    description=UPDATE_DESCRIPTION,
    responses=errors(404, 422, write=True, body=True),
)
async def update_lane(status: str, payload: LaneUpdate, service: ServiceDep) -> list[LaneRead]:
    return await service.update_lane(status, payload.title, payload.style)


@router.delete(
    "/{status}",
    response_model=list[LaneRead],
    summary="Delete a lane",
    description=DELETE_DESCRIPTION,
    responses=errors(404, 409, 422, write=True),
)
async def delete_lane(status: str, service: ServiceDep) -> list[LaneRead]:
    return await service.delete_lane(status)
