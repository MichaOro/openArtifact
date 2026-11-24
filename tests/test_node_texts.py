"""The texts of a node kind stay short (docs/guides/ui-catalog.md, "Texts of a node"): a label of at most 3 words, a help of
at most 2 sentences and 220 characters, a placeholder of at most 60 characters, an option and a port of a few words, a caption of one
line. A language may be longer by a quarter. A kind that has a good reason for a longer text names it in ``ALLOWED`` with
the reason, so a new kind and a third party see the rule and its exceptions."""

from __future__ import annotations

import re
from typing import Any

from openartifact.graph.localize import localize
from openartifact.graph.node_types import NODE_TYPES

# English; a language gets LONGER_BY on top (German is about a quarter longer).
LIMITS = {
    "label_words": 3,
    "group_words": 4,
    "option_words": 3,
    "port_words": 2,
    "help_chars": 220,
    "help_sentences": 2,
    "placeholder_chars": 60,
}
LONGER_BY = 1.25

#: (kind or "*" for every kind, what) -> why a text may be longer than the rule. A stale entry fails the test.
ALLOWED: dict[tuple[str, str], str] = {
    ("*", "setting on_failure label"): (
        "The owner's wording ('If the node fails', 'If the action fails'): a question that its three answers complete; "
        "n8n words it the same way"
    ),
}


def _words(text: str) -> int:
    return len(text.split())


def _sentences(text: str) -> int:
    return len([x for x in re.split(r"(?<=[.!?])\s+(?=[A-Z$'\"{])", text.strip()) if x])


def _limit(name: str, factor: float) -> int:
    value = LIMITS[name]
    return round(value * factor) if factor != 1 else value


def texts(description: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Every text a node's dialog and card show: (kind, what, text)."""
    rows: list[tuple[str, str, str]] = []
    for entry in description:
        kind = entry["kind"]
        rows.append((kind, "label", entry["label"]))
        for port in (*entry.get("inputs", []), *entry.get("outputs", [])):
            rows.append((kind, f"port {port['name']}", port["label"]))
        caption = (entry.get("ui") or {}).get("caption")
        if isinstance(caption, dict) and "template" in caption:
            rows.append((kind, "caption", caption["template"]))
        for setting in entry.get("settings", []):
            key = setting["key"]
            rows.append((kind, f"setting {key} label", setting["label"]))
            for field in ("group", "help", "placeholder"):
                if setting.get(field):
                    rows.append((kind, f"setting {key} {field}", setting[field]))
            labels = setting.get("option_labels") or {}
            for option in setting.get("options") or []:
                rows.append((kind, f"setting {key} option {option}", labels.get(option, option)))
    return rows


def problems(description: list[dict[str, Any]], factor: float = 1.0) -> dict[tuple[str, str], str]:
    found: dict[tuple[str, str], str] = {}
    for kind, what, text in texts(description):
        bad = ""
        if what == "label" or what.endswith(" label"):
            if _words(text) > _limit("label_words", factor) or text.rstrip().endswith("."):
                bad = (
                    f"{_words(text)} words (at most {_limit('label_words', factor)}, no full stop)"
                )
        elif what.startswith("port "):
            if _words(text) > _limit("port_words", factor):
                bad = f"{_words(text)} words (a port: at most {_limit('port_words', factor)})"
        elif what.endswith(" group"):
            if _words(text) > _limit("group_words", factor):
                bad = (
                    f"{_words(text)} words (a group title: at most {_limit('group_words', factor)})"
                )
        elif what.endswith(" help"):
            chars, sentences = len(text), _sentences(text)
            if chars > _limit("help_chars", factor) or sentences > _limit("help_sentences", 1):
                bad = f"{chars} characters and {sentences} sentences (at most {_limit('help_chars', factor)} and 2)"
        elif what.endswith(" placeholder"):
            if len(text) > _limit("placeholder_chars", factor):
                bad = f"{len(text)} characters (at most {_limit('placeholder_chars', factor)})"
        elif " option " in what:
            if _words(text) > _limit("option_words", factor):
                bad = f"{_words(text)} words (an option: at most {_limit('option_words', factor)})"
        elif what == "caption":
            fixed = re.sub(r"\{[^}]*\}", "", text)  # the parts that are filled in are not sentences
            if "\n" in text or re.search(r"[.!?]\s", fixed):
                bad = "a caption is one line and no sentence"
        if bad:
            found[(kind, what)] = f"{text!r}: {bad}"
    return found


def _allowed(found: dict[tuple[str, str], str]) -> dict[tuple[str, str], str]:
    """What the rule refuses, minus what ALLOWED names."""
    return {
        key: why
        for key, why in found.items()
        if key not in ALLOWED and ("*", key[1]) not in ALLOWED
    }


def _english() -> list[dict[str, Any]]:
    return [nt.describe() for nt in NODE_TYPES.values()]


def test_the_english_texts_of_every_kind_keep_the_rule() -> None:
    refused = _allowed(problems(_english()))
    assert not refused, "\n" + "\n".join(
        f"{k[0]} / {k[1]}: {v}" for k, v in sorted(refused.items())
    )


def test_the_german_texts_keep_the_rule_with_a_quarter_more() -> None:
    refused = _allowed(problems(localize(_english(), "de"), LONGER_BY))
    assert not refused, "\n" + "\n".join(
        f"{k[0]} / {k[1]}: {v}" for k, v in sorted(refused.items())
    )


def test_an_exception_that_is_no_longer_needed_is_removed() -> None:
    found = problems(_english())
    for kind, what in ALLOWED:
        assert any(what == w and (kind in ("*", k)) for (k, w) in found), (
            f"{kind} / {what} keeps the rule now: take it out of ALLOWED"
        )


def test_the_rule_refuses_what_it_should() -> None:
    """The check itself: a label of four words, a help of three sentences, a long placeholder and a caption with a sentence."""
    description = [
        {
            "kind": "demo",
            "label": "Demo",
            "inputs": [{"name": "in", "label": "Input"}],
            "outputs": [{"name": "pass", "label": "When everything passed"}],
            "ui": {"caption": {"template": "{x}. A sentence.\nAnd a second line"}},
            "settings": [
                {
                    "key": "a",
                    "label": "A label of four",
                    "type": "text",
                    "help": "One. Two. Three.",
                },
                {"key": "b", "label": "Fine", "type": "text", "placeholder": "x" * 61},
                {"key": "c", "label": "Fine", "type": "select", "options": ["A choice of four"]},
            ],
        }
    ]
    found = problems(description)
    assert set(found) == {
        ("demo", "port pass"),
        ("demo", "caption"),
        ("demo", "setting a label"),
        ("demo", "setting a help"),
        ("demo", "setting b placeholder"),
        ("demo", "setting c option A choice of four"),
    }
    assert problems(description, LONGER_BY).keys() >= {
        ("demo", "setting a help")
    }  # sentences do not grow with the language
