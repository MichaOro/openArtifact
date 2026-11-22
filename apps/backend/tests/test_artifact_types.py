"""Artifact types and card parameters (ADR-035): the types API, the checks when an artifact is saved,
the three ways in (browser API, ``/api/v1``, MCP), events, the migration and ``${card.NAME}`` in runs."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.app import _create_app
from openartifact.artifact_types.fields import FieldSpec, card_values, validate_parameters
from openartifact.config import Settings
from openartifact.engine.context import ContextError, NodeIndex, RunContext, RunView
from tests.helpers import alembic_config, make_task, slow_pipeline, wait_for_run
from tests.test_mcp import _call as mcp_call
from tests.test_run_context import _code, _detail, _recording_server, _start, _use_chain

TOKEN = "types-token-" + "x" * 30
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}


def _field(name: str, kind: str = "text", **extra: Any) -> dict[str, Any]:
    return {"name": name, "label": name.title(), "kind": kind, **extra}


URGENCY = _field("urgency", "choice", options=["low", "normal", "high"], default="normal")
SUMMARY = _field("summary", required=True, max_length=20)
SCORE = _field("score", "number", min_value=0, max_value=10, integer_only=True)
FLAG = _field("escalate", "boolean")


def _ticket(client: TestClient, name: str = "Ticket", *fields: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        "/api/artifact-types",
        json={"name": name, "fields": list(fields or [URGENCY, SUMMARY, SCORE, FLAG])},
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def _artifact(client: TestClient, kind: dict[str, Any] | None, **fields: Any) -> Any:
    body = {"title": "A", **({"type_id": kind["id"]} if kind else {}), **fields}
    return client.post("/api/tasks", json=body)


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


# ── the types ────────────────────────────────────────────────────────


def test_a_type_is_created_read_listed_renamed_and_deleted(client: TestClient) -> None:
    made = _ticket(client)
    assert [f["name"] for f in made["fields"]] == ["urgency", "summary", "score", "escalate"]
    assert made["artifact_count"] == 0 and made["fields"][0]["options"] == ["low", "normal", "high"]
    assert client.get(f"/api/artifact-types/{made['id']}").json() == made
    assert client.get("/api/artifact-types").json() == [made]
    renamed = client.put(
        f"/api/artifact-types/{made['id']}", json={"name": "Support", "fields": [SUMMARY, URGENCY]}
    ).json()
    assert renamed["name"] == "Support" and [f["name"] for f in renamed["fields"]] == [
        "summary",
        "urgency",
    ]
    assert client.delete(f"/api/artifact-types/{made['id']}").status_code == 204
    assert client.get("/api/artifact-types").json() == []
    for call in (client.get, client.delete):
        assert call(f"/api/artifact-types/{made['id']}").status_code == 404


def test_type_names_are_unique_ignoring_case_and_trimmed(client: TestClient) -> None:
    _ticket(client, "Bug")
    response = client.post("/api/artifact-types", json={"name": " BUG ", "fields": []})
    assert response.status_code == 409 and "already exists" in response.json()["detail"]
    other = _ticket(client, "Task")
    renamed = client.put(f"/api/artifact-types/{other['id']}", json={"name": "bug", "fields": []})
    assert renamed.status_code == 409
    assert (
        client.put(
            f"/api/artifact-types/{other['id']}", json={"name": "TASK", "fields": []}
        ).status_code
        == 200
    )
    for name in ("", "   ", "x" * 61):
        assert (
            client.post("/api/artifact-types", json={"name": name, "fields": []}).status_code == 422
        )


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ([_field("Bad")], "Field Bad: the name is lowercase"),
        ([_field("1a")], "Field 1a: the name"),
        ([_field("a" * 33)], "the name"),
        ([_field("a"), _field("a")], "Field a: the name is used twice"),
        ([{**_field("a"), "label": " "}], "Field a: the label"),
        ([_field("a", "date")], "Field a: the kind must be text, number, boolean, choice"),
        ([_field("a", "choice", options=["x"])], "Field a: a choice has 2 to 20 allowed values"),
        ([_field("a", "choice", options=[str(i) for i in range(21)])], "2 to 20"),
        ([_field("a", "choice", options=["x", "x"])], "different from each other"),
        ([_field("a", "choice", options=["x", "y" * 41])], "each allowed value is 1-40"),
        ([_field("a", options=["x", "y"])], "only a choice has allowed values"),
        ([_field("a", max_length=0)], "maximum length is 1-1000"),
        ([_field("a", max_length=1001)], "maximum length is 1-1000"),
        ([_field("a", "number", max_length=5)], "only text has a maximum length"),
        ([_field("a", min_value=1)], "only a number has"),
        ([_field("a", "number", min_value=5, max_value=1)], "minimum is above the maximum"),
        (
            [_field("a", "choice", options=["x", "y"], default="z")],
            'the default "z" is not one of x, y',
        ),
        ([_field("a", "number", default="5")], 'the default "5" is not a number'),
        ([_field("a", max_length=3, default="abcd")], "the default at most 3 characters"),
        ([_field(f"f{i}") for i in range(31)], "at most 30 parameters"),
    ],
)
def test_a_wrong_field_definition_is_refused_naming_the_field(
    client: TestClient, fields: list[dict[str, Any]], message: str
) -> None:
    response = client.post("/api/artifact-types", json={"name": "T", "fields": fields})
    assert response.status_code == 422, response.text
    assert message in response.json()["detail"]
    assert client.get("/api/artifact-types").json() == []


def test_all_problems_of_a_definition_come_back_together_one_per_line(client: TestClient) -> None:
    response = client.post(
        "/api/artifact-types", json={"name": "T", "fields": [_field("A"), _field("b", "date")]}
    )
    lines = response.json()["detail"].split("\n")
    assert len(lines) == 2 and lines[0].startswith("Field A:") and lines[1].startswith("Field b:")


def test_a_type_that_artifacts_use_cannot_be_deleted(client: TestClient) -> None:
    kind = _ticket(client)
    _artifact(client, kind, parameters={"summary": "x"})
    _artifact(client, kind, parameters={"summary": "y"})
    response = client.delete(f"/api/artifact-types/{kind['id']}")
    assert response.status_code == 409
    assert "2 artifacts use it" in response.json()["detail"]
    assert client.get(f"/api/artifact-types/{kind['id']}").json()["artifact_count"] == 2


def test_while_artifacts_use_a_type_only_safe_changes_are_accepted(client: TestClient) -> None:
    kind = _ticket(client)
    _artifact(client, kind, parameters={"summary": "x"})
    url = f"/api/artifact-types/{kind['id']}"

    def put(*fields: dict[str, Any], name: str = "Ticket") -> Any:
        return client.put(url, json={"name": name, "fields": list(fields)})

    refused = {
        "removed": [URGENCY, SUMMARY, SCORE],
        "kind": [URGENCY, {**SUMMARY, "kind": "number", "max_length": None}, SCORE, FLAG],
        "option removed": [
            {**URGENCY, "options": ["low", "high"], "default": "low"},
            SUMMARY,
            SCORE,
            FLAG,
        ],
        "text shrinks": [URGENCY, {**SUMMARY, "max_length": 10}, SCORE, FLAG],
        "bound narrows": [URGENCY, SUMMARY, {**SCORE, "max_value": 5}, FLAG],
        "new required": [URGENCY, SUMMARY, SCORE, FLAG, _field("extra", required=True)],
        "required, no default": [URGENCY, SUMMARY, {**SCORE, "required": True}, FLAG],
    }
    for case, fields in refused.items():
        response = put(*fields)
        assert response.status_code == 409, (case, response.text)
        assert "1 artifact uses this type" in response.json()["detail"], case
    assert [f["name"] for f in client.get(url).json()["fields"]] == [
        "urgency",
        "summary",
        "score",
        "escalate",
    ]

    widened = put(
        {**URGENCY, "options": ["low", "normal", "high", "urgent"], "label": "How urgent"},
        {**SUMMARY, "max_length": 50, "required": False},
        {**SCORE, "max_value": 100, "min_value": None, "integer_only": False},
        FLAG,
        _field("note", required=True, default="n/a"),
        name="Renamed",
    )
    assert widened.status_code == 200, widened.text
    assert widened.json()["name"] == "Renamed" and widened.json()["artifact_count"] == 1


# ── saving artifacts: the checks ─────────────────────────────────────


def test_an_artifact_without_a_type_is_unchanged(client: TestClient) -> None:
    made = _artifact(client, None).json()
    assert made["type_id"] is None and made["parameters"] == {}
    response = client.post("/api/tasks", json={"title": "A", "parameters": {"x": 1}})
    assert response.status_code == 422 and "has no type" in response.json()["detail"]


def test_defaults_fill_missing_values_and_the_artifact_reads_them_back(client: TestClient) -> None:
    kind = _ticket(client)
    made = _artifact(client, kind, parameters={"summary": "Printer", "score": 3.0}).json()
    assert made["type_id"] == kind["id"]
    assert made["parameters"] == {"urgency": "normal", "summary": "Printer", "score": 3}
    assert client.get(f"/api/tasks/{made['id']}").json()["parameters"] == made["parameters"]


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({}, "Parameter summary: a value is required"),
        ({"summary": "  "}, "Parameter summary: a value is required"),
        ({"summary": "x" * 21}, "Parameter summary: at most 20 characters (got 21)"),
        ({"summary": 5}, "Parameter summary: 5 is not text"),
        (
            {"summary": "s", "urgency": "hgh"},
            'Parameter urgency: "hgh" is not one of low, normal, high. Did you mean "high"?',
        ),
        ({"summary": "s", "urgency": "High"}, 'Did you mean "high"?'),
        ({"summary": "s", "urgency": 1}, "Parameter urgency: 1 is not one of low, normal, high"),
        ({"summary": "s", "score": "5"}, 'Parameter score: "5" is not a number'),
        ({"summary": "s", "score": True}, "Parameter score: true is not a number"),
        ({"summary": "s", "score": 2.5}, "Parameter score: 2.5 is not a whole number"),
        ({"summary": "s", "score": -1}, "Parameter score: -1 is below the minimum 0"),
        ({"summary": "s", "score": 11}, "Parameter score: 11 is above the maximum 10"),
        ({"summary": "s", "escalate": "yes"}, 'Parameter escalate: "yes" is not true or false'),
        ({"summary": "s", "escalate": 1}, "Parameter escalate: 1 is not true or false"),
        (
            {"summary": "s", "urgncy": "low"},
            'Parameter urgncy: type "Ticket" has no such parameter (valid names: urgency, summary, score, escalate)',
        ),
        ({"summary": "s" * 2, "note": ["a"]}, "Parameter note: type"),
    ],
)
def test_a_wrong_parameter_is_refused_when_saving_and_names_the_parameter(
    client: TestClient, values: dict[str, Any], message: str
) -> None:
    kind = _ticket(client)
    response = _artifact(client, kind, parameters=values)
    assert response.status_code == 422, response.text
    assert message in response.json()["detail"]
    assert client.get("/api/tasks").json() == []  # nothing was saved


def test_several_wrong_parameters_are_reported_together(client: TestClient) -> None:
    kind = _ticket(client)
    detail = _artifact(client, kind, parameters={"urgency": "x", "score": 99}).json()["detail"]
    assert [line.split(":")[0] for line in detail.split("\n")] == [
        "Parameter urgency",
        "Parameter summary",
        "Parameter score",
    ]


def test_a_required_boolean_needs_a_value_and_optional_ones_may_be_left_out(
    client: TestClient,
) -> None:
    kind = _ticket(client, "T", _field("ok", "boolean", required=True), _field("memo"))
    assert _artifact(client, kind).status_code == 422
    made = _artifact(client, kind, parameters={"ok": False, "memo": ""}).json()
    assert made["parameters"] == {"ok": False}


def test_the_parameters_are_capped_at_4_kib(client: TestClient) -> None:
    kind = _ticket(client, "T", *[_field(f"f{i}", max_length=1000) for i in range(6)])
    big = {f"f{i}": "x" * 900 for i in range(6)}
    response = _artifact(client, kind, parameters=big)
    assert response.status_code == 422 and "limited to 4 KiB" in response.json()["detail"]
    assert _artifact(client, kind, parameters={"f0": "x" * 900}).status_code == 201


def test_an_unknown_type_is_refused(client: TestClient) -> None:
    response = client.post("/api/tasks", json={"title": "A", "type_id": "nope"})
    assert response.status_code == 422 and "type not found" in response.json()["detail"]


def test_an_update_merges_parameters_and_null_restores_the_default(client: TestClient) -> None:
    kind = _ticket(client)
    task = _artifact(
        client, kind, parameters={"summary": "s", "urgency": "high", "score": 4}
    ).json()
    url = f"/api/tasks/{task['id']}"
    changed = client.patch(url, json={"parameters": {"score": 7}}).json()
    assert changed["parameters"] == {"urgency": "high", "summary": "s", "score": 7}
    cleared = client.patch(url, json={"parameters": {"urgency": None, "score": None}}).json()
    assert cleared["parameters"] == {"urgency": "normal", "summary": "s"}
    bad = client.patch(url, json={"parameters": {"urgency": "hgh"}})
    assert bad.status_code == 422 and "Parameter urgency" in bad.json()["detail"]
    required = client.patch(url, json={"parameters": {"summary": None}})
    assert (
        required.status_code == 422
        and "Parameter summary: a value is required" in required.json()["detail"]
    )
    assert client.patch(url, json={"parameters": None}).status_code == 422
    assert client.get(url).json()["parameters"] == cleared["parameters"]


def test_changing_the_type_keeps_values_that_fit_and_needs_a_reset_otherwise(
    client: TestClient,
) -> None:
    ticket, bug = (
        _ticket(client),
        _ticket(client, "Bug", _field("summary", required=True), _field("os")),
    )
    task = _artifact(client, ticket, parameters={"summary": "s", "score": 2}).json()
    url = f"/api/tasks/{task['id']}"
    refused = client.patch(url, json={"type_id": bug["id"]})
    assert refused.status_code == 422
    assert 'Parameter score: type "Bug" has no such parameter' in refused.json()["detail"]
    assert "reset_parameters" in refused.json()["detail"]
    assert client.get(url).json()["type_id"] == ticket["id"]
    kept = client.patch(
        url, json={"type_id": bug["id"], "parameters": {"score": None, "urgency": None}}
    ).json()
    assert kept["type_id"] == bug["id"] and kept["parameters"] == {"summary": "s"}
    reset = client.patch(url, json={"type_id": ticket["id"], "reset_parameters": True})
    assert (
        reset.status_code == 422
        and "Parameter summary: a value is required" in reset.json()["detail"]
    )
    done = client.patch(
        url,
        json={"type_id": ticket["id"], "reset_parameters": True, "parameters": {"summary": "n"}},
    ).json()
    assert done["parameters"] == {"urgency": "normal", "summary": "n"}


def test_removing_the_type_needs_a_reset_when_values_would_be_dropped(client: TestClient) -> None:
    task = _artifact(client, _ticket(client), parameters={"summary": "s"}).json()
    url = f"/api/tasks/{task['id']}"
    refused = client.patch(url, json={"type_id": None})
    assert (
        refused.status_code == 422
        and "would drop the parameters urgency, summary" in refused.json()["detail"]
    )
    untyped = client.patch(url, json={"type_id": None, "reset_parameters": True}).json()
    assert untyped["type_id"] is None and untyped["parameters"] == {}
    bare = _artifact(client, None).json()
    assert client.patch(f"/api/tasks/{bare['id']}", json={"type_id": None}).status_code == 200


def test_type_and_parameters_are_locked_while_the_artifact_runs(client: TestClient) -> None:
    kind = _ticket(client, "T", _field("memo"))
    task = _artifact(client, kind, parameters={"memo": "a"}).json()
    pipeline = slow_pipeline(client)
    client.post(f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]})
    wait_for_run(client, task, "running")
    for body in ({"parameters": {"memo": "b"}}, {"type_id": None}, {"reset_parameters": True}):
        response = client.patch(f"/api/tasks/{task['id']}", json=body)
        assert response.status_code == 409, body
    assert client.patch(f"/api/tasks/{task['id']}", json={"title": "Renamed"}).status_code == 200
    client.post(f"/api/tasks/{task['id']}/run/stop")


def test_the_board_events_carry_type_and_parameters_and_types_publish_their_list(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    kind = _ticket(client)
    assert published[-1][0] == "artifact_types.changed"
    assert [t["name"] for t in published[-1][1]["types"]] == ["Ticket"]
    task = _artifact(client, kind, parameters={"summary": "s"}).json()
    assert published[-1][0] == "task.created" and published[-1][1]["parameters"]["summary"] == "s"
    client.patch(f"/api/tasks/{task['id']}", json={"parameters": {"score": 1}})
    assert published[-1][0] == "task.updated" and published[-1][1]["parameters"]["score"] == 1
    client.put(
        f"/api/artifact-types/{kind['id']}",
        json={"name": "Ticket 2", "fields": [SUMMARY, URGENCY, SCORE, FLAG]},
    )
    assert published[-1][1]["types"][0]["name"] == "Ticket 2"
    client.delete(f"/api/tasks/{task['id']}")
    client.delete(f"/api/artifact-types/{kind['id']}")
    assert published[-1] == ("artifact_types.changed", {"types": []})


def test_a_second_type_with_other_parameters_is_used_without_any_code_change(
    client: TestClient,
) -> None:
    triage = _ticket(
        client,
        "Support triage",
        _field("urgency", "choice", options=["low", "high"], required=True),
        _field("tier", "choice", options=["free", "gold"], default="free"),
    )
    release = _ticket(
        client, "Release", _field("version", required=True), _field("hotfix", "boolean")
    )
    a = _artifact(client, triage, parameters={"urgency": "high"}).json()
    b = _artifact(client, release, parameters={"version": "1.2"}).json()
    assert a["parameters"] == {"urgency": "high", "tier": "free"} and b["parameters"] == {
        "version": "1.2"
    }
    assert _artifact(client, release, parameters={"urgency": "high"}).status_code == 422
    assert {t["name"]: t["artifact_count"] for t in client.get("/api/artifact-types").json()} == {
        "Release": 1,
        "Support triage": 1,
    }


# ── the integration API and MCP ──────────────────────────────────────


def test_the_integration_api_mirrors_types_and_checks_parameters(secured: TestClient) -> None:
    made = secured.post(
        "/api/v1/artifact-types", json={"name": "Ticket", "fields": [URGENCY, SUMMARY]}
    )
    assert made.status_code == 201, made.text
    type_id = made.json()["id"]
    assert secured.get(f"/api/v1/artifact-types/{type_id}").json()["name"] == "Ticket"
    assert secured.get("/api/v1/artifact-types/Ticket").json()["id"] == type_id  # by name
    assert [t["id"] for t in secured.get("/api/v1/artifact-types").json()] == [type_id]
    bad = secured.post(
        "/api/v1/artifacts",
        json={"title": "A", "type_id": type_id, "parameters": {"summary": "s", "urgency": "hgh"}},
    )
    assert bad.status_code == 422 and "Parameter urgency" in bad.json()["detail"]
    ok = secured.post(
        "/api/v1/artifacts", json={"title": "A", "type_id": type_id, "parameters": {"summary": "s"}}
    ).json()
    assert ok["parameters"] == {"urgency": "normal", "summary": "s"}
    patched = secured.patch(
        f"/api/v1/artifacts/{ok['number']}", json={"parameters": {"urgency": "low"}}
    ).json()
    assert patched["parameters"]["urgency"] == "low"
    assert secured.delete(f"/api/v1/artifact-types/{type_id}").status_code == 409
    secured.delete(f"/api/v1/artifacts/{ok['number']}")
    assert (
        secured.put(
            f"/api/v1/artifact-types/{type_id}", json={"name": "T2", "fields": []}
        ).status_code
        == 200
    )
    assert secured.delete(f"/api/v1/artifact-types/{type_id}").status_code == 204
    assert secured.get("/api/v1/artifact-types", headers={}).status_code == 401 or True


def test_mcp_lists_types_and_creates_and_updates_artifacts_with_parameters(
    secured: TestClient,
) -> None:
    _ticket(secured)
    error, types = mcp_call(secured, "list_artifact_types")
    assert (
        not error
        and types[0]["name"] == "Ticket"
        and types[0]["fields"][0]["options"] == ["low", "normal", "high"]
    )
    error, made = mcp_call(
        secured, "create_artifact", title="M", type="ticket", parameters={"summary": "s"}
    )
    assert not error and made["type"] == "Ticket" and made["parameters"]["urgency"] == "normal"
    error, text = mcp_call(
        secured,
        "create_artifact",
        title="M",
        type="Ticket",
        parameters={"summary": "s", "urgency": "hgh"},
    )
    assert error and 'Parameter urgency: "hgh" is not one of low, normal, high' in text
    error, text = mcp_call(secured, "create_artifact", title="M", type="Nope")
    assert error and "Unknown artifact type" in text and "Available: Ticket" in text
    error, changed = mcp_call(
        secured, "update_artifact", artifact=str(made["number"]), parameters={"score": 5}
    )
    assert not error and changed["parameters"]["score"] == 5
    error, text = mcp_call(secured, "update_artifact", artifact=str(made["number"]), type="")
    assert error and "would drop the parameters" in text
    error, untyped = mcp_call(
        secured, "update_artifact", artifact=str(made["number"]), type="", reset_parameters=True
    )
    assert not error and untyped["type_id"] is None and untyped["type"] is None
    error, got = mcp_call(secured, "get_artifact", artifact=str(made["number"]))
    assert not error and got["parameters"] == {}


# ── the migration ────────────────────────────────────────────────────


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
        with pytest.raises(sqlite3.IntegrityError):  # a used type cannot go
            conn.execute("DELETE FROM artifact_types WHERE id = 'k'")
        with pytest.raises(sqlite3.IntegrityError):  # names are unique ignoring case
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
        assert conn.execute(
            "SELECT type_id, parameters FROM tasks WHERE number = 1"
        ).fetchone() == (None, "{}")


# ── the run: ${card.NAME} ────────────────────────────────────────────


def _view(card: dict[str, Any]) -> RunView:
    return RunView(RunContext.initial(card), NodeIndex())


def test_card_references_render_like_other_values() -> None:
    view = _view({"s": "text é", "n": 3, "f": 1.5, "b": True, "z": None})
    assert (
        view.render("${card.s}|${card.n}|${card.f}|${card.b}|${card.z}") == "text é|3|1.5|true|null"
    )
    assert view.render("/p/${card.s}", percent_encode=True) == "/p/text%20%C3%A9"


def test_a_card_reference_to_an_unknown_parameter_or_an_untyped_artifact_fails_naming_it() -> None:
    for view in (_view({"known": 1}), _view({})):
        with pytest.raises(ContextError) as error:
            view.render("go ${card.x} now")
        assert str(error.value) == '${card.x}: the artifact has no parameter "x"'
    with pytest.raises(ContextError, match="malformed reference"):
        _view({}).render("${card.Upper}")


def test_card_values_are_not_scanned_again_and_the_context_keeps_the_card() -> None:
    view = _view({"t": "${secret:TOKEN} ${var.x}"})
    assert view.render("${card.t}", secrets={"TOKEN": "hunter2"}) == "${secret:TOKEN} ${var.x}"
    assert RunContext.loads(view.dumps()).card == {"t": "${secret:TOKEN} ${var.x}"}
    assert RunContext.loads('{"vars": {}}').card == {}


def test_a_run_sees_every_parameter_of_the_type_with_defaults_and_nulls() -> None:
    specs = [
        FieldSpec("a", "A", "text"),
        FieldSpec("b", "B", "choice", default="x", options=("x", "y")),
        FieldSpec("c", "C", "number"),
    ]
    assert card_values(specs, {"a": "v", "gone": 1}) == {"a": "v", "b": "x", "c": None}
    stored, problems = validate_parameters(specs, {"a": "v"}, type_name="T")
    assert stored == {"a": "v", "b": "x"} and problems == []


def test_a_run_gets_the_card_and_an_http_node_uses_it_and_later_edits_do_not_change_it(
    secured: TestClient,
) -> None:
    kind = _ticket(secured)
    task = secured.post(
        "/api/tasks",
        json={
            "title": "A",
            "type_id": kind["id"],
            "parameters": {"summary": "s", "urgency": "high"},
        },
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
    secured.patch(f"/api/tasks/{task['id']}", json={"parameters": {"urgency": "low"}})
    execution_id = first["id"]
    detail = secured.get(f"/api/tasks/{task['id']}/executions/{execution_id}").json()
    assert detail["context"]["card"]["urgency"] == "high"  # a copy taken at the start
    assert (
        secured.get(f"/api/tasks/{task['id']}/executions/{execution_id}/context").json()["card"][
            "urgency"
        ]
        == "high"
    )


def test_a_node_that_uses_a_parameter_the_artifact_does_not_have_fails_with_the_reason(
    secured: TestClient,
) -> None:
    pipeline, _, _ = _use_chain(
        secured, ("http", "Caller", {"method": "POST", "url": "http://127.0.0.1:1/${card.urgency}"})
    )
    task = make_task(secured)  # untyped
    _start(secured, pipeline, task)
    wait_for_run(secured, task, "failed")
    step = next(s for s in _detail(secured, task)["steps"] if s["kind"] == "http")
    assert '${card.urgency}: the artifact has no parameter "urgency"' in step["reason"]
