"""Workflow definitions: port rules, API, cascades."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.config import Settings
from openartifact.models import NodeKind
from openartifact.workflow.rules import EdgeError, Endpoint, validate_edge
from tests.conftest import alembic_config

# ── Port rules ────────────────────────────────────────────────────────

TRIGGER = Endpoint("t", NodeKind.TRIGGER)
S1 = Endpoint("s1", NodeKind.STAGE)
S2 = Endpoint("s2", NodeKind.STAGE)
A1 = Endpoint("a1", NodeKind.ACTION, stage_id="s1")
A2 = Endpoint("a2", NodeKind.ACTION, stage_id="s1")
B1 = Endpoint("b1", NodeKind.ACTION, stage_id="s2")
END = Endpoint("e", NodeKind.COMPLETE)


@pytest.mark.parametrize(
    ("source", "source_port", "target", "target_port"),
    [
        (TRIGGER, "out", S1, "start"),
        (S1, "end", S2, "start"),
        (S1, "end", END, "in"),
        (S1, "start", A1, "in"),
        (A1, "pass", A2, "in"),
        (A1, "error", A2, "in"),
        (A1, "error", A1, "in"),  # an error may retry the same action
        (A1, "pass", S1, "end"),
        (A1, "error", S1, "end"),  # allowed on purpose
    ],
)
def test_allowed_connections(
    source: Endpoint, source_port: str, target: Endpoint, target_port: str
) -> None:
    validate_edge(source, source_port, target, target_port)


@pytest.mark.parametrize(
    ("source", "source_port", "target", "target_port"),
    [
        (TRIGGER, "out", A1, "in"),  # actions are reached from inside a stage
        (TRIGGER, "out", END, "in"),
        (TRIGGER, "in", S1, "start"),  # no such output
        (S1, "end", S1, "start"),  # not to itself
        (S1, "end", S2, "end"),  # the end is fed from inside
        (S1, "start", B1, "in"),  # an action of another stage
        (S1, "start", S2, "start"),
        (A1, "pass", B1, "in"),  # across stages
        (A1, "pass", S2, "end"),
        (A1, "pass", S1, "start"),  # the stage's start is fed from outside
        (A1, "pass", END, "in"),
        (END, "pass", A1, "in"),  # no such output
        (A1, "pass", A2, "pass"),  # no such input
    ],
)
def test_rejected_connections(
    source: Endpoint, source_port: str, target: Endpoint, target_port: str
) -> None:
    with pytest.raises(EdgeError):
        validate_edge(source, source_port, target, target_port)


# ── API ───────────────────────────────────────────────────────────────


def _workflow(client: TestClient, name: str = "Flow") -> dict[str, Any]:
    return client.post("/api/workflows", json={"name": name}).json()  # type: ignore[no-any-return]


def _node(client: TestClient, workflow: dict[str, Any], kind: str, **extra: Any) -> dict[str, Any]:
    response = client.post(f"/api/workflows/{workflow['id']}/nodes", json={"kind": kind, **extra})
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def _edge(
    client: TestClient,
    workflow: dict[str, Any],
    a: dict[str, Any],
    ap: str,
    b: dict[str, Any],
    bp: str,
) -> Any:
    return client.post(
        f"/api/workflows/{workflow['id']}/edges",
        json={"source_id": a["id"], "source_port": ap, "target_id": b["id"], "target_port": bp},
    )


def _graph(client: TestClient, workflow: dict[str, Any]) -> dict[str, Any]:
    return client.get(f"/api/workflows/{workflow['id']}").json()  # type: ignore[no-any-return]


def test_new_workflow_starts_with_a_trigger(client: TestClient) -> None:
    workflow = _workflow(client)
    graph = _graph(client, workflow)
    assert [n["kind"] for n in graph["nodes"]] == ["trigger"]
    assert graph["edges"] == []
    assert workflow["status"] == "draft"


def test_workflow_crud(client: TestClient) -> None:
    first, second = _workflow(client, "A"), _workflow(client, "B")
    assert {w["name"] for w in client.get("/api/workflows").json()} == {"A", "B"}
    assert client.patch(f"/api/workflows/{first['id']}", json={"name": "A2"}).json()["name"] == "A2"
    assert client.delete(f"/api/workflows/{second['id']}").status_code == 204
    assert [w["name"] for w in client.get("/api/workflows").json()] == ["A2"]
    assert client.get(f"/api/workflows/{second['id']}").status_code == 404


def test_name_is_required(client: TestClient) -> None:
    assert client.post("/api/workflows", json={"name": "   "}).status_code == 422
    assert client.post("/api/workflows", json={}).status_code == 422


def test_node_kinds_and_defaults(client: TestClient) -> None:
    workflow = _workflow(client)
    stage = _node(client, workflow, "stage", x=100, y=50)
    assert (stage["name"], stage["width"], stage["height"]) == ("Stage", 360, 240)
    action = _node(client, workflow, "action", stage_id=stage["id"], x=20, y=40)
    assert (action["name"], action["stage_id"], action["width"]) == ("Action", stage["id"], None)
    assert _node(client, workflow, "complete")["name"] == "Complete"


def test_action_needs_a_stage_of_the_same_workflow(client: TestClient) -> None:
    one, other = _workflow(client), _workflow(client)
    stage = _node(client, other, "stage")
    url = f"/api/workflows/{one['id']}/nodes"
    assert client.post(url, json={"kind": "action"}).status_code == 422
    assert client.post(url, json={"kind": "action", "stage_id": stage["id"]}).status_code == 422
    assert client.post(url, json={"kind": "stage", "stage_id": stage["id"]}).status_code == 422


def test_move_rename_and_resize(client: TestClient) -> None:
    workflow = _workflow(client)
    stage = _node(client, workflow, "stage")
    url = f"/api/workflows/{workflow['id']}/nodes/{stage['id']}"
    changed = client.patch(
        url, json={"name": "Refine", "x": 10, "y": 20, "width": 500, "height": 300}
    ).json()
    assert (changed["name"], changed["x"], changed["y"], changed["width"], changed["height"]) == (
        "Refine",
        10,
        20,
        500,
        300,
    )
    action = _node(client, workflow, "action", stage_id=stage["id"])
    assert (
        client.patch(
            f"/api/workflows/{workflow['id']}/nodes/{action['id']}", json={"width": 10}
        ).status_code
        == 422
    )
    assert client.patch(url, json={"width": 0}).status_code == 422


def test_connect_validates_and_replaces_the_output_edge(client: TestClient) -> None:
    workflow = _workflow(client)
    trigger = _graph(client, workflow)["nodes"][0]
    one, two = _node(client, workflow, "stage"), _node(client, workflow, "stage")
    assert _edge(client, workflow, trigger, "out", one, "start").status_code == 201
    assert _edge(client, workflow, trigger, "out", two, "start").status_code == 201  # replaces
    edges = _graph(client, workflow)["edges"]
    assert [e["target_id"] for e in edges] == [two["id"]]
    assert _edge(client, workflow, trigger, "out", trigger, "in").status_code == 422
    assert _edge(client, workflow, one, "end", one, "start").status_code == 422


def test_edges_remember_style_and_stage_slots(client: TestClient) -> None:
    workflow = _workflow(client)
    trigger = _graph(client, workflow)["nodes"][0]
    stage = _node(client, workflow, "stage")
    url = f"/api/workflows/{workflow['id']}/edges"
    body = {
        "source_id": trigger["id"],
        "source_port": "out",
        "target_id": stage["id"],
        "target_port": "start",
    }
    created = client.post(url, json=body).json()
    assert (created["style"], created["source_slot"], created["target_slot"]) == ("curved", 0, 0)

    created = client.post(url, json={**body, "style": "elbow", "target_slot": 2}).json()
    assert (created["style"], created["target_slot"]) == ("elbow", 2)
    assert client.post(url, json={**body, "target_slot": 3}).status_code == 422
    assert (
        client.post(url, json={**body, "source_slot": 1}).status_code == 422
    )  # trigger: one point

    changed = client.patch(f"{url}/{created['id']}", json={"style": "straight"}).json()
    assert changed["style"] == "straight"
    assert client.patch(f"{url}/{created['id']}", json={"style": "wavy"}).status_code == 422
    assert client.patch(f"{url}/missing", json={"style": "straight"}).status_code == 404


def test_inputs_take_several_edges(client: TestClient) -> None:
    workflow = _workflow(client)
    stage = _node(client, workflow, "stage")
    a, b = (_node(client, workflow, "action", stage_id=stage["id"]) for _ in range(2))
    target = _node(client, workflow, "action", stage_id=stage["id"])
    assert _edge(client, workflow, a, "pass", target, "in").status_code == 201
    assert _edge(client, workflow, b, "pass", target, "in").status_code == 201
    assert _edge(client, workflow, a, "error", target, "in").status_code == 201
    assert len(_graph(client, workflow)["edges"]) == 3


def test_edges_across_workflows_are_rejected(client: TestClient) -> None:
    one, other = _workflow(client), _workflow(client)
    stage = _node(client, other, "stage")
    trigger = _graph(client, one)["nodes"][0]
    assert _edge(client, one, trigger, "out", stage, "start").status_code == 422


def test_disconnect(client: TestClient) -> None:
    workflow = _workflow(client)
    trigger = _graph(client, workflow)["nodes"][0]
    stage = _node(client, workflow, "stage")
    edge = _edge(client, workflow, trigger, "out", stage, "start").json()
    assert client.delete(f"/api/workflows/{workflow['id']}/edges/{edge['id']}").status_code == 204
    assert _graph(client, workflow)["edges"] == []
    assert client.delete(f"/api/workflows/{workflow['id']}/edges/{edge['id']}").status_code == 404


def test_deleting_a_stage_removes_its_actions_and_all_their_edges(client: TestClient) -> None:
    workflow = _workflow(client)
    trigger = _graph(client, workflow)["nodes"][0]
    stage, other = _node(client, workflow, "stage"), _node(client, workflow, "stage")
    action = _node(client, workflow, "action", stage_id=stage["id"])
    _edge(client, workflow, trigger, "out", stage, "start")
    _edge(client, workflow, stage, "start", action, "in")
    _edge(client, workflow, stage, "end", other, "start")
    assert client.delete(f"/api/workflows/{workflow['id']}/nodes/{stage['id']}").status_code == 204
    graph = _graph(client, workflow)
    assert sorted(n["kind"] for n in graph["nodes"]) == ["stage", "trigger"]
    assert graph["edges"] == []


def test_deleting_a_workflow_removes_everything_in_it(
    client: TestClient, migrated_settings: Settings
) -> None:
    workflow = _workflow(client)
    _node(client, workflow, "stage")
    client.delete(f"/api/workflows/{workflow['id']}")
    with sqlite3.connect(migrated_settings.data_dir / migrated_settings.database_filename) as conn:
        assert conn.execute("SELECT COUNT(*) FROM workflow_nodes").fetchone() == (0,)


def test_unknown_ids_are_404(client: TestClient) -> None:
    workflow = _workflow(client)
    assert client.get("/api/workflows/nope").status_code == 404
    assert client.post("/api/workflows/nope/nodes", json={"kind": "stage"}).status_code == 404
    assert (
        client.patch(f"/api/workflows/{workflow['id']}/nodes/nope", json={"name": "x"}).status_code
        == 404
    )
    assert client.delete(f"/api/workflows/{workflow['id']}/nodes/nope").status_code == 404


def test_migration_0008_is_reversible(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    command.upgrade(alembic_config(), "head")
    command.downgrade(alembic_config(), "0007")
    with sqlite3.connect(settings.data_dir / settings.database_filename) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {"workflows", "workflow_nodes", "workflow_edges"} & tables


def test_migration_0009_merges_the_inner_and_outer_stage_ports(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    command.upgrade(alembic_config(), "0008")
    db = settings.data_dir / settings.database_filename
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO workflows (id, name) VALUES ('w', 'W')")
        for node_id, kind, stage in (
            ("t", "trigger", None),
            ("s", "stage", None),
            ("a", "action", "s"),
            ("s2", "stage", None),
        ):
            conn.execute(
                "INSERT INTO workflow_nodes (id, workflow_id, kind, stage_id, name) VALUES (?, 'w', ?, ?, ?)",
                (node_id, kind, stage, node_id),
            )
        for edge_id, src, sp, dst, dp in (
            ("e1", "t", "out", "s", "in"),
            ("e2", "s", "entry", "a", "in"),
            ("e3", "a", "pass", "s", "exit"),
            ("e4", "s", "out", "s2", "in"),
        ):
            conn.execute(
                "INSERT INTO workflow_edges (id, workflow_id, source_id, source_port, target_id, target_port) "
                "VALUES (?, 'w', ?, ?, ?, ?)",
                (edge_id, src, sp, dst, dp),
            )
    command.upgrade(alembic_config(), "0009")
    query = "SELECT id, source_port, target_port FROM workflow_edges ORDER BY id"
    with sqlite3.connect(db) as conn:
        assert conn.execute(query).fetchall() == [
            ("e1", "out", "start"),
            ("e2", "start", "in"),
            ("e3", "pass", "end"),
            ("e4", "end", "start"),
        ]
    command.downgrade(alembic_config(), "0008")
    with sqlite3.connect(db) as conn:
        assert conn.execute(query).fetchall() == [
            ("e1", "out", "in"),
            ("e2", "entry", "in"),
            ("e3", "pass", "exit"),
            ("e4", "out", "in"),
        ]


def test_migration_0010_adds_defaults_and_is_reversible(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    command.upgrade(alembic_config(), "0009")
    db = settings.data_dir / settings.database_filename
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO workflows (id, name) VALUES ('w', 'W')")
        for node_id, kind in (("t", "trigger"), ("s", "stage")):
            conn.execute(
                "INSERT INTO workflow_nodes (id, workflow_id, kind, name) VALUES (?, 'w', ?, ?)",
                (node_id, kind, node_id),
            )
        conn.execute(
            "INSERT INTO workflow_edges (id, workflow_id, source_id, source_port, target_id, target_port) "
            "VALUES ('e', 'w', 't', 'out', 's', 'start')"
        )
    command.upgrade(alembic_config(), "0010")
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT style, source_slot, target_slot FROM workflow_edges").fetchone()
    assert row == ("curved", 0, 0)
    command.downgrade(alembic_config(), "0009")
    with sqlite3.connect(db) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(workflow_edges)")}
    assert not {"style", "source_slot", "target_slot"} & columns


def _action_definition(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/workflows", json={"name": "Gap analysis", "kind": "action"})
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]


def test_action_definitions_are_listed_apart_from_workflows(client: TestClient) -> None:
    _workflow(client, "A workflow")
    definition = _action_definition(client)
    assert definition["kind"] == "action"
    assert [w["name"] for w in client.get("/api/workflows").json()] == ["A workflow"]
    listed = client.get("/api/workflows", params={"kind": "action"}).json()
    assert [w["id"] for w in listed] == [definition["id"]]


def test_an_action_definition_starts_with_trigger_and_output(client: TestClient) -> None:
    graph = _graph(client, _action_definition(client))
    assert sorted(n["kind"] for n in graph["nodes"]) == ["output", "trigger"]
    assert all(n["fail_enabled"] is False for n in graph["nodes"])


def test_trigger_feeds_the_output_and_on_fail_is_optional(client: TestClient) -> None:
    definition = _action_definition(client)
    nodes = {n["kind"]: n for n in _graph(client, definition)["nodes"]}
    assert (
        _edge(client, definition, nodes["trigger"], "out", nodes["output"], "in").status_code == 201
    )
    url = f"/api/workflows/{definition['id']}/nodes/{nodes['output']['id']}"
    assert client.patch(url, json={"fail_enabled": True}).json()["fail_enabled"] is True
    assert client.patch(url, json={"fail_enabled": False}).json()["fail_enabled"] is False
    trigger_url = f"/api/workflows/{definition['id']}/nodes/{nodes['trigger']['id']}"
    assert client.patch(trigger_url, json={"fail_enabled": True}).status_code == 422


def test_an_action_definition_keeps_its_trigger_and_output(client: TestClient) -> None:
    definition = _action_definition(client)
    base = f"/api/workflows/{definition['id']}/nodes"
    for node in _graph(client, definition)["nodes"]:
        assert client.delete(f"{base}/{node['id']}").status_code == 422
    for kind in ("stage", "complete", "output", "trigger"):
        assert client.post(base, json={"kind": kind}).status_code == 422


def test_a_workflow_has_no_output_node(client: TestClient) -> None:
    workflow = _workflow(client)
    response = client.post(f"/api/workflows/{workflow['id']}/nodes", json={"kind": "output"})
    assert response.status_code == 422


def test_migration_0011_marks_existing_workflows_and_is_reversible(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    command.upgrade(alembic_config(), "0010")
    db = settings.data_dir / settings.database_filename
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO workflows (id, name) VALUES ('w', 'W')")
    command.upgrade(alembic_config(), "0011")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT kind FROM workflows").fetchall() == [("workflow",)]
        conn.execute("INSERT INTO workflows (id, name, kind) VALUES ('a', 'A', 'action')")
        conn.execute(
            "INSERT INTO workflow_nodes (id, workflow_id, kind, name) VALUES ('o', 'a', 'output', 'O')"
        )
    command.downgrade(alembic_config(), "0010")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id FROM workflows").fetchall() == [("w",)]
        assert conn.execute("SELECT count(*) FROM workflow_nodes").fetchone() == (0,)
