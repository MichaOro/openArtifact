"""The sources of the Build Context node (ADR-078): what a package can be made of, as data.

A node of the kind ``context`` holds a list of sources, ``[{"source": "comments", "count": 20}, ...]``; the order is the priority when the
size limit runs out. This module is the one place that says which sources exist, which options each has and how a stored list is
checked; the engine (``engine/context_builder.py``) builds from it, the editor draws it (``Setting.describe`` carries ``sources``) and
the settings API validates with :func:`sources_error` / :func:`normalise`.

Options: ``count`` (a whole number within bounds: how many items), ``detail`` (``title`` or ``text``: a related card as one line, or with
its text), ``names`` (a list of names of nodes of this run; ``handovers`` may name none: all documents). A source can be there once;
``nodes`` names its nodes inside.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: The most sources a node holds and the most node names ``nodes`` may name.
MAX_SOURCES = 9
MAX_NAMES = 10
MAX_NAME_CHARS = 200

DETAIL_TITLE = "title"
DETAIL_TEXT = "text"
DETAILS = (DETAIL_TITLE, DETAIL_TEXT)
DEFAULT_DETAIL = DETAIL_TITLE


@dataclass(frozen=True)
class SourceSpec:
    """One source: its key, the words the editor shows and the options it takes."""

    key: str
    label: str
    help: str
    #: ``(minimum, maximum, default)`` of ``count``, or ``None`` (the source has no count).
    count: tuple[int, int, int] | None = None
    #: The source takes ``detail`` (a related card: title only, or title and text).
    detail: bool = False
    #: The source takes ``names`` (the nodes of the run whose results are used).
    names: bool = False

    def describe(self) -> dict[str, Any]:
        data: dict[str, Any] = {"key": self.key, "label": self.label, "help": self.help}
        if self.count is not None:
            data["count"] = list(self.count)
        if self.detail:
            data["detail"] = list(DETAILS)
        if self.names:
            data["names"] = {"max": MAX_NAMES, "max_chars": MAX_NAME_CHARS}
        return data


SOURCES: dict[str, SourceSpec] = {
    spec.key: spec
    for spec in (
        SourceSpec(
            "card",
            "Title and body",
            "The number, the title and the text of the card the run belongs to. It is reserved first: when space is short, the other "
            "sources give way before this one is cut.",
        ),
        SourceSpec(
            "fields",
            "Fields",
            "The values of the card's own fields (name and value, one per line); a field nobody filled is left out.",
        ),
        SourceSpec(
            "comments",
            "Comments",
            "The newest comments of the card, oldest of them first; older ones are left out first, and the package says how many.",
            count=(1, 100, 20),
        ),
        SourceSpec(
            "parent",
            "Parent card",
            "The card this card belongs to, if it has one (archived cards are not used).",
            detail=True,
        ),
        SourceSpec(
            "children",
            "Child cards",
            "The cards that belong to this card, by number; the last ones are left out first (archived cards are not used).",
            count=(1, 50, 20),
            detail=True,
        ),
        SourceSpec(
            "siblings",
            "Sibling cards",
            "The other cards of the same parent, by number; the last ones are left out first (archived cards are not used).",
            count=(1, 50, 20),
            detail=True,
        ),
        SourceSpec(
            "nodes",
            "Results of earlier nodes",
            "The output of nodes of this run that already ran, picked by their name (a node of this run's actions). A node that "
            "has not run is listed as left out. The run keeps at most 4 KiB of a node's output.",
            names=True,
        ),
        SourceSpec(
            "handovers",
            "Handover documents",
            "The documents agents handed over in this run through a Hand Over Tool, as fields and values. Name the tool nodes to use "
            "only those; none named means all of them, oldest first.",
            names=True,
        ),
        SourceSpec(
            "executions",
            "Earlier executions",
            "The last finished executions of this card (not the running one): how each ended, why, and the output of its last "
            "step that produced text. Older ones are left out first.",
            count=(1, 10, 3),
        ),
    )
}

#: The sources a new node starts with.
DEFAULT_SOURCES: list[dict[str, Any]] = [{"source": "card"}, {"source": "comments", "count": 20}]


def describe() -> dict[str, Any]:
    """What the editor needs to draw the setting: the sources, in the order of the menu, and the bound of the list."""
    return {"sources": [s.describe() for s in SOURCES.values()], "max_sources": MAX_SOURCES}


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def sources_error(value: Any) -> str | None:
    """Why ``value`` is no list of sources (plain words), or ``None``."""
    try:
        normalise(value)
    except ValueError as error:
        return str(error)
    return None


def normalise(value: Any) -> list[dict[str, Any]]:
    """The list as it is stored (every option present for the source that takes it); :class:`ValueError` with a plain message."""
    if not isinstance(value, list):
        raise ValueError("The sources must be a list")
    if len(value) > MAX_SOURCES:
        raise ValueError(f"At most {MAX_SOURCES} sources")
    seen: set[str] = set()
    stored: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("Every source must be an object with a 'source'")
        key = item.get("source")
        spec = SOURCES.get(key) if isinstance(key, str) else None
        if spec is None:
            raise ValueError(f"Unknown source {str(key)[:40]!r}: use {', '.join(SOURCES)}")
        if key in seen:
            raise ValueError(f"The source '{spec.label}' is there twice; it can be used once")
        seen.add(spec.key)
        allowed = (
            {"source"}
            | ({"count"} if spec.count else set())
            | ({"detail"} if spec.detail else set())
        )
        allowed |= {"names"} if spec.names else set()
        extra = sorted(set(item) - allowed)
        if extra:
            raise ValueError(f"'{spec.label}' has no option '{extra[0][:40]}'")
        entry: dict[str, Any] = {"source": spec.key}
        if spec.count is not None:
            low, high, default = spec.count
            count = item.get("count", default)
            if not _whole(count) or not low <= count <= high:
                raise ValueError(f"'{spec.label}': the number of items is {low} to {high}")
            entry["count"] = count
        if spec.detail:
            detail = item.get("detail", DEFAULT_DETAIL)
            if detail not in DETAILS:
                raise ValueError(f"'{spec.label}': detail is one of {', '.join(DETAILS)}")
            entry["detail"] = detail
        if spec.names:
            names = item.get("names", [])
            if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                raise ValueError(f"'{spec.label}': the names are a list of texts")
            cleaned = [n.strip() for n in names if n.strip()]
            if len(cleaned) > MAX_NAMES:
                raise ValueError(f"'{spec.label}': at most {MAX_NAMES} nodes")
            if any(len(n) > MAX_NAME_CHARS or "\x00" in n for n in cleaned):
                raise ValueError(f"'{spec.label}': a name is at most {MAX_NAME_CHARS} characters")
            if len(set(cleaned)) != len(cleaned):
                raise ValueError(f"'{spec.label}': a node is named twice")
            entry["names"] = cleaned
        stored.append(entry)
    return stored
