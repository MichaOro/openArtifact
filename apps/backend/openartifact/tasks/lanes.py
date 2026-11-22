"""Board lanes: the single place that defines which lanes exist, their order and titles.

Today the lanes are fixed and map 1:1 to :class:`~openartifact.models.TaskStatus`; only their titles
can be changed (table ``lane_titles``, overrides of the defaults below). The UI
never hard-codes lanes: the page renders them from :data:`BOARD_LANES` and the frontend reads
them back from the DOM (``[data-lane]``). User-defined lanes later replace this constant with
data from the database (a ``lanes`` table that ``tasks`` references instead of the CHECK
constraint of migration 0003); see ADR-011.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models import LaneTitle, TaskStatus
from openartifact.tasks.schemas import LaneRead


@dataclass(frozen=True, slots=True)
class Lane:
    """One column of the board."""

    status: TaskStatus
    title: str

    @property
    def key(self) -> str:
        """DOM-friendly identifier (``in-progress``)."""
        return self.status.value.replace("_", "-")


#: Number of hues in the lane palette (tokens.css: --lane-hue-1 … --lane-hue-N). Lane N uses hue N,
#: cycling when there are more lanes than hues.
LANE_HUES = 8

BOARD_LANES: tuple[Lane, ...] = (
    Lane(TaskStatus.BACKLOG, "Backlog"),
    Lane(TaskStatus.IN_PROGRESS, "In Progress"),
    Lane(TaskStatus.DONE, "Done"),
)


TITLE_MAX_LENGTH = 40


class LaneTitleError(ValueError):
    """A lane title that cannot be used (the message says why)."""


def clean_title(value: str | None) -> str | None:
    """The title as stored: trimmed; ``None`` for nothing. Raises :class:`LaneTitleError` if invalid."""
    if value is None or not value.strip():
        return None
    title = value.strip()
    if len(title) > TITLE_MAX_LENGTH:
        raise LaneTitleError(f"A lane title has at most {TITLE_MAX_LENGTH} characters.")
    if any(unicodedata.category(c).startswith("C") for c in title):
        raise LaneTitleError("A lane title must not contain control characters.")
    return title


async def effective_lanes(session: AsyncSession) -> list[LaneRead]:
    """The lanes as shown: the defaults of :data:`BOARD_LANES` with the titles the user changed."""
    overrides = dict((await session.execute(select(LaneTitle.status, LaneTitle.title))).all())
    return [
        LaneRead(
            status=lane.status,
            key=lane.key,
            title=overrides.get(lane.status.value, lane.title),
            default_title=lane.title,
            hue=index % LANE_HUES + 1,
        )
        for index, lane in enumerate(BOARD_LANES)
    ]


async def rename_lane(
    session: AsyncSession, status: TaskStatus, title: str | None
) -> list[LaneRead]:
    """Give a lane its own title, or (``None``, empty, or its default text) back its default.

    Raises :class:`LaneTitleError` for an invalid title or one another lane already has (ignoring case).
    """
    chosen = clean_title(title)
    lanes = await effective_lanes(session)
    current = next(lane for lane in lanes if lane.status == status)
    shown = chosen or current.default_title
    for other in lanes:
        if other.status != status and other.title.casefold() == shown.casefold():
            raise LaneTitleError(f'Another lane is already called "{other.title}".')
    row = await session.get(LaneTitle, status.value)
    if shown == current.default_title:
        if row is not None:
            await session.delete(row)
    elif row is None:
        session.add(LaneTitle(status=status.value, title=shown))
    else:
        row.title = shown
    await session.commit()
    return await effective_lanes(session)
