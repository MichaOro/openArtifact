"""The Build Context node (ADR-078): assembles one package of text for an agent from the card, its neighbours and earlier results.

The node holds an ordered list of *sources* (``graph/context_sources.py``) and a size limit in bytes. This module reads what the sources
name, then :func:`assemble` makes the package with fixed, documented rules, and says exactly what went in and what was left out:

- **The order is the priority.** Sources are added in the order the user gave, each as a section ``## <label>``; what does not fit is
  left out, never silently: the section says how many items were left out, and ``data.omitted`` says why a whole source is missing.
- **The card is reserved first** (the number, the title and the text): the other sources give way before it is cut, and it is the only
  thing that is cut inside an item. It keeps its place in the order.
- **Items are whole.** A source that does not fit is shortened by items: comments and earlier executions drop the oldest first (a line
  ``[... 12 older comments left out]`` stands in front), related cards, fields and nodes drop the last first (a line at the end). An item
  longer than ``item_limit`` bytes is cut with a visible mark ``…[cut]`` before it is weighed, and ``data`` counts those.
- **The package never exceeds the limit** (headings, markers and separators included); ``size_bytes`` is what it takes.
- **The text of cards, comments and results is untrusted.** It is pasted as it is, never read for ``${...}`` references, so a card that
  holds ``${secret:X}`` puts those characters into the package, not a secret. The section headings say where a source starts; a card can
  still write a line that looks like a heading, so the package is data for the agent, not instructions.

Everything here is a pure function of what the gateways gave; the only IO is :func:`run_context` reading through them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from openartifact.comments.schemas import CommentRead
from openartifact.engine.artifact_runner import CommentsGateway
from openartifact.engine.context import BUILT_IN_CARD, ContextError, RunView, card_text, node_key
from openartifact.engine.results import NodeResult, failed
from openartifact.exceptions import ArtifactError
from openartifact.graph import context_sources as sources

#: The size limit of the package in bytes (UTF-8): the setting's bounds and default (the manifest says the same; a test keeps them equal).
LIMIT_MIN, LIMIT_MAX, LIMIT_DEFAULT = 1024, 32 * 1024, 8 * 1024
#: The longest one item may be before it is cut (bytes), the bounds and default of the setting ``item_limit``.
ITEM_MIN, ITEM_MAX, ITEM_DEFAULT = 256, 16 * 1024, 2 * 1024
CUT_MARK = "…[cut]"
#: Rough size of a token in bytes of English text: only for the hint (``approx_tokens``), never for a decision.
BYTES_PER_TOKEN = 4
SEPARATOR = "\n\n"


# ── what the gateways give ───────────────────────────────────────────


@dataclass(frozen=True)
class CardInfo:
    """A card as a source shows it."""

    number: int | None
    title: str
    body: str
    lane: str | None = None


@dataclass(frozen=True)
class PastExecution:
    """A finished execution of the card: how it ended and the output of its last step that produced text."""

    number: int
    status: str
    note: str | None
    started_by: str
    pipeline: str
    started_at: datetime
    last_step: str | None = None
    last_output: str = ""


class CardsGateway(Protocol):
    """What the node needs of the cards and the history (a protocol: the services import the engine)."""

    async def parent(self, task_id: str) -> CardInfo | None: ...

    async def children(self, task_id: str, limit: int) -> tuple[list[CardInfo], int]:
        """The first ``limit`` children by number (not archived) and how many there are in all."""
        ...

    async def siblings(self, task_id: str, limit: int) -> tuple[list[CardInfo], int]:
        """The first ``limit`` other children of the parent by number (not archived) and how many there are in all."""
        ...

    async def comment_count(self, task_id: str) -> int:
        """How many comments the card has in all."""
        ...

    async def executions(
        self, task_id: str, exclude: str | None, newest: int
    ) -> tuple[list[PastExecution], int]:
        """The newest ``newest`` finished executions, oldest of them first, and how many finished ones there are in all."""
        ...


# ── bytes ────────────────────────────────────────────────────────────


def size(text: str) -> int:
    return len(text.encode("utf-8"))


def cut_to(text: str, limit: int, mark: str = CUT_MARK) -> tuple[str, bool]:
    """``text`` within ``limit`` bytes (never half a character) and whether it was cut; a cut text ends with ``mark``."""
    if size(text) <= limit:
        return text, False
    room = max(limit - size(mark), 0)
    kept = text.encode("utf-8")[:room].decode("utf-8", errors="ignore")
    return kept + mark, True


# ── sections ─────────────────────────────────────────────────────────


@dataclass
class Section:
    """What one source offers: its items in order, how many there are in all and how the section reads."""

    key: str
    label: str
    items: list[str]
    #: How many items the source has in all (more than ``items`` when the user's count or the gateway's limit held some back).
    available: int
    #: ``newest``: the items are oldest first and the oldest are left out first; ``first``: the last are left out first.
    drop: str = "first"
    #: What the left-out items are called in the marker line ("comment", "child card"): singular.
    noun: str = "item"
    #: Between two items: a blank line for blocks, a line break for one-line items.
    joiner: str = SEPARATOR
    #: Items cut at the item limit (counted for the data).
    cut: int = 0
    #: The source has nothing to give: why (shown in ``omitted``).
    empty: str | None = None
    #: Items that could not be offered at all, with the reason (a node that has not run).
    skipped: list[str] = field(default_factory=list)


def _plural(count: int, noun: str) -> str:
    return noun if count == 1 else f"{noun}s"


def _text_of(section: Section, taken: int) -> str:
    """The section's text with ``taken`` of its items (the newest or the first ones), the heading and the marker line."""
    gone = section.available - taken
    chosen = (
        section.items[len(section.items) - taken :]
        if section.drop == "newest"
        else section.items[:taken]
    )
    parts = list(chosen)
    if gone > 0:
        if section.drop == "newest":
            parts.insert(0, f"[... {gone} older {_plural(gone, section.noun)} left out]")
        else:
            parts.append(f"[... {gone} more {_plural(gone, section.noun)} left out]")
    heading = f"## {section.label}"
    if gone > 0:
        order = ", oldest first" if section.drop == "newest" else ""
        heading += f" ({taken} of {section.available}{order})"
    return heading + SEPARATOR + section.joiner.join(parts)


