"""The schema of flat fields and the check of a document against it (ADR-080)."""

from __future__ import annotations

from typing import Any

import pytest

from openartifact.graph import field_schema as fs

REVIEW = fs.normalise(
    [
        {"name": "passed", "type": "boolean", "required": True, "description": "Whether it holds"},
        {"name": "verdict", "type": "choice", "required": True, "choices": ["approve", "reject"]},
        {"name": "reasons", "type": "list"},
        {"name": "score", "type": "number"},
        {"name": "note", "type": "text"},
    ]
)
GOOD = {"passed": True, "verdict": "approve", "reasons": ["a", "b"], "score": 3.5, "note": "ok"}


# ── the stored list ──────────────────────────────────────────────────


def test_a_list_is_stored_with_every_option_present_and_the_values_of_a_choice_trimmed() -> None:
    stored = fs.normalise([{"name": "kind", "type": "choice", "choices": [" a ", "b", ""]}])
    assert stored == [
        {
            "name": "kind",
            "type": "choice",
            "required": False,
            "description": "",
            "choices": ["a", "b"],
        }
    ]
    assert fs.normalise([{"name": "x"}]) == [
        {"name": "x", "type": "text", "required": False, "description": ""}
    ]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("nope", "The fields must be a list"),
        ([{"name": "a"}] * 31, "At most 30 fields"),
        (["x"], "Field 1 must be an object"),
        ([{"name": "Bad"}], "Field 1: the name is lowercase letters, digits and _"),
        ([{"name": "1a"}], "Field 1: the name is lowercase letters"),
        ([{"name": "a" * 33}], "Field 1: the name is lowercase letters"),
        ([{"name": "a"}, {"name": "a"}], "The field 'a' is there twice"),
        ([{"name": "a", "type": "object"}], "Field 'a': the type is one of text, number"),
        ([{"name": "a", "required": "yes"}], "Field 'a': required is true or false"),
        ([{"name": "a", "description": "x" * 301}], "Field 'a': the description is a text of at most 300"),
        ([{"name": "a", "type": "choice"}], "Field 'a': a choice needs 2 to 20 values"),
        ([{"name": "a", "type": "choice", "choices": ["only"]}], "a choice needs 2 to 20 values"),
        ([{"name": "a", "type": "choice", "choices": ["x", "x"]}], "Field 'a': a value is there twice"),
        ([{"name": "a", "type": "choice", "choices": ["x", "y" * 61]}], "a value is at most 60 characters"),
        ([{"name": "a", "type": "text", "choices": ["x", "y"]}], "Field 'a': only a choice has values"),
        ([{"name": "a", "fields": []}], "Field 1 has no option 'fields'"),
    ],
)  # fmt: skip
def test_a_list_that_is_no_schema_is_refused_in_plain_words(value: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        fs.normalise(value)
    assert fs.fields_error(value) is not None


def test_a_flat_schema_has_no_object_type_and_the_server_says_so_to_the_editor() -> None:
    assert "object" not in fs.TYPES
    described = fs.describe()
    assert described["field_types"] == list(fs.TYPES) and described["max_fields"] == 30


# ── what the model is told ───────────────────────────────────────────


def test_the_model_is_told_exactly_the_fields_and_which_are_required() -> None:
    schema = fs.json_schema(REVIEW)
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert schema["required"] == ["passed", "verdict"]
    assert schema["properties"]["passed"] == {"type": "boolean", "description": "Whether it holds"}
    assert schema["properties"]["verdict"] == {"type": "string", "enum": ["approve", "reject"]}
    assert schema["properties"]["reasons"]["type"] == "array"
    assert schema["properties"]["score"] == {"type": "number"}
    assert schema["properties"]["note"]["type"] == "string"
    assert list(schema["properties"]) == ["passed", "verdict", "reasons", "score", "note"]


# ── the check of a document ──────────────────────────────────────────


def test_a_document_that_fits_has_no_problem() -> None:
    assert fs.validate(REVIEW, GOOD) == []
    assert fs.validate(REVIEW, {"passed": False, "verdict": "reject"}) == []
    assert (
        fs.validate(REVIEW, {"passed": True, "verdict": "approve", "score": None}) == []
    )  # null is "not given"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"passed": "yes"}, "'passed' must be true or false"),
        ({"passed": 1}, "'passed' must be true or false"),
        ({"verdict": "maybe"}, "'verdict' must be one of: approve, reject"),
        ({"verdict": 3}, "'verdict' must be one of: approve, reject"),
        ({"reasons": "a"}, "'reasons' must be a list of texts"),
        ({"reasons": ["a", 2]}, "'reasons' must be a list of texts"),
        ({"reasons": ["x"] * 51}, "'reasons' has more than 50 entries"),
        ({"reasons": ["x" * 501]}, "'reasons' has an entry longer than 500 characters"),
        ({"score": "3"}, "'score' must be a number"),
        ({"score": True}, "'score' must be a number"),
        ({"note": 5}, "'note' must be a text"),
        ({"note": "x" * 8001}, "'note' is longer than 8000 characters"),
        ({"extra": 1}, "unknown field 'extra' (the fields are: passed, verdict, reasons, score, note)"),
    ],
)  # fmt: skip
def test_a_wrong_value_is_named_with_the_field_and_what_was_expected(
    change: dict[str, Any], message: str
) -> None:
    assert fs.validate(REVIEW, {**GOOD, **change}) == [message]


def test_everything_that_is_wrong_comes_back_at_once_in_the_order_of_the_schema() -> None:
    problems = fs.validate(REVIEW, {"extra": 1, "score": "x"})
    assert problems == [
        "unknown field 'extra' (the fields are: passed, verdict, reasons, score, note)",
        "'passed' is required",
        "'verdict' is required",
        "'score' must be a number",
    ]


def test_a_required_field_may_be_neither_left_out_nor_null() -> None:
    assert fs.validate(REVIEW, {"verdict": "approve", "passed": None}) == ["'passed' is required"]


def test_a_document_that_is_no_object_is_refused() -> None:
    assert fs.validate(REVIEW, ["a"]) == ["the document must be an object with the fields below"]
    assert fs.validate(REVIEW, "text") == ["the document must be an object with the fields below"]


def test_the_whole_document_is_held_to_its_size() -> None:
    fields = fs.normalise([{"name": "note"}])
    assert fs.validate(fields, {"note": "x" * 2000}, 4096) == []
    (problem,) = fs.validate(fields, {"note": "x" * 2000}, 1024)
    assert problem.startswith("the document is 2012 bytes, more than the limit of 1024 bytes")
    assert fs.validate(fields, {"note": "ä" * 600}, 1024) == [
        "the document is 1212 bytes, more than the limit of 1024 bytes"
    ]  # bytes of UTF-8, not characters


def test_a_text_that_looks_like_a_reference_is_only_text() -> None:
    fields = fs.normalise([{"name": "note"}])
    document = {"note": "${secret:API_KEY} ${var.x} ${(Node).output}"}
    assert fs.validate(fields, document) == []
    assert fs.clean(fields, document) == document  # kept as it is, never read as a reference


def test_the_stored_document_has_the_fields_in_the_order_of_the_schema_and_no_null() -> None:
    document = {"score": 2, "verdict": "reject", "passed": False, "reasons": None}
    assert list(fs.clean(REVIEW, document)) == ["passed", "verdict", "score"]
