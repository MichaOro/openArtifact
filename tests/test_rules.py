"""One rule system (ADR-052 generalised, ADR-060): the condition tree, its two evaluators (SQL for retention, in memory
for guards) and the schemas per purpose."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from openartifact.engine import retention
from openartifact.guards.schemas import GuardGroup
from openartifact.rules import tree
from openartifact.rules.catalog import GUARD, SCHEMAS
from tests.helpers import make_task
from tests.test_history_global import Seed


def _group(*items: dict[str, Any], mode: str = "all") -> dict[str, Any]:
    return {"type": "group", "mode": mode, "items": list(items)}


def _cond(field: str, op: str, value: Any) -> dict[str, Any]:
    return {"type": "condition", "field": field, "op": op, "value": value}


def _guard(data: dict[str, Any]) -> GuardGroup:
    return GuardGroup.model_validate(data)


# ── the in-memory evaluator ─────────────────────────────────────────


def test_numbers_counts_and_durations_compare_as_their_operator_says() -> None:
    facts = {"runs": 5, "idle": 180, "cost": 0.5, "var.gain": 0.01}
    assert tree.evaluate(_guard(_group(_cond("runs", "at_least", 5))), facts)
    assert not tree.evaluate(_guard(_group(_cond("runs", "below", 5))), facts)
    assert tree.evaluate(_guard(_group(_cond("runs", "equals", 5))), facts)
    assert tree.evaluate(_guard(_group(_cond("idle", "at_least", 120))), facts)
    assert tree.evaluate(_guard(_group(_cond("var.gain", "below", 0.05))), facts)
    assert not tree.evaluate(_guard(_group(_cond("cost", "at_least", 1))), facts)


def test_all_any_and_inner_groups_and_an_empty_tree_matches_nothing() -> None:
    facts = {"runs": 3, "errors": 0, "last_status": "pass"}
    either = _group(_cond("runs", "at_least", 10), _cond("last_status", "is", ["pass"]), mode="any")
    both = _group(_cond("runs", "at_least", 10), _cond("last_status", "is", ["pass"]))
    assert tree.evaluate(_guard(either), facts)
    assert not tree.evaluate(_guard(both), facts)
    assert not tree.evaluate(_guard(_group()), facts)  # an empty rule never fires
    # an empty inner group is left out: it neither blocks nor matches everything
    assert tree.evaluate(_guard(_group(_group(), _cond("errors", "equals", 0))), facts)
    assert not tree.evaluate(_guard(_group(_group(mode="any"))), facts)


def test_a_missing_fact_never_fires_whatever_the_operator() -> None:
    for condition in (
        _cond("cost", "below", 10),
        _cond("var.score", "below", 1),
        _cond("last_status", "is_not", ["pass"]),
    ):
        assert not tree.evaluate(_guard(_group(condition)), {"runs": 1})


# ── the guard schema checks its conditions ───────────────────────────


@pytest.mark.parametrize(
    ("condition", "reason"),
    [
        (_cond("colour", "is", ["red"]), "unknown field 'colour'"),
        (_cond("runs", "older_than", 3), "the operator 'older_than' does not fit"),
        (_cond("runs", "at_least", 2.5), "give a whole number"),
        (_cond("idle", "at_least", -1), "give a value from 0"),
        (_cond("last_status", "is", ["maybe"]), "'maybe' is not one of pass, error, none"),
        (_cond("var.Bad-Name", "below", 1), "name a result field as var.NAME"),
        (_cond("cost", "at_least", True), "valid"),
    ],
)
def test_a_guard_condition_that_does_not_fit_the_schema_is_refused(
    condition: dict[str, Any], reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        _guard(_group(condition))


def test_the_bounds_hold_for_every_purpose() -> None:
    deep: dict[str, Any] = _group(_cond("runs", "at_least", 1))
    for _ in range(4):
        deep = _group(deep)
    with pytest.raises(ValueError, match="nested too deep"):
        tree.check_bounds(_guard(deep))
    with pytest.raises(ValueError, match="at most 50 conditions"):
        tree.check_bounds(_guard(_group(*[_cond("runs", "at_least", 1)] * 51)))


# ── both evaluators agree ─────────────────────────────────────────────

TREES = [
    _group(_cond("status", "is", ["failed"])),
    _group(_cond("status", "is_not", ["done"]), _cond("pipeline", "contains", "uil")),
    _group(_cond("age", "older_than", 3 * 86400), _cond("started_by", "is", ["api"]), mode="any"),
    _group(_cond("position", "beyond", 2)),
    _group(
        _cond("pipeline", "is", "build"),
        _group(_cond("age", "older_than", 3600), _cond("position", "beyond", 1), mode="any"),
    ),
    _group(_cond("pipeline", "is_not", "Deploy"), _group()),
    _group(),
]


def test_the_sql_compiler_and_the_in_memory_evaluator_agree_on_the_same_trees(
    client: TestClient,
) -> None:
    seed = Seed(client)
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for name, offsets in (("A", (10, 6, 2, 0.01)), ("B", (5, 1))):
        task = make_task(client, name)
        for i, days in enumerate(offsets):
            at = now - timedelta(days=days)
            status = ("done", "failed", "stopped")[i % 3]
            by, pipeline = ("api" if i % 2 else "user"), ("Build" if i % 2 == 0 else "Deploy")
            ident = seed.add(task, at=at, status=status, by=by, pipeline=pipeline)
            rows.append(
                {
                    "id": ident,
                    "task": name,
                    "index": i,
                    "total": len(offsets),
                    "status": status,
                    "started_by": by,
                    "pipeline": pipeline,
                    "age": (now - at).total_seconds(),
                }
            )
    for row in rows:
        row["position"] = row["total"] - 1 - row["index"]  # how many of its artifact are newer
    for data in TREES:
        rules = retention.Rules.model_validate({"rules": [{"when": data, "action": "delete"}]})
        preview = client.post("/api/settings/retention/preview", json=rules.model_dump()).json()
        in_memory = sum(tree.evaluate(rules.rules[0].when, row) for row in rows)
        assert preview["matching"] == in_memory, data


# ── the schemas are the server's and the browser reads them ─────────


def test_the_schemas_list_the_fields_and_mark_what_is_not_built_yet(client: TestClient) -> None:
    body = client.get("/api/rules/schemas").json()
    by_purpose = {s["purpose"]: s for s in body}
    assert set(by_purpose) == set(SCHEMAS)
    retention_fields = {f["key"]: tuple(f["operators"]) for f in by_purpose["retention"]["fields"]}
    assert retention_fields == retention.FIELDS  # retention keeps exactly its fields
    guard = by_purpose["guard"]
    assert {f["key"] for f in guard["fields"]} >= {"runs", "elapsed", "idle", "guard.runs", "var."}
    unavailable = {c["key"]: c["needs"] for c in guard["consequences"] if not c["available"]}
    assert set(unavailable) == {"notify", "handover"}
    assert "#93" in unavailable["notify"] and "#95" in unavailable["handover"]
    assert by_purpose["lane"]["planned"] is False  # built with the card rules (ADR-071)
    assert by_purpose["board"]["planned"] is False
    assert client.get("/api/rules/schemas/guard").json() == GUARD.to_data()
    assert client.get("/api/rules/schemas/nothing").status_code == 404