@dataclass
class Package:
    text: str
    included: list[dict[str, Any]]
    omitted: list[dict[str, str]]

    @property
    def size_bytes(self) -> int:
        return size(self.text)


def _card_section_text(card: Section, room: int) -> tuple[str, bool]:
    """The card's section within ``room`` bytes; when it does not fit, the end of the text is cut (with the mark)."""
    whole = f"## {card.label}" + SEPARATOR + card.items[0]
    return cut_to(whole, room)


def assemble(
    order: Sequence[str], sections: Mapping[str, Section], limit: int
) -> tuple[Package, list[dict[str, str]]]:
    """Make the package from the sections (``order`` is the user's order) within ``limit`` bytes.

    Returns the package and, for what is not in it, ``{"source", "reason"}``. The card section is reserved first; the others are weighed
    in the user's order against what is left (separators counted).
    """
    texts: dict[str, str] = {}
    taken: dict[str, int] = {}
    omitted: list[dict[str, str]] = []
    remaining = limit
    cut_card = False
    card = sections.get("card")
    if card is not None and card.items:
        text, cut_card = _card_section_text(card, remaining)
        texts["card"], taken["card"] = text, 1
        remaining -= size(text)
    for key in order:
        section = sections.get(key)
        if section is None:
            continue
        omitted += [{"source": key, "reason": reason} for reason in section.skipped]
        if key == "card" and key in texts:
            continue
        if not section.items:
            if not section.skipped:
                omitted.append(
                    {"source": key, "reason": section.empty or "there was nothing to include"}
                )
            continue
        room = remaining - size(SEPARATOR)
        best = next(
            (n for n in range(len(section.items), 0, -1) if size(_text_of(section, n)) <= room), 0
        )
        if best == 0:
            need = size(_text_of(section, 1))
            omitted.append(
                {
                    "source": key,
                    "reason": f"it did not fit: its first item needs {need} bytes and {max(room, 0)} are left",
                }
            )
            continue
        texts[key], taken[key] = _text_of(section, best), best
        remaining -= size(texts[key]) + size(SEPARATOR)
    package = Package(SEPARATOR.join(texts[k] for k in order if k in texts), [], omitted)
    for key in order:
        section = sections.get(key)
        if key not in texts or section is None:
            continue
        package.included.append(
            {
                "source": key,
                "label": section.label,
                "items": taken[key],
                "available": section.available,
                "bytes": size(texts[key]),
                "cut": int(cut_card) if key == "card" else section.cut,
            }
        )
    return package, omitted


