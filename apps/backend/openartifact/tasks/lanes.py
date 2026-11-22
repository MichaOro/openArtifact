"""Board lanes: the columns artifacts sit in, their titles, order and the rules for changing them.

The lanes are rows of the table ``lanes`` (migration 0029, ADR-011); ``tasks.status`` holds a lane's
``key`` and references it, so the database itself refuses an artifact in a lane that does not exist
and the deletion of a lane that still holds artifacts. The UI never hard-codes lanes: the page renders
them from here and the frontend reads them back from the DOM (``[data-lane]``).
"""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models import Lane, Task
from openartifact.tasks.schemas import LaneRead

#: Number of hues in the lane palette (tokens.css: --lane-hue-1 … --lane-hue-N). The lane at board
#: position N uses hue N, cycling when there are more lanes than hues.
LANE_HUES = 8
MAX_LANES = 12
TITLE_MAX_LENGTH = 40
KEY_MAX_LENGTH = 32
NOT_EMPTY_MESSAGE = "A lane can only be deleted when it contains no artifacts."


class LaneError(Exception):
    """A lane change that is refused; ``code`` is the HTTP status the interfaces answer with."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def clean_title(value: str) -> str:
    """The title as stored: trimmed. Raises :class:`LaneError` (422) if it cannot be used."""
    title = value.strip()
    if not title:
        raise LaneError(422, "A lane needs a title.")
    if len(title) > TITLE_MAX_LENGTH:
        raise LaneError(422, f"A lane title has at most {TITLE_MAX_LENGTH} characters.")
    if any(unicodedata.category(c).startswith("C") for c in title):
        raise LaneError(422, "A lane title must not contain control characters.")
    return title


def key_for(title: str, taken: set[str]) -> str:
    """A key from a title (``Code Review`` -> ``code_review``), made unique with a numeric suffix."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "_", ascii_title.lower()).strip("_")
    if not base or not base[0].isalpha():
        base = f"lane_{base}".rstrip("_")
    base = base[:KEY_MAX_LENGTH]
    key, n = base, 1
    while key in taken:
        n += 1
        suffix = f"_{n}"
        key = base[: KEY_MAX_LENGTH - len(suffix)] + suffix
    return key


async def _rows(session: AsyncSession) -> list[Lane]:
    return list((await session.scalars(select(Lane).order_by(Lane.position, Lane.key))).all())


async def effective_lanes(session: AsyncSession) -> list[LaneRead]:
    """The lanes in board order with their artifact counts."""
    rows = await _rows(session)
    counts = dict(
        (await session.execute(select(Task.status, func.count()).group_by(Task.status))).all()
    )
    return [
        LaneRead(
            status=lane.key,
            key=lane.key.replace("_", "-"),
            title=lane.title,
            position=lane.position,
            hue=index % LANE_HUES + 1,
            artifact_count=counts.get(lane.key, 0),
            deletable=counts.get(lane.key, 0) == 0 and len(rows) > 1,
        )
        for index, lane in enumerate(rows)
    ]


async def lane_keys(session: AsyncSession) -> list[str]:
    """The keys of all lanes in board order."""
    return [lane.key for lane in await _rows(session)]


async def require_lane(session: AsyncSession, key: str) -> str:
    """``key`` if the lane exists, else a :class:`LaneError` (422) that lists the valid keys."""
    keys = await lane_keys(session)
    if key not in keys:
        raise LaneError(422, f"Unknown lane '{key}'. Valid lanes: {', '.join(keys)}")
    return key


async def first_lane(session: AsyncSession) -> str:
    """The key of the first lane: where an artifact goes when no lane is given."""
    return (await lane_keys(session))[0]


def _check_unique(lanes: list[Lane], title: str, *, ignoring: str | None = None) -> None:
    for other in lanes:
        if other.key != ignoring and other.title.casefold() == title.casefold():
            raise LaneError(422, f'Another lane is already called "{other.title}".')


async def create_lane(session: AsyncSession, title: str) -> list[LaneRead]:
    """Append a lane (at most :data:`MAX_LANES`). Raises :class:`LaneError` (422) for a bad title or limit."""
    chosen = clean_title(title)
    lanes = await _rows(session)
    if len(lanes) >= MAX_LANES:
        raise LaneError(422, f"A board has at most {MAX_LANES} lanes.")
    _check_unique(lanes, chosen)
    session.add(
        Lane(
            key=key_for(chosen, {lane.key for lane in lanes}),
            title=chosen,
            position=max((lane.position for lane in lanes), default=-1) + 1,
        )
    )
    try:
        await session.commit()
    except IntegrityError as error:  # the same title created at the same time (the unique index)
        await session.rollback()
        raise LaneError(422, f'Another lane is already called "{chosen}".') from error
    return await effective_lanes(session)


async def rename_lane(session: AsyncSession, key: str, title: str) -> list[LaneRead]:
    """Change a lane's title (its key stays). Raises :class:`LaneError`: 404 unknown, 422 bad title."""
    lanes = await _rows(session)
    lane = next((row for row in lanes if row.key == key), None)
    if lane is None:
        raise LaneError(404, f"Unknown lane '{key}'")
    chosen = clean_title(title)
    _check_unique(lanes, chosen, ignoring=key)
    lane.title = chosen
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise LaneError(422, f'Another lane is already called "{chosen}".') from error
    return await effective_lanes(session)


async def delete_lane(session: AsyncSession, key: str) -> list[LaneRead]:
    """Delete an empty lane. Raises :class:`LaneError`: 404 unknown, 409 not empty or the last lane.

    The foreign key ``ON DELETE RESTRICT`` is the safety net when an artifact moves in concurrently.
    """
    lanes = await _rows(session)
    lane = next((row for row in lanes if row.key == key), None)
    if lane is None:
        raise LaneError(404, f"Unknown lane '{key}'")
    if len(lanes) == 1:
        raise LaneError(409, "The last lane cannot be deleted.")
    in_lane = await session.scalar(select(func.count()).select_from(Task).where(Task.status == key))
    if in_lane:
        raise LaneError(409, NOT_EMPTY_MESSAGE)
    await session.delete(lane)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise LaneError(409, NOT_EMPTY_MESSAGE) from error
    return await effective_lanes(session)
