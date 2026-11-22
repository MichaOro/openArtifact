"""Lane routes (prefix ``/api/lanes``): the lanes of the board and their titles.

The artifact API keeps using the status codes (``backlog``, ``in_progress``, ``done``); renaming a
lane changes the title the user sees, nothing else.
"""

from __future__ import annotations

from fastapi import APIRouter

from openartifact.api.contract import GATED, errors
from openartifact.api.deps import ServiceDep
from openartifact.tasks.lanes import TITLE_MAX_LENGTH
from openartifact.tasks.schemas import LaneRead, LaneRename

router = APIRouter(prefix="/api/lanes", tags=["lanes"], responses=GATED)

RENAME_DESCRIPTION = (
    f"Give a lane its own title: trimmed, 1 to {TITLE_MAX_LENGTH} characters, no control characters, "
    "different from the other lanes' titles (ignoring case), else 422. ``null``, an empty title or the "
    "default text restores the default. Returns the lanes and publishes ``board.lanes``."
)


@router.get("", response_model=list[LaneRead], summary="List the lanes")
async def list_lanes(service: ServiceDep) -> list[LaneRead]:
    """The lanes in board order: ``status`` (the code artifacts use), ``title`` (as shown),
    ``default_title`` and ``hue``."""
    return await service.lanes()


@router.put(
    "/{status}",
    response_model=list[LaneRead],
    summary="Rename a lane",
    description=RENAME_DESCRIPTION,
    responses=errors(404, 422, write=True, body=True),
)
async def rename_lane(status: str, payload: LaneRename, service: ServiceDep) -> list[LaneRead]:
    return await service.rename_lane(status, payload.title)
