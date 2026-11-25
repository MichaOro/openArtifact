"""The body of an artifact with its ``${card.x}`` references filled in (ADR-064 addendum).

Only the original text is stored. A reader gets the finished text: the artifact dialog when a card is opened,
the preview on the board, the card a run starts with. One pure function does it, so the three agree.

What is filled in: ``${card.title}``, ``${card.number}``, ``${card.id}`` and ``${card.<field>}`` of the artifact's
own fields. What is left as written, never raised on: ``${card.body}`` and ``${card.text}`` (a body cannot contain
itself), ``${node...}``, ``${var...}``, ``${secret:...}``, a name the artifact does not have, anything malformed. One
level only: a field value that itself holds ``${...}`` is not filled in again.

Performance: with a word budget (the board's preview) the text is read token by token and reading stops when the
budget is spent, so a body of ten thousand words costs what a short one does. A body without ``${card.`` is not
scanned for references at all.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
from typing import Any

#: The words of a card's preview on the board. The board used to show the whole body and let CSS cut it after six
#: lines; this is what those six lines can hold with room to spare (about forty words), so the card looks as before.
PREVIEW_WORDS = 60
#: The marker of a preview that was cut.
ELLIPSIS = "…"

_MARK = "${card."
#: What a body reads as, token by token: a run of text, a card reference, a lone ``$``, or white space.
_TOKEN = re.compile(r"\$\{card\.([a-z][a-z0-9_]{0,31})\}|[^\s$]+|\$|\s+")
#: What a body must not contain of itself, and what is built into every artifact.
SELF_NAMES = frozenset({"body", "text"})


def render_value(value: Any) -> str:
    """A value as text the way ``${card.x}`` renders elsewhere: text as it is, an empty field as empty text,
    everything else as compact JSON (``3``, ``1.5``, ``true``)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def has_references(body: str | None) -> bool:
    """Whether the body may hold a card reference (a cheap substring test, no scan)."""
    return body is not None and _MARK in body


def _value_of(name: str, card: Mapping[str, Any]) -> tuple[bool, str]:
    """``(known, text)`` for a card reference of a body."""
    if name in SELF_NAMES or name not in card:
        return False, ""
    return True, render_value(card[name])


class _Budget:
    """The words that may still be written; counts words across the pieces that are written one after another."""

    def __init__(self, words: int | None) -> None:
        self.left = words
        self.in_word = False
        self.cut = False

    @property
    def spent(self) -> bool:
        return self.cut

    def write(self, out: list[str], text: str) -> None:
        """Append as much of ``text`` as the budget allows (whole pieces of white space and words)."""
        if self.left is None:
            out.append(text)
            return
        for piece in re.finditer(r"\S+|\s+", text):
            token = piece[0]
            if token.isspace():
                if self.in_word:
                    self.in_word = False
                out.append(token)
                continue
            if not self.in_word:
                if self.left <= 0:
                    self.cut = True
                    return
                self.left -= 1
                self.in_word = True
            out.append(token)


def _walk(body: str, card: Mapping[str, Any], words: int | None) -> tuple[str, int, bool]:
    """``(text, substitutions, cut)`` of ``body``; with ``words`` it stops reading when the budget is spent."""
    out: list[str] = []
    budget = _Budget(words)
    done = 0
    for match in _TOKEN.finditer(body):
        name = match[1]
        if name is None:
            budget.write(out, match[0])
        else:
            known, text = _value_of(name, card)
            if known:
                done += 1
                budget.write(out, text)
            else:
                budget.write(out, match[0])
        if budget.spent:
            break
    text = "".join(out)
    if budget.cut:
        text = text.rstrip() + ELLIPSIS
    return text, done, budget.cut


def resolve_body(body: str | None, card: Mapping[str, Any], max_words: int | None = None) -> str:
    """The body with its card references filled in from ``card`` (title, number, id and the field values).

    ``max_words``: only the first words are wanted (the board's preview); a long value is cut to what is left and a
    cut text ends with an ellipsis. Never raises; ``None`` is the empty text.
    """
    if not body:
        return ""
    try:
        if _MARK not in body and max_words is None:
            return body
        return _walk(body, card, max_words)[0]
    except Exception:  # a body must never break a read: show it as it was written
        return body