# ── reading the sources ──────────────────────────────────────────────


def _at(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M")


def _card_line(card: CardInfo) -> str:
    lane = f" ({card.lane})" if card.lane else ""
    return f"#{card.number} {card.title}{lane}".rstrip()


def _card_block(card: CardInfo, detail: str, item_limit: int) -> tuple[str, bool]:
    line = _card_line(card)
    body = (card.body or "").strip()
    if detail == sources.DETAIL_TEXT and body:
        return cut_to(f"{line}\n\n{body}", item_limit)
    return cut_to(line, item_limit)


def _comment_block(comment: CommentRead, item_limit: int) -> tuple[str, bool]:
    text = f"[{_at(comment.created_at)}] {comment.author} ({comment.author_kind}):\n{comment.body.strip()}"
    return cut_to(text, item_limit)


def _execution_block(past: PastExecution, item_limit: int) -> tuple[str, bool]:
    lines = [
        f"#{past.number} {past.status}, {_at(past.started_at)}, started by {past.started_by}"
        + (f', pipeline "{past.pipeline}"' if past.pipeline else "")
    ]
    if past.note:
        lines.append(f"Note: {past.note.strip()}")
    if past.last_output.strip():
        lines.append(f"Last result ({past.last_step or 'a step'}):\n{past.last_output.strip()}")
    return cut_to("\n".join(lines), item_limit)


def _card_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _handover_block(entry: Mapping[str, Any]) -> str:
    """A handed-over document as text: the name of its tool node, then one ``field: value`` line per field (pasted as it is)."""
    data = entry.get("data") if isinstance(entry.get("data"), Mapping) else {}
    lines = [f"{name}: {_card_value(value)}" for name, value in (data or {}).items()]
    return f"### {entry.get('name')}\n" + ("\n".join(lines) if lines else "(empty)")


def _blocks(
    section: Section, made: Sequence[tuple[str, bool]], available: int | None = None
) -> Section:
    section.items = [text for text, _ in made]
    section.cut = sum(1 for _, was_cut in made if was_cut)
    section.available = len(made) if available is None else max(available, len(made))
    return section


async def read_sources(
    chosen: Sequence[Mapping[str, Any]],
    *,
    view: RunView,
    cards: CardsGateway | None,
    comments: CommentsGateway | None,
    item_limit: int,
) -> dict[str, Section]:
    """Read every chosen source into a section (the only IO of the node); :class:`ArtifactError` / :class:`ContextError` fail it."""
    found: dict[str, Section] = {}
    task = view.task_id
    card = view.context.card
    for entry in chosen:
        key = str(entry["source"])
        spec = sources.SOURCES[key]
        section = Section(key, spec.label, [], 0)
        found[key] = section
        if key not in {"nodes", "handovers"} and not card and not task:
            section.empty = "the run has no card"
            continue
        if key in {"comments", "parent", "children", "siblings", "executions"} and not task:
            section.empty = "the run has no card"
            continue
        if key == "card":
            if "title" not in card:
                section.empty = "the run has no card"
                continue
            section.items = [card_text(card)]
            section.available = 1
        elif key == "fields":
            lines = [
                f"{name}: {text}"
                for name, value in card.items()
                if name not in BUILT_IN_CARD and (text := _card_value(value))
            ]
            _blocks(section, [cut_to(line, item_limit) for line in lines])
            section.joiner, section.noun = "\n", "field"
            section.empty = "the card has no field with a value"
        elif key == "comments":
            if comments is None or not task:
                raise ArtifactError(400, "Comments are not available here")
            newest = await comments.comments(task, int(entry["count"]))
            total = await cards.comment_count(task) if cards is not None else len(newest)
            _blocks(section, [_comment_block(c, item_limit) for c in newest], total)
            section.drop, section.noun = "newest", "comment"
            section.empty = "the card has no comments"
        elif key == "parent":
            gateway = _need(cards)
            parent = await gateway.parent(str(task))
            if parent is None:
                section.empty = "the card has no parent"
            else:
                _blocks(section, [_card_block(parent, str(entry["detail"]), item_limit)])
        elif key in {"children", "siblings"}:
            gateway = _need(cards)
            read = gateway.children if key == "children" else gateway.siblings
            related, total = await read(str(task), int(entry["count"]))
            _blocks(
                section,
                [_card_block(c, str(entry["detail"]), item_limit) for c in related],
                total,
            )
            section.noun = "child card" if key == "children" else "sibling card"
            section.joiner = "\n" if entry["detail"] == sources.DETAIL_TITLE else SEPARATOR
            section.empty = (
                "the card has no child cards"
                if key == "children"
                else "the card has no sibling cards"
            )
        elif key == "nodes":
            made: list[tuple[str, bool]] = []
            for name in entry["names"]:
                result = view.context.nodes.get(node_key(name))
                if result is None:
                    section.skipped.append(f'the node "{name}" has not run in this execution')
                    continue
                kept = str(result.get("output") or "").strip() or "(no output)"
                mark = " [output was cut by the run]" if result.get("truncated") else ""
                head = f"### {result.get('name', name)} ({result.get('kind')}, {result.get('outcome')})"
                made.append(cut_to(f"{head}\n{kept}{mark}", item_limit))
            _blocks(section, made)
            section.noun = "node"
            section.empty = (
                "no node is named"
                if not entry["names"]
                else "none of the named nodes has run in this execution"
            )
        elif key == "handovers":
            wanted = {node_key(n) for n in entry["names"]}
            documents = [
                (found_key, found_entry)
                for found_key, found_entry in view.context.nodes.items()
                if found_entry.get("kind") == "handover_tool"
                and (not wanted or found_key in wanted)
            ]
            for name in entry["names"]:
                if node_key(name) not in {k for k, _ in documents}:
                    section.skipped.append(
                        f'nothing was handed over under the name "{name}" in this execution'
                    )
            _blocks(section, [cut_to(_handover_block(e), item_limit) for _, e in documents])
            section.noun = "document"
            section.empty = "no document was handed over in this execution"
        elif key == "executions":
            gateway = _need(cards)
            past, total = await gateway.executions(
                str(task), view.execution_id, int(entry["count"])
            )
            _blocks(section, [_execution_block(p, item_limit) for p in past], total)
            section.drop, section.noun = "newest", "execution"
            section.empty = "the card has no earlier finished execution"
    return found


def _need(cards: CardsGateway | None) -> CardsGateway:
    if cards is None:
        raise ArtifactError(400, "The cards are not available here")
    return cards


# ── the node ─────────────────────────────────────────────────────────


def _bounded(value: Any, low: int, high: int, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return min(max(value, low), high)
    return default


async def run_context(
    config: Mapping[str, Any],
    *,
    view: RunView,
    cards: CardsGateway | None,
    comments: CommentsGateway | None,
) -> NodeResult:
    """Build the package the node's sources and limit describe; the result's ``output`` is the package, ``data`` says what is in it."""
    stored = config.get("sources")
    try:  # a node whose list was never saved builds from the sources a new node shows (the setting's default)
        chosen = sources.normalise(sources.DEFAULT_SOURCES if stored is None else stored)
    except ValueError as error:
        return failed(str(error))
    if not chosen:
        return failed("No source is chosen: add at least one source to build a package from")
    limit = _bounded(config.get("size_limit"), LIMIT_MIN, LIMIT_MAX, LIMIT_DEFAULT)
    item_limit = _bounded(config.get("item_limit"), ITEM_MIN, ITEM_MAX, ITEM_DEFAULT)
    try:
        found = await read_sources(
            chosen, view=view, cards=cards, comments=comments, item_limit=item_limit
        )
    except (ArtifactError, ContextError) as error:
        return failed(getattr(error, "message", str(error)))
    order = [str(e["source"]) for e in chosen]
    package, left_out = assemble(order, found, limit)
    data = {
        "included": package.included,
        "omitted": left_out,
        "size_bytes": package.size_bytes,
        "limit_bytes": limit,
        "approx_tokens": math.ceil(package.size_bytes / BYTES_PER_TOKEN),
    }
    result = NodeResult("pass", output=package.text, data=data, keep_bytes=limit)
    if not package.text:
        result.reason = "Nothing was included: " + "; ".join(
            f"{o['source']}: {o['reason']}" for o in left_out
        )
        result.__post_init__()
    return result
