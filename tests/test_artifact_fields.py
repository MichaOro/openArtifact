"""Artifact fields (ADR-044): the one list of fields every artifact has, the checks when an artifact is
saved, the three ways in (browser API, ``/api/v1``, MCP), events, the migrations and ``${card.NAME}`` in runs."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.app import _create_app
from openartifact.artifact_fields.rules import (
    FieldSpec,
    card_values,
    validate_values,
    with_defaults,
)
from openartifact.config import Settings
from openartifact.engine.context import ContextError, NodeIndex, RunContext, RunView
from tests.helpers import alembic_config, make_task, slow_pipeline, wait_for_run
from tests.test_mcp import _call as mcp_call
from tests.test_run_context import _code, _detail, _recording_server, _start, _use_chain

TOKEN = "fields-token-" + "x" * 30
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}


def _field(name: str, kind: str = "text", **extra: Any) -> dict[str, Any]:
    return {"name": name, "label": name.title(), "kind": kind, **extra}


URGENCY = _field("urgency", "choice", options=["low", "normal", "high"], default="normal")
SUMMARY = _field("summary", max_length=20)
SCORE = _field("score", "number", min_value=0, max_value=10, integer_only=True)
FLAG = _field("escalate", "boolean")


def _define(client: TestClient, *fields: dict[str, Any]) -> dict[str, Any]:
    response = client.put("/api/artifact-fields", json={"fields": list(fields)})
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def _artifact(client: TestClient, **values: Any) -> Any:
    return client.post("/api/tasks", json={"title": "A", "fields": values})


@pytest.fixture
def secured(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(
        update={
            "api_token": TOKEN,
            "secret_key": "k" * 40,
            "http_allow_private_networks": True,
            "code_nodes_without_token": True,
        }
    )
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


# ── the list of fields ───────────────────────────────────────────────


def test_there_are_no_fields_at_first_and_the_list_is_replaced_as_a_whole(
    client: TestClient,
) -> None:
    assert client.get("/api/artifact-fields").json() == {"fields": []}
    read = _define(client, URGENCY, SUMMARY)
    assert [f["name"] for f in read["fields"]] == ["urgency", "summary"]
    assert read["fields"][0] == {
        **URGENCY,
        "max_length": None,
        "min_value": None,
        "max_value": None,
        "integer_only": False,
        "artifact_count": 0,
    }
    assert [f["name"] for f in _define(client, SUMMARY, URGENCY)["fields"]] == [
        "summary",
        "urgency",
    ]
    assert client.get("/api/artifact-fields").json()["fields"][0]["name"] == "summary"  # the order


def test_a_field_has_no_required_setting_any_more(client: TestClient) -> None:
    """Every artifact has every field: a required one would break all existing artifacts at once."""
    response = client.put("/api/artifact-fields", json={"fields": [_field("a", required=True)]})
    assert response.status_code == 422 and "required" in response.text


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ([_field("Bad Name")], "Field Bad Name: the name is lowercase letters"),
        ([_field("a", label=" ")], "Field a: the label is 1-60 characters"),
        ([_field("a", "date")], "Field a: the kind must be text, number, boolean, choice"),
        ([_field("a", "choice", options=["x"])], "a choice has 2 to 20 allowed values"),
        ([_field("a", "choice", options=["x", "x"])], "different from each other"),
        ([_field("a", options=["x", "y"])], "only a choice has allowed values"),
        ([_field("a", "number", max_length=5)], "only text has a maximum length"),
        ([_field("a", min_value=1)], "only a number has"),
        ([_field("a", "number", min_value=5, max_value=1)], "minimum is above the maximum"),
        (
            [_field("a", "choice", options=["x", "y"], default="z")],
            'the default "z" is not one of x, y',
        ),
        ([_field("a", "number", default="5")], 'the default "5" is not a number'),
        ([_field("a"), _field("a")], "Field a: the name is used twice"),
        ([_field(f"f{i}") for i in range(31)], "There are at most 30 artifact fields"),
    ],
)
def test_a_wrong_definition_is_refused_naming_the_field(
    client: TestClient, fields: list[dict[str, Any]], message: str
) -> None:
    response = client.put("/api/artifact-fields", json={"fields": fields})
    assert response.status_code == 422 and message in response.json()["detail"]
    assert client.get("/api/artifact-fields").json() == {"fields": []}  # nothing was saved


def test_all_problems_of_a_definition_come_back_together_one_per_line(client: TestClient) -> None:
    response = client.put(
        "/api/artifact-fields", json={"fields": [_field("Bad"), _field("b", "date")]}
    )
    lines = response.json()["detail"].split("\n")
    assert response.status_code == 422 and len(lines) == 2
    assert lines[0].startswith("Field Bad:") and lines[1].startswith("Field b:")


# ── the values of an artifact ────────────────────────────────────────


def test_a_new_artifact_gets_the_defaults_and_the_values_given(client: TestClient) -> None:
    _define(client, URGENCY, SUMMARY, SCORE, FLAG)
    plain = _artifact(client).json()
    assert plain["fields"] == {"urgency": "normal"}  # only the default is stored
    given = _artifact(client, summary="s", score=3, escalate=False).json()
    assert given["fields"] == {"urgency": "normal", "summary": "s", "score": 3, "escalate": False}
    assert client.get(f"/api/tasks/{given['id']}").json()["fields"] == given["fields"]


def test_an_artifact_made_before_there_were_fields_has_none_and_reads_the_defaults(
    client: TestClient,
) -> None:
    before = make_task(client)
    assert before["fields"] == {}
    _define(client, URGENCY)
    assert client.get(f"/api/tasks/{before['id']}").json()["fields"] == {}  # nothing stored...
    assert card_values(
        [FieldSpec("urgency", "U", "choice", default="normal", options=("low", "normal"))], {}
    ) == {"urgency": "normal"}  # ...and a run reads the default


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            {"nope": 1},
            "Field nope: there is no such field (fields: urgency, summary, score, escalate)",
        ),
        (
            {"urgency": "hgh"},
            'Field urgency: "hgh" is not one of low, normal, high. Did you mean "high"?',
        ),
        ({"summary": "x" * 21}, "Field summary: at most 20 characters (got 21)"),
        ({"score": 11}, "Field score: 11 is above the maximum 10"),
        ({"score": 1.5}, "Field score: 1.5 is not a whole number"),
        ({"escalate": "yes"}, 'Field escalate: "yes" is not true or false'),
    ],
)
def test_a_wrong_value_is_refused_when_saving_and_names_the_field(
    client: TestClient, values: dict[str, Any], message: str
) -> None:
    _define(client, URGENCY, SUMMARY, SCORE, FLAG)
    response = _artifact(client, **values)
    assert response.status_code == 422 and message in response.json()["detail"]


def test_several_wrong_values_are_reported_together(client: TestClient) -> None:
    _define(client, URGENCY, SCORE)
    detail = _artifact(client, urgency="x", score="y").json()["detail"].split("\n")
    assert [line.split(":")[0] for line in detail] == ["Field urgency", "Field score"]


def test_the_values_are_capped_at_4_kib(client: TestClient) -> None:
    _define(client, *(_field(f"t{i}", max_length=1000) for i in range(5)))
    response = _artifact(client, **{f"t{i}": "x" * 1000 for i in range(5)})
    assert response.status_code == 422 and "Field values are limited to 4 KiB" in response.text


def test_an_update_merges_values_and_null_clears_one(client: TestClient) -> None:
    _define(client, URGENCY, SUMMARY, SCORE)
    task = _artifact(client, summary="s", score=2).json()
    changed = client.patch(f"/api/tasks/{task['id']}", json={"fields": {"score": 5}}).json()
    assert changed["fields"] == {"urgency": "normal", "summary": "s", "score": 5}
    cleared = client.patch(
        f"/api/tasks/{task['id']}", json={"fields": {"urgency": None, "summary": ""}}
    ).json()
    assert cleared["fields"] == {"score": 5}  # cleared ones read as their default again
    bad = client.patch(f"/api/tasks/{task['id']}", json={"fields": {"score": 50}})
    assert bad.status_code == 422 and "Field score" in bad.json()["detail"]
    assert client.patch(f"/api/tasks/{task['id']}", json={"fields": None}).status_code == 422


def test_the_fields_are_locked_while_the_artifact_runs(client: TestClient) -> None:
    _define(client, _field("memo"))
    task = _artifact(client, memo="a").json()
    pipeline = slow_pipeline(client)
    client.post(f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]})
    wait_for_run(client, task, "running")
    response = client.patch(f"/api/tasks/{task['id']}", json={"fields": {"memo": "b"}})
    assert response.status_code == 409
    assert client.patch(f"/api/tasks/{task['id']}", json={"title": "Renamed"}).status_code == 200
    client.post(f"/api/tasks/{task['id']}/run/stop")


# ── changing the list while artifacts have values ────────────────────


def test_removing_a_field_takes_its_values_with_it(client: TestClient) -> None:
    _define(client, URGENCY, SUMMARY)
    task = _artifact(client, summary="s").json()
    assert {
        f["name"]: f["artifact_count"] for f in client.get("/api/artifact-fields").json()["fields"]
    } == {
        "urgency": 1,
        "summary": 1,
    }
    _define(client, URGENCY)
    assert client.get(f"/api/tasks/{task['id']}").json()["fields"] == {"urgency": "normal"}
    _define(client, URGENCY, SUMMARY)  # the field comes back empty, not with the old value
    assert client.get(f"/api/tasks/{task['id']}").json()["fields"] == {"urgency": "normal"}


def test_a_change_that_stored_values_do_not_fit_is_refused_naming_the_field_and_the_count(
    client: TestClient,
) -> None:
    _define(client, URGENCY, SUMMARY)
    for text in ("a fairly long text", "another long text"):
        _artifact(client, summary=text)
    narrower = client.put(
        "/api/artifact-fields", json={"fields": [URGENCY, _field("summary", max_length=5)]}
    )
    assert narrower.status_code == 409
    assert (
        narrower.json()["detail"]
        == "Field summary: 2 artifacts have a value that does not fit the new definition"
    )
    kind = client.put(
        "/api/artifact-fields",
        json={"fields": [_field("urgency", "number"), SUMMARY]},
    )
    assert kind.status_code == 409 and "Field urgency: 2 artifacts have" in kind.json()["detail"]
    assert [f["kind"] for f in client.get("/api/artifact-fields").json()["fields"]] == [
        "choice",
        "text",
    ]
    wider = _define(
        client, _field("urgency", "choice", options=["low", "normal", "high", "urgent"]), SUMMARY
    )
    assert wider["fields"][0]["options"][-1] == "urgent"  # what still fits is fine


def test_the_events_carry_the_fields(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    _define(client, SUMMARY)
    assert published[-1][0] == "artifact_fields.changed"
    assert [f["name"] for f in published[-1][1]["fields"]] == ["summary"]
    task = _artifact(client, summary="s").json()
    assert published[-1][0] == "task.created" and published[-1][1]["fields"] == {"summary": "s"}
    client.patch(f"/api/tasks/{task['id']}", json={"fields": {"summary": "t"}})
    assert published[-1][0] == "task.updated" and published[-1][1]["fields"] == {"summary": "t"}


def test_the_artifact_types_are_gone(client: TestClient) -> None:
    assert client.get("/api/artifact-types").status_code == 404
    assert client.post("/api/tasks", json={"title": "A", "type_id": "x"}).status_code == 422
    assert client.get("/artifact-types").status_code == 404


# ── the integration API and MCP ──────────────────────────────────────


def test_the_integration_api_mirrors_the_fields_and_checks_values(secured: TestClient) -> None:
    put = secured.put("/api/v1/artifact-fields", json={"fields": [URGENCY, SUMMARY]})
    assert put.status_code == 200, put.text
    assert [f["name"] for f in secured.get("/api/v1/artifact-fields").json()["fields"]] == [
        "urgency",
        "summary",
    ]
    bad = secured.post("/api/v1/artifacts", json={"title": "A", "fields": {"urgency": "hgh"}})
    assert bad.status_code == 422 and "Field urgency" in bad.json()["detail"]
    ok = secured.post("/api/v1/artifacts", json={"title": "A", "fields": {"summary": "s"}}).json()
    assert ok["fields"] == {"urgency": "normal", "summary": "s"}
    patched = secured.patch(
        f"/api/v1/artifacts/{ok['number']}", json={"fields": {"urgency": "low"}}
    ).json()
    assert patched["fields"]["urgency"] == "low"


def test_mcp_lists_the_fields_and_creates_and_updates_artifacts_with_values(
    secured: TestClient,
) -> None:
    _define(secured, URGENCY, SUMMARY, SCORE)
    error, fields = mcp_call(secured, "list_artifact_fields")
    assert not error and [f["name"] for f in fields] == ["urgency", "summary", "score"]
    assert fields[0]["options"] == ["low", "normal", "high"]
    error, made = mcp_call(secured, "create_artifact", title="M", fields={"summary": "s"})
    assert not error and made["fields"] == {"urgency": "normal", "summary": "s"}
    error, text = mcp_call(secured, "create_artifact", title="M", fields={"urgency": "hgh"})
    assert error and 'Field urgency: "hgh" is not one of low, normal, high' in text
    error, changed = mcp_call(
        secured, "update_artifact", artifact=str(made["number"]), fields={"score": 5}
    )
    assert not error and changed["fields"]["score"] == 5
    error, text = mcp_call(secured, "update_artifact", artifact=str(made["number"]))
    assert error and "Give a title, a body, a lane or fields to change" in text


# ── the migrations ───────────────────────────────────────────────────


def test_migration_0038_replaces_the_types_with_the_field_list(
    unmigrated_settings: Settings, at_revision: Callable[[str], Path]
) -> None:
    path = at_revision("0037")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO artifact_types VALUES ('k', 'Ticket', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO artifact_type_fields (type_id, name, label, kind, required, integer_only, position) "
            "VALUES ('k', 'urgency', 'Urgency', 'text', 0, 0, 0)"
        )
        conn.execute(
            "INSERT INTO tasks (id, title, status, number, position, created_by, created_at, updated_at, "
            "type_id, parameters) VALUES ('t1', 'Typed', 'backlog', 1, 0, 'user', '2026-01-01', "
            "'2026-01-01', 'k', '{\"urgency\": \"x\"}')"
        )
    cfg = alembic_config()
    command.upgrade(cfg, "0038")
    with sqlite3.connect(path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        assert (
            "artifact_fields" in tables and not {"artifact_types", "artifact_type_fields"} & tables
        )
        assert "field_values" in columns and not {"type_id", "parameters"} & columns
        # the owner chose a clean model: the values of types are not carried over
        assert conn.execute("SELECT title, field_values FROM tasks").fetchall() == [("Typed", "{}")]
    command.downgrade(cfg, "0037")
    with sqlite3.connect(path) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"type_id", "parameters"} <= columns and "field_values" not in columns
        assert {
            "artifact_types",
            "artifact_type_fields",
        } <= tables and "artifact_fields" not in tables
        assert conn.execute("SELECT count(*) FROM tasks").fetchone() == (1,)
    command.upgrade(cfg, "head")


def test_migration_0031_adds_types_and_goes_down_and_up_with_data(
    unmigrated_settings: Settings, at_revision: Callable[[str], Path]
) -> None:
    path = at_revision("0030")
    with sqlite3.connect(path) as conn:
        for number, title in ((1, "Plain"), (2, "Other")):
            conn.execute(
                "INSERT INTO tasks (id, title, status, number, position, created_by, created_at, updated_at) "
                f"VALUES ('t{number}', '{title}', 'backlog', {number}, 0, 'user', '2026-01-01', '2026-01-01')"
            )
    cfg = alembic_config()
    command.upgrade(cfg, "0031")
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        assert conn.execute("SELECT type_id, parameters FROM tasks ORDER BY number").fetchall() == [
            (None, "{}"),
            (None, "{}"),
        ]
        conn.execute(
            "INSERT INTO artifact_types VALUES ('k', 'Ticket', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO artifact_type_fields (type_id, name, label, kind, required, integer_only, position) "
            "VALUES ('k', 'urgency', 'Urgency', 'text', 0, 0, 0)"
        )
        conn.execute(
            "UPDATE tasks SET type_id = 'k', parameters = '{\"urgency\": \"x\"}' WHERE number = 1"
        )
        with pytest.raises(
            sqlite3.IntegrityError, match=r"FOREIGN KEY constraint failed"
        ):  # a used type cannot go
            conn.execute("DELETE FROM artifact_types WHERE id = 'k'")
        with pytest.raises(
            sqlite3.IntegrityError, match=r"UNIQUE constraint failed: artifact_types\.name"
        ):  # names are unique ignoring case
            conn.execute(
                "INSERT INTO artifact_types VALUES ('k2', 'TICKET', '2026-01-01', '2026-01-01')"
            )
    command.downgrade(cfg, "0030")
    with sqlite3.connect(path) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {"type_id", "parameters"} & columns
        assert "artifact_types" not in tables and "artifact_type_fields" not in tables
        assert conn.execute("SELECT count(*) FROM tasks").fetchone() == (2,)
    command.upgrade(cfg, "head")
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT field_values FROM tasks WHERE number = 1").fetchone() == ("{}",)


# ── the run: ${card.NAME} ────────────────────────────────────────────


def _view(card: dict[str, Any]) -> RunView:
    return RunView(RunContext.initial(card), NodeIndex())


def test_card_references_render_like_other_values() -> None:
    view = _view({"s": "text é", "n": 3, "f": 1.5, "b": True, "z": None})
    assert (
        view.render("${card.s}|${card.n}|${card.f}|${card.b}|${card.z}") == "text é|3|1.5|true|null"
    )
    assert view.render("/p/${card.s}", percent_encode=True) == "/p/text%20%C3%A9"


def test_a_card_reference_to_an_unknown_field_fails_naming_it() -> None:
    for view in (_view({"known": 1}), _view({})):
        with pytest.raises(ContextError) as error:
            view.render("go ${card.x} now")
        assert str(error.value) == '${card.x}: the artifact has no field "x"'
    with pytest.raises(ContextError, match="malformed reference"):
        _view({}).render("${card.Upper}")


def test_card_values_are_not_scanned_again_and_the_context_keeps_the_card() -> None:
    view = _view({"t": "${secret:TOKEN} ${var.x}"})
    assert view.render("${card.t}", secrets={"TOKEN": "hunter2"}) == "${secret:TOKEN} ${var.x}"
    assert RunContext.loads(view.dumps()).card == {"t": "${secret:TOKEN} ${var.x}"}
    assert RunContext.loads('{"vars": {}}').card == {}


def test_a_run_sees_every_field_with_its_value_its_default_or_null() -> None:
    specs = [
        FieldSpec("a", "A", "text"),
        FieldSpec("b", "B", "choice", default="x", options=("x", "y")),
        FieldSpec("c", "C", "number"),
    ]
    assert card_values(specs, {"a": "v", "gone": 1}) == {"a": "v", "b": "x", "c": None}
    stored, problems = validate_values(specs, with_defaults(specs, {"a": "v"}))
    assert stored == {"a": "v", "b": "x"} and problems == []


def test_a_run_gets_the_card_and_an_http_node_uses_it_and_later_edits_do_not_change_it(
    secured: TestClient,
) -> None:
    _define(secured, URGENCY, SUMMARY, SCORE, FLAG)
    task = secured.post(
        "/api/tasks", json={"title": "A", "fields": {"summary": "s", "urgency": "high"}}
    ).json()
    with _recording_server() as (port, seen):
        call = {
            "method": "POST",
            "url": f"http://127.0.0.1:{port}/u/${{card.urgency}}",
            "body": "${card.summary}",
        }
        pipeline, _, _ = _use_chain(
            secured,
            ("http", "Caller", call),
            (
                "code",
                "Dump",
                _code(
                    "python3 -c \"import json;print(json.load(open('context.json'))['card']['urgency'])\"",
                    "sh",
                ),
            ),
        )
        _start(secured, pipeline, task)
        wait_for_run(secured, task, "done")
    assert seen[0]["path"] == "/u/high" and seen[0]["body"] == "s"
    first = _detail(secured, task)
    assert first["context"]["card"] == {
        "urgency": "high",
        "summary": "s",
        "score": None,
        "escalate": None,
    }
    assert first["context"]["nodes"]["Dump"]["output"].strip() == "high"
    secured.patch(f"/api/tasks/{task['id']}", json={"fields": {"urgency": "low"}})
    detail = secured.get(f"/api/tasks/{task['id']}/executions/{first['id']}").json()
    assert detail["context"]["card"]["urgency"] == "high"  # a copy taken at the start


def test_a_node_that_uses_a_field_that_does_not_exist_fails_with_the_reason(
    secured: TestClient,
) -> None:
    pipeline, _, _ = _use_chain(
        secured, ("http", "Caller", {"method": "POST", "url": "http://127.0.0.1:1/${card.urgency}"})
    )
    task = make_task(secured)
    _start(secured, pipeline, task)
    wait_for_run(secured, task, "failed")
    step = next(s for s in _detail(secured, task)["steps"] if s["kind"] == "http")
    assert '${card.urgency}: the artifact has no field "urgency"' in step["reason"]
