"""The body of an artifact with its ${card.x} references filled in (openartifact/artifact_fields/body.py)."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from typing import Any

import pytest

from openartifact.artifact_fields import body as body_module
from openartifact.artifact_fields.body import (
    ELLIPSIS,
    PREVIEW_WORDS,
    has_references,
    preview_or_none,
    render_value,
    resolve_body,
    resolved_or_none,
    unknown_references,
)
from openartifact.engine import context

CARD: dict[str, Any] = {
    "id": "7a1c0000-0000-4000-8000-000000000000",
    "number": 98,
    "title": "Der letzte Leuchtturm",
    "epic_url": "https://example.org/e/1",
    "priority": 3,
    "ratio": 1.5,
    "needs_review": True,
    "level": "high",
    "empty": None,
    "test": "Als Elias erwachte",
}


def test_the_built_in_names_and_every_kind_of_field_are_filled_in() -> None:
    text = (
        "${card.title} (#${card.number}) ${card.id} / ${card.epic_url} ${card.priority} "
        "${card.ratio} ${card.needs_review} ${card.level} ${card.test}"
    )
    assert resolve_body(text, CARD) == (
        "Der letzte Leuchtturm (#98) 7a1c0000-0000-4000-8000-000000000000 / https://example.org/e/1 3 "
        "1.5 true high Als Elias erwachte"
    )


def test_an_empty_field_is_empty_text_not_null() -> None:
    assert resolve_body("[${card.empty}]", CARD) == "[]"


@pytest.mark.parametrize("value", ["text", 3, 1.5, True, False, None, "ä ö", 0])
def test_a_value_renders_the_way_references_render_elsewhere(value: Any) -> None:
    shown = render_value(value)
    assert shown == ("" if value is None else context._render(value))


def test_a_name_the_artifact_does_not_have_is_left_as_written() -> None:
    assert resolve_body("a ${card.nope} b", CARD) == "a ${card.nope} b"


@pytest.mark.parametrize("name", ["body", "text"])
def test_a_body_cannot_contain_itself(name: str) -> None:
    card = {**CARD, "body": "x", "text": "y"}
    assert resolve_body(f"before ${{card.{name}}} after", card) == f"before ${{card.{name}}} after"


def test_node_var_secret_and_malformed_references_are_never_touched() -> None:
    text = "${(Fetch).output} ${node.X.output} ${var.v} ${secret:API_KEY} ${card.} ${card.Title} ${card.title"
    assert resolve_body(text, CARD) == text


def test_only_one_level_is_filled_in() -> None:
    card = {**CARD, "test": "${card.title}"}
    assert resolve_body("${card.test}", card) == "${card.title}"


def test_none_and_empty_bodies_are_empty_text() -> None:
    assert resolve_body(None, CARD) == "" and resolve_body("", CARD) == ""


def test_the_function_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        def finditer(self, *_: Any) -> Iterator[Any]:
            raise RuntimeError("boom")

    monkeypatch.setattr(body_module, "_TOKEN", Broken())
    assert resolve_body("a ${card.title}", CARD) == "a ${card.title}"
    assert resolved_or_none("a ${card.title}", CARD) is None


def test_resolved_or_none_is_none_when_nothing_was_filled_in() -> None:
    assert resolved_or_none("no reference here", CARD) is None
    assert resolved_or_none("${card.nope} and ${card.body}", CARD) is None
    assert resolved_or_none("${card.title}", CARD) == "Der letzte Leuchtturm"


def test_a_body_without_the_mark_is_not_scanned_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    class Counting:
        def finditer(self, text: str) -> Iterator[Any]:
            nonlocal calls
            calls += 1
            return iter(())

    monkeypatch.setattr(body_module, "_TOKEN", Counting())
    assert resolve_body("a plain body " * 1000, CARD) == "a plain body " * 1000
    assert resolved_or_none("a plain body " * 1000, CARD) is None
    assert not has_references("a plain body")
    assert calls == 0


# ── the preview: a word budget ───────────────────────────────────────


def _count_tokens(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    seen = [0]
    real = body_module._TOKEN

    class Counting:
        def finditer(self, text: str) -> Iterator[Any]:
            for match in real.finditer(text):
                seen[0] += 1
                yield match

    monkeypatch.setattr(body_module, "_TOKEN", Counting())
    return seen


def test_the_preview_stops_at_the_budget_and_marks_the_cut() -> None:
    body = "${card.title} " + " ".join(f"w{i}" for i in range(500))
    preview = resolve_body(body, CARD, 25)
    words = preview.removesuffix(ELLIPSIS).split()
    assert len(words) == 25 and preview.endswith(ELLIPSIS)
    assert words[:3] == ["Der", "letzte", "Leuchtturm"]  # the reference counted with its words


def test_a_long_value_is_cut_to_what_is_left_of_the_budget() -> None:
    card = {**CARD, "test": " ".join(f"v{i}" for i in range(200))}
    preview = resolve_body("start ${card.test} the end", card, 10)
    words = preview.removesuffix(ELLIPSIS).split()
    assert words == ["start"] + [f"v{i}" for i in range(9)] and preview.endswith(ELLIPSIS)
    assert "the end" not in preview


def test_a_text_within_the_budget_is_whole_and_has_no_ellipsis() -> None:
    assert resolve_body("a ${card.title} b", CARD, 25) == "a Der letzte Leuchtturm b"


def test_ten_thousand_words_cost_what_a_short_body_costs(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _count_tokens(monkeypatch)
    short = "${card.title} " + " ".join(["word"] * 40)
    resolve_body(short, CARD, 25)
    short_cost = seen[0]
    seen[0] = 0
    huge = "${card.title} " + " ".join(["word"] * 10_000) + " ${card.test}"
    started = time.perf_counter()
    preview = resolve_body(huge, CARD, 25)
    elapsed = time.perf_counter() - started
    assert preview.endswith(ELLIPSIS)
    assert seen[0] <= short_cost + 4, (
        f"{seen[0]} tokens for 10,000 words, {short_cost} for a short body"
    )
    assert elapsed < 0.05


def test_the_preview_is_none_without_a_reference() -> None:
    assert preview_or_none("just words " * 100, CARD) is None
    assert preview_or_none(None, CARD) is None
    cut = preview_or_none("${card.title} " + "x " * 500, CARD)
    assert cut is not None and len(cut.removesuffix(ELLIPSIS).split()) == PREVIEW_WORDS


# ── what is told when it is saved ───────────────────────────────────


def test_unknown_references_are_named_with_why() -> None:
    known = {"title", "number", "id", "test"}
    problems = unknown_references("${card.nope} ${card.test} ${card.body} ${card.nope}", known)
    assert problems == [
        "${card.nope}: the artifact has no field 'nope'",
        "${card.body}: a body cannot contain itself, so this is shown as written",
    ]
    assert unknown_references("nothing", known) == []
    assert unknown_references(None, known) == []


def test_the_reference_pattern_is_the_one_of_the_engine() -> None:
    from openartifact.engine.context import _CARD_REFERENCE

    sample = "abcdefghijklmnopqrstuvwxyz012345"
    assert re.fullmatch(body_module._TOKEN.pattern.split("|")[0], f"${{card.{sample}}}")
    assert _CARD_REFERENCE.fullmatch(f"card.{sample}")