def resolve_body_segments(
    body: str | None, card: Mapping[str, Any], max_words: int | None = None
) -> list[dict[str, Any]]:
    """The body as a list of segments: each is ``{"text": str, "resolved": bool}``.

    A segment with ``resolved=True`` came from a ``${card.x}`` reference; ``resolved=False`` is original text.
    ``max_words`` limits output (for preview); stops at word boundary with ellipsis on the last segment.

    Never raises; on error returns a single segment with the original body and ``resolved=False``.
    """
    if not body:
        return [{"text": "", "resolved": False}]
    try:
        if _MARK not in body and max_words is None:
            return [{"text": body, "resolved": False}]
        return _walk_segments(body, card, max_words)
    except Exception:
        return [{"text": body, "resolved": False}]


def _walk_segments(body: str, card: Mapping[str, Any], words: int | None) -> list[dict[str, Any]]:
    """``(segments, substitutions, cut)`` of ``body``; segments are ``{"text": str, "resolved": bool}``.

    Uses the same word budget logic as _walk: stops when budget is spent.
    """
    segments: list[dict[str, Any]] = []
    budget = _Budget(words)
    done = 0

    current_text: list[str] = []
    current_resolved: bool | None = None

    def flush():
        nonlocal current_text, current_resolved
        if current_text:
            segments.append({"text": "".join(current_text), "resolved": current_resolved})
            current_text = []
            current_resolved = None

    def add_text(text: str, resolved: bool) -> bool:
        """Add text through budget.write() to track word count correctly (same as _walk).
        Returns True if budget was spent and processing should stop.
        """
        nonlocal current_text, current_resolved
        if current_resolved is not None and current_resolved != resolved:
            flush()
        current_resolved = resolved

        dummy_out: list[str] = []
        # Always call budget.write - it handles unlimited budget (left is None) correctly
        if budget.left is not None:
            budget.write(dummy_out, text)
        else:
            # No budget limit - everything passes through
            dummy_out.append(text)

        if dummy_out:
            current_text.append("".join(dummy_out))

        return budget.spent

    try:
        for match in _TOKEN.finditer(body):
            name = match[1]
            token = match[0]
            if name is None:
                # Plain text (word, whitespace, or lone $)
                if add_text(token, False):
                    break
            else:
                # Card reference
                known, text = _value_of(name, card)
                if known:
                    done += 1
                    if add_text(text, True):
                        break
                else:
                    # Unknown reference - treat as plain text
                    if add_text(token, False):
                        break
    except StopIteration:
        pass

    flush()

    if budget.cut and segments:
        # Add ellipsis to the last segment
        last = segments[-1]
        last["text"] = last["text"].rstrip() + ELLIPSIS

    return segments


def resolved_or_none(body: str | None, card: Mapping[str, Any]) -> str | None:
    """The full resolved body, or ``None`` when nothing in it was filled in (the reader then shows the body)."""
    if not has_references(body):
        return None
    try:
        text, done, _ = _walk(body or "", card, None)
    except Exception:
        return None
    return text if done else None


def preview_or_none(
    body: str | None, card: Mapping[str, Any], words: int = PREVIEW_WORDS
) -> str | None:
    """The resolved first ``words`` words for the board, or ``None`` when the body holds no reference (the client
    then cuts the original as it always did)."""
    if not has_references(body):
        return None
    return resolve_body(body, card, words)


def unknown_references(body: str | None, known: Collection[str]) -> list[str]:
    """The references of a body that cannot be filled in, each with why, for the calm warning when it is saved."""
    if not has_references(body):
        return []
    names = set(known)
    problems: list[str] = []
    for match in re.finditer(r"\$\{card\.([a-z][a-z0-9_]{0,31})\}", body or ""):
        name = match[1]
        if name in SELF_NAMES:
            problems.append(
                f"{match[0]}: a body cannot contain itself, so this is shown as written"
            )
        elif name not in names:
            problems.append(f"{match[0]}: the artifact has no field '{name}'")
    return list(dict.fromkeys(problems))
