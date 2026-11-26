"""Tests for resolve_body_segments (A4)."""

from __future__ import annotations

from typing import Any

from openartifact.artifact_fields.body import resolve_body_segments


def test_segments_simple_reference() -> None:
    """A single reference produces two segments: text before + resolved."""
    body = "Ticket ${card.number}"
    card = {"number": 123}
    segments = resolve_body_segments(body, card)
    assert len(segments) == 2
    assert segments[0] == {"text": "Ticket ", "resolved": False}
    assert segments[1] == {"text": "123", "resolved": True}


def test_segments_multiple_references() -> None:
    """Multiple references produce alternating segments."""
    body = "${card.title} - ${card.number}"
    card = {"title": "Fix bug", "number": 42}
    segments = resolve_body_segments(body, card)
    assert len(segments) == 3
    assert segments[0] == {"text": "Fix bug", "resolved": True}
    assert segments[1] == {"text": " - ", "resolved": False}
    assert segments[1] == {"text": " - ", "resolved": False}
    assert segments[2] == {"text": "42", "resolved": True}


def test_segments_no_references() -> None:
    """Body without references returns single unresolved segment."""
    body = "Plain text"
    card: dict[str, Any] = {}
    segments = resolve_body_segments(body, card)
    assert len(segments) == 1
    assert segments[0] == {"text": "Plain text", "resolved": False}


def test_segments_empty_body() -> None:
    """Empty body returns single empty unresolved segment."""
    segments = resolve_body_segments("", {})
    assert len(segments) == 1
    assert segments[0] == {"text": "", "resolved": False}


def test_segments_unknown_reference() -> None:
    """Unknown reference stays as text, unresolved."""
    body = "${card.unknown}"
    card: dict[str, Any] = {}
    segments = resolve_body_segments(body, card)
    assert len(segments) == 1
    assert segments[0] == {"text": "${card.unknown}", "resolved": False}


def test_segments_self_reference() -> None:
    """Self references (body, text) stay as text, unresolved."""
    body = "${card.body}"
    card = {"body": "original"}
    segments = resolve_body_segments(body, card)
    assert len(segments) == 1
    assert segments[0] == {"text": "${card.body}", "resolved": False}


def test_segments_with_preview_budget() -> None:
    """Budget limits segments and adds ellipsis to last segment."""
    body = "A ${card.title} B ${card.number} C"
    card = {"title": "Long title that takes many words", "number": 1}
    segments = resolve_body_segments(body, card, max_words=3)
    # Should stop within budget
    total_words = sum(len(s["text"].split()) for s in segments)
    assert total_words <= 3
    # Last segment should have ellipsis if cut
    if "…" in segments[-1]["text"]:
        assert segments[-1]["text"].endswith("…")


def test_segments_adjacent_references() -> None:
    """Adjacent references merge into one resolved segment (no separator)."""
    body = "${card.title}${card.number}"
    card = {"title": "T", "number": 1}
    segments = resolve_body_segments(body, card)
    # Two references with no text between merge into one resolved segment
    assert len(segments) == 1
    assert segments[0] == {"text": "T1", "resolved": True}


def test_segments_separated_references() -> None:
    """References separated by space produce separate segments."""
    body = "${card.title} ${card.number}"
    card = {"title": "T", "number": 1}
    segments = resolve_body_segments(body, card)
    assert len(segments) == 3
    assert segments[0] == {"text": "T", "resolved": True}
    assert segments[1] == {"text": " ", "resolved": False}
    assert segments[2] == {"text": "1", "resolved": True}


def test_segments_mixed_content() -> None:
    """Mixed text and references produce correct segments."""
    body = "Start ${card.title} middle ${card.number} end"
    card = {"title": "T", "number": 1}
    segments = resolve_body_segments(body, card)
    assert len(segments) == 5
    assert segments[0] == {"text": "Start ", "resolved": False}
    assert segments[1] == {"text": "T", "resolved": True}
    assert segments[2] == {"text": " middle ", "resolved": False}
    assert segments[3] == {"text": "1", "resolved": True}
    assert segments[4] == {"text": " end", "resolved": False}


def test_segments_empty_field() -> None:
    """Empty field value produces empty resolved segment."""
    body = "Value: ${card.empty_field}"
    card = {"empty_field": ""}
    segments = resolve_body_segments(body, card)
    assert len(segments) == 2
    assert segments[0] == {"text": "Value: ", "resolved": False}
    assert segments[1] == {"text": "", "resolved": True}


def test_segments_number_boolean_rendering() -> None:
    """Numbers and booleans render as compact JSON."""
    body = "${card.count} ${card.flag}"
    card = {"count": 3, "flag": True}
    segments = resolve_body_segments(body, card)
    # Should have: "3" (resolved), " " (unresolved), "true" (resolved)
    resolved_segments = [s for s in segments if s["resolved"]]
    assert len(resolved_segments) == 2
    assert resolved_segments[0]["text"] == "3"
    assert resolved_segments[1]["text"] == "true"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
