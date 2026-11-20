"""Board lanes: the single place that defines which lanes exist, their order and titles.

Today the lanes are fixed and map 1:1 to :class:`~openartifact.models.TaskStatus`. The UI
never hard-codes lanes: the page renders them from :data:`BOARD_LANES` and the frontend reads
them back from the DOM (``[data-lane]``). User-defined lanes later replace this constant with
data from the database (a ``lanes`` table that ``tasks`` references instead of the CHECK
constraint of migration 0003); see ADR-011.
"""

from __future__ import annotations

from dataclasses import dataclass

from openartifact.models import TaskStatus


@dataclass(frozen=True, slots=True)
class Lane:
    """One column of the board."""

    status: TaskStatus
    title: str

    @property
    def key(self) -> str:
        """DOM-friendly identifier (``in-progress``)."""
        return self.status.value.replace("_", "-")


BOARD_LANES: tuple[Lane, ...] = (
    Lane(TaskStatus.BACKLOG, "Backlog"),
    Lane(TaskStatus.IN_PROGRESS, "In Progress"),
    Lane(TaskStatus.DONE, "Done"),
)
