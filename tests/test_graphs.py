"""Graphs (pipelines and action definitions): port rules, API, cascades, migrations."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.config import Settings
from openartifact.graph.rules import EdgeError, Endpoint, validate_edge
from openartifact.models import NodeKind

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
        (TRIGGER, "out", END, "in"),  # the default connection
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


def _url(graph: dict[str, Any]) -> str:
    return f"/api/{'actions' if graph['kind'] == 'action' else 'pipelines'}/{graph['id']}"


def _pipeline(client: TestClient, name: str = "Flow") -> dict[str, Any]:
    return client.post("/api/pipelines", json={"name": name}).json()  # type: ignore[no-any-return]


def _node(client: TestClient, pipeline: dict[str, Any], kind: str, **extra: Any) -> dict[str, Any]:
    response = client.post(f"{_url(pipeline)}/nodes", json={"kind": kind, **extra})
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def _edge(
    client: TestClient,
    pipeline: dict[str, Any],
    a: dict[str, Any],
    ap: str,
    b: dict[str, Any],
    bp: str,
) -> Any:
    return client.post(
        f"{_url(pipeline)}/edges",
        json={"source_id": a["id"], "source_port": ap, "target_id": b["id"], "target_port": bp},
    )


def _graph(client: TestClient, pipeline: dict[str, Any]) -> dict[str, Any]:
    return client.get(_url(pipeline)).json()  # type: ignore[no-any-return]


def test_new_pipeline_has_a_trigger_and_a_complete_connected_with_each_other(
    client: TestClient,
) -> None:
    pipeline = _pipeline(client)
    graph = _graph(client, pipeline)
    nodes = {n["kind"]: n for n in graph["nodes"]}
    assert sorted(nodes) == ["complete", "trigger"]
    assert [
        (e["source_id"], e["source_port"], e["target_id"], e["target_port"]) for e in graph["edges"]
    ] == [(nodes["trigger"]["id"], "out", nodes["complete"]["id"], "in")]
    assert pipeline["status"] == "draft"


def test_pipeline_crud(client: TestClient) -> None:
    first, second = _pipeline(client, "A"), _pipeline(client, "B")
    assert {w["name"] for w in client.get("/api/pipelines").json()} == {"A", "B"}
    assert client.patch(_url(first), json={"name": "A2"}).json()["name"] == "A2"
    assert client.delete(_url(second)).status_code == 204
    assert [w["name"] for w in client.get("/api/pipelines").json()] == ["A2"]
    assert client.get(_url(second)).status_code == 404


def test_name_is_required(client: TestClient) -> None:
    assert client.post("/api/pipelines", json={"name": "   "}).status_code == 422
    assert client.post("/api/pipelines", json={}).status_code == 422


def test_node_kinds_and_defaults(client: TestClient) -> None:
    pipeline = _pipeline(client)
    stage = _node(client, pipeline, "stage", x=100, y=50)
    assert (stage["name"], stage["width"], stage["height"]) == ("Stage", 360, 240)
    action = _node(client, pipeline, "action", stage_id=stage["id"], x=20, y=40)
    assert (action["name"], action["stage_id"], action["width"]) == ("Action", stage["id"], None)


def test_trigger_and_complete_cannot_be_added_or_deleted(client: TestClient) -> None:
    pipeline = _pipeline(client)
    base = f"{_url(pipeline)}/nodes"
    for kind in ("trigger", "complete"):
        assert client.post(base, json={"kind": kind}).status_code == 422
    for node in _graph(client, pipeline)["nodes"]:
        assert client.delete(f"{base}/{node['id']}").status_code == 422


def test_action_needs_a_stage_of_the_same_pipeline(client: TestClient) -> None:
    one, other = _pipeline(client), _pipeline(client)
    stage = _node(client, other, "stage")
    url = f"{_url(one)}/nodes"
    assert client.post(url, json={"kind": "action"}).status_code == 422
    assert client.post(url, json={"kind": "action", "stage_id": stage["id"]}).status_code == 422
    assert client.post(url, json={"kind": "stage", "stage_id": stage["id"]}).status_code == 422


def test_move_rename_and_resize(client: TestClient) -> None:
    pipeline = _pipeline(client)
    stage = _node(client, pipeline, "stage")
    url = f"{_url(pipeline)}/nodes/{stage['id']}"
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
    action = _node(client, pipeline, "action", stage_id=stage["id"])
    assert (
        client.patch(f"{_url(pipeline)}/nodes/{action['id']}", json={"width": 10}).status_code
        == 422
    )
    assert client.patch(url, json={"width": 0}).status_code == 422


def test_connect_validates_and_replaces_the_output_edge(client: TestClient) -> None:
    pipeline = _pipeline(client)
    trigger = _graph(client, pipeline)["nodes"][0]
    one, two = _node(client, pipeline, "stage"), _node(client, pipeline, "stage")
    assert _edge(client, pipeline, trigger, "out", one, "start").status_code == 201
    assert _edge(client, pipeline, trigger, "out", two, "start").status_code == 201  # replaces
    edges = _graph(client, pipeline)["edges"]
    assert [e["target_id"] for e in edges] == [two["id"]]
    assert _edge(client, pipeline, trigger, "out", trigger, "in").status_code == 422
    assert _edge(client, pipeline, one, "end", one, "start").status_code == 422


def test_edges_remember_style_and_stage_slots(client: TestClient) -> None:
    pipeline = _pipeline(client)
    trigger = _graph(client, pipeline)["nodes"][0]
    stage = _node(client, pipeline, "stage")
    url = f"{_url(pipeline)}/edges"
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
    pipeline = _pipeline(client)
    stage = _node(client, pipeline, "stage")
    a, b = (_node(client, pipeline, "action", stage_id=stage["id"]) for _ in range(2))
    target = _node(client, pipeline, "action", stage_id=stage["id"])
    assert _edge(client, pipeline, a, "pass", target, "in").status_code == 201
    assert _edge(client, pipeline, b, "pass", target, "in").status_code == 201
    assert (
        _edge(client, pipeline, a, "error", target, "in").status_code == 422
    )  # not there (ADR-061)
    client.patch(
        f"{_url(pipeline)}/nodes/{a['id']}", json={"config": {"on_failure": "error_output"}}
    )
    assert _edge(client, pipeline, a, "error", target, "in").status_code == 201
    assert len(_graph(client, pipeline)["edges"]) == 4  # the three and the default one


def test_edges_across_pipelines_are_rejected(client: TestClient) -> None:
    one, other = _pipeline(client), _pipeline(client)
    stage = _node(client, other, "stage")
    trigger = _graph(client, one)["nodes"][0]
    assert _edge(client, one, trigger, "out", stage, "start").status_code == 422


def test_disconnect(client: TestClient) -> None:
    pipeline = _pipeline(client)
    trigger = _graph(client, pipeline)["nodes"][0]
    stage = _node(client, pipeline, "stage")
    edge = _edge(client, pipeline, trigger, "out", stage, "start").json()
    assert client.delete(f"{_url(pipeline)}/edges/{edge['id']}").status_code == 204
    assert _graph(client, pipeline)["edges"] == []
    assert client.delete(f"{_url(pipeline)}/edges/{edge['id']}").status_code == 404


def test_deleting_a_stage_removes_its_actions_and_all_their_edges(client: TestClient) -> None:
    pipeline = _pipeline(client)
    trigger = next(n for n in _graph(client, pipeline)["nodes"] if n["kind"] == "trigger")
    stage, other = _node(client, pipeline, "stage"), _node(client, pipeline, "stage")
    action = _node(client, pipeline, "action", stage_id=stage["id"])
    _edge(client, pipeline, trigger, "out", stage, "start")
    _edge(client, pipeline, stage, "start", action, "in")
    _edge(client, pipeline, stage, "end", other, "start")
    assert client.delete(f"{_url(pipeline)}/nodes/{stage['id']}").status_code == 204
    graph = _graph(client, pipeline)
    assert sorted(n["kind"] for n in graph["nodes"]) == ["complete", "stage", "trigger"]
    assert graph["edges"] == []


def test_deleting_a_pipeline_removes_everything_in_it(
    client: TestClient, migrated_settings: Settings
) -> None:
    pipeline = _pipeline(client)
    _node(client, pipeline, "stage")
    client.delete(_url(pipeline))
    with sqlite3.connect(migrated_settings.data_dir / migrated_settings.database_filename) as conn:
        assert conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone() == (0,)


def test_unknown_ids_are_404(client: TestClient) -> None:
    pipeline = _pipeline(client)
    assert client.get("/api/pipelines/nope").status_code == 404
    assert client.post("/api/pipelines/nope/nodes", json={"kind": "stage"}).status_code == 404
    assert client.patch(f"{_url(pipeline)}/nodes/nope", json={"name": "x"}).status_code == 404
    assert client.delete(f"{_url(pipeline)}/nodes/nope").status_code == 404


def _action_definition(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/actions", json={"name": "Gap analysis"})
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]


def test_action_definitions_are_listed_apart_from_pipelines(client: TestClient) -> None:
    _pipeline(client, "A pipeline")
    definition = _action_definition(client)
    assert definition["kind"] == "action"
    assert [w["name"] for w in client.get("/api/pipelines").json()] == ["A pipeline"]
    listed = client.get("/api/actions").json()
    assert [w["id"] for w in listed] == [definition["id"]]


def test_an_action_definition_starts_with_trigger_and_output(client: TestClient) -> None:
    graph = _graph(client, _action_definition(client))
    assert sorted(n["kind"] for n in graph["nodes"]) == ["output", "trigger"]
    assert all(n["fail_enabled"] is False for n in graph["nodes"])


def test_an_action_definition_starts_with_trigger_connected_to_on_pass(
    client: TestClient,
) -> None:
    definition = _action_definition(client)
    graph = _graph(client, definition)
    nodes = {n["kind"]: n for n in graph["nodes"]}
    assert [(e["source_port"], e["target_id"], e["target_port"]) for e in graph["edges"]] == [
        ("out", nodes["output"]["id"], "pass")
    ]


def test_the_output_has_separate_on_pass_and_on_fail_connectors(client: TestClient) -> None:
    definition = _action_definition(client)
    nodes = {n["kind"]: n for n in _graph(client, definition)["nodes"]}
    trigger, output = nodes["trigger"], nodes["output"]
    assert _edge(client, definition, trigger, "out", output, "in").status_code == 422  # gone
    assert (
        _edge(client, definition, trigger, "out", output, "fail").status_code == 422
    )  # not on yet
    url = f"{_url(definition)}/nodes/{output['id']}"
    assert client.patch(url, json={"fail_enabled": True}).json()["fail_enabled"] is True
    assert _edge(client, definition, trigger, "out", output, "fail").status_code == 201
    assert [e["target_port"] for e in _graph(client, definition)["edges"]] == ["fail"]
    client.patch(url, json={"fail_enabled": False})  # the On Fail connector goes, and its edge
    assert _graph(client, definition)["edges"] == []
    trigger_url = f"{_url(definition)}/nodes/{trigger['id']}"
    assert client.patch(trigger_url, json={"fail_enabled": True}).status_code == 422


def test_an_action_definition_keeps_its_trigger_and_output(client: TestClient) -> None:
    definition = _action_definition(client)
    base = f"{_url(definition)}/nodes"
    for node in _graph(client, definition)["nodes"]:
        assert client.delete(f"{base}/{node['id']}").status_code == 422
    for kind in ("stage", "complete", "output", "trigger"):
        assert client.post(base, json={"kind": kind}).status_code == 422


def test_a_pipeline_has_no_output_node(client: TestClient) -> None:
    pipeline = _pipeline(client)
    response = client.post(f"{_url(pipeline)}/nodes", json={"kind": "output"})
    assert response.status_code == 422


# ── linking an action to an action definition ─────────────────────────


def _shell(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    pipeline = _pipeline(client)
    stage = _node(client, pipeline, "stage")
    return pipeline, _node(client, pipeline, "action", stage_id=stage["id"])


def _link(client: TestClient, pipeline: dict[str, Any], node: dict[str, Any], target: Any) -> Any:
    return client.patch(f"{_url(pipeline)}/nodes/{node['id']}", json={"definition_id": target})


def test_an_action_shell_links_to_a_definition_and_shows_its_name(client: TestClient) -> None:
    pipeline, shell = _shell(client)
    assert shell["definition_id"] is None
    definition = _action_definition(client)
    linked = _link(client, pipeline, shell, definition["id"]).json()
    assert (linked["definition_id"], linked["definition_name"]) == (
        definition["id"],
        "Gap analysis",
    )
    assert linked["definition_fail_enabled"] is False
    node = next(n for n in _graph(client, pipeline)["nodes"] if n["id"] == shell["id"])
    assert node["definition_name"] == "Gap analysis"
    assert _link(client, pipeline, shell, None).json()["definition_id"] is None


def test_only_actions_link_to_existing_action_definitions(client: TestClient) -> None:
    pipeline, shell = _shell(client)
    stage = next(n for n in _graph(client, pipeline)["nodes"] if n["kind"] == "stage")
    definition = _action_definition(client)
    assert _link(client, pipeline, stage, definition["id"]).status_code == 422
    assert _link(client, pipeline, shell, "missing").status_code == 422
    assert _link(client, pipeline, shell, pipeline["id"]).status_code == 422  # not a definition


def test_the_error_output_of_an_action_follows_its_setting_and_is_kept_in_step_with_its_definition(
    client: TestClient,
) -> None:
    """The action's setting decides whether On Error exists (ADR-061); the definition's On Fail is kept in step with it
    in both directions (ADR-061 addendum)."""
    pipeline, shell = _shell(client)
    other = _node(client, pipeline, "action", stage_id=shell["stage_id"])
    definition = _action_definition(client)
    output = next(n for n in _graph(client, definition)["nodes"] if n["kind"] == "output")
    client.patch(f"{_url(definition)}/nodes/{output['id']}", json={"fail_enabled": False})
    _link(client, pipeline, shell, definition["id"])
    assert _edge(client, pipeline, shell, "error", other, "in").status_code == 422  # not there
    client.patch(
        f"{_url(pipeline)}/nodes/{shell['id']}", json={"config": {"on_failure": "error_output"}}
    )
    assert _edge(client, pipeline, shell, "error", other, "in").status_code == 201
    # setting it on the action switched On Fail on in the definition
    assert next(n for n in _graph(client, definition)["nodes"] if n["id"] == output["id"])[
        "fail_enabled"
    ]
    # switching it off there takes the action's connection and its setting with it
    client.patch(f"{_url(definition)}/nodes/{output['id']}", json={"fail_enabled": False})
    assert [
        e["source_port"] for e in _graph(client, pipeline)["edges"] if e["source_id"] == shell["id"]
    ] == []
    node = next(n for n in _graph(client, pipeline)["nodes"] if n["id"] == shell["id"])
    assert node["config"]["on_failure"] == "fail"
    assert _edge(client, pipeline, shell, "pass", other, "in").status_code == 201


def test_deleting_a_definition_turns_its_actions_back_into_shells(client: TestClient) -> None:
    pipeline, shell = _shell(client)
    definition = _action_definition(client)
    _link(client, pipeline, shell, definition["id"])
    assert client.delete(_url(definition)).status_code == 204
    node = next(n for n in _graph(client, pipeline)["nodes"] if n["id"] == shell["id"])
    assert node["definition_id"] is None


def test_slugs_follow_the_name_and_are_unique_per_kind(client: TestClient) -> None:
    first = _pipeline(client, "Käse & Brot!")
    second = _pipeline(client, "Kaese brot")
    assert (first["slug"], second["slug"]) == ("kaese-brot", "kaese-brot-2")
    assert _pipeline(client, "???")["slug"] == "pipeline"
    as_action = client.post("/api/actions", json={"name": "Kaese brot"}).json()
    assert as_action["slug"] == "kaese-brot"  # another kind: its own names
    renamed = client.patch(_url(second), json={"name": "Final"}).json()
    assert renamed["slug"] == "final"
    again = client.patch(_url(first), json={"name": "Käse & Brot!"}).json()
    assert again["slug"] == "kaese-brot"  # renaming to the same name keeps its own slug
    collided = client.patch(_url(second), json={"name": "Käse & Brot!"}).json()
    assert collided["slug"] == "kaese-brot-2"  # the suffix applies on a rename too
    freed = client.patch(_url(first), json={"name": "Else"}).json()
    assert freed["slug"] == "else"
    taken = client.patch(_url(second), json={"name": "Käse & Brot!"}).json()
    assert taken["slug"] == "kaese-brot"  # the first one left: the plain slug is free again


# ── the timer node of an action definition ────────────────────────────


def test_a_timer_has_seconds_and_sits_between_trigger_and_output(client: TestClient) -> None:
    definition = _action_definition(client)
    nodes = {n["kind"]: n for n in _graph(client, definition)["nodes"]}
    timer = _node(client, definition, "timer")
    assert (timer["name"], timer["seconds"]) == ("Timer", 5)
    assert _node(client, definition, "timer", seconds=30)["seconds"] == 30
    url = f"{_url(definition)}/nodes/{timer['id']}"
    assert client.patch(url, json={"seconds": 12}).json()["seconds"] == 12
    assert client.patch(url, json={"seconds": 0}).status_code == 422
    assert client.patch(url, json={"seconds": 86401}).status_code == 422
    assert _edge(client, definition, nodes["trigger"], "out", timer, "in").status_code == 201
    assert _edge(client, definition, timer, "out", nodes["output"], "pass").status_code == 201
    assert _edge(client, definition, timer, "out", timer, "in").status_code == 422  # not to itself
    trigger_url = f"{_url(definition)}/nodes/{nodes['trigger']['id']}"
    assert client.patch(trigger_url, json={"seconds": 3}).status_code == 422
    assert client.delete(url).status_code == 204


def test_a_pipeline_has_no_timer(client: TestClient) -> None:
    pipeline = _pipeline(client)
    response = client.post(f"{_url(pipeline)}/nodes", json={"kind": "timer"})
    assert response.status_code == 422


def test_a_graph_requested_under_the_wrong_kind_is_404(client: TestClient) -> None:
    pipeline = _pipeline(client)
    definition = _action_definition(client)
    assert client.get(f"/api/actions/{pipeline['id']}").status_code == 404
    assert client.get(f"/api/pipelines/{definition['id']}").status_code == 404
    assert client.delete(f"/api/actions/{pipeline['id']}").status_code == 404
    assert (
        client.post(f"/api/pipelines/{definition['id']}/nodes", json={"kind": "stage"}).status_code
        == 404
    )
    assert client.get(f"/api/actions/{definition['id']}/stages").status_code == 404
    assert client.get(_url(pipeline)).status_code == 200


def test_node_types_are_served_under_their_own_path(client: TestClient) -> None:
    types = client.get("/api/node-types").json()
    assert types
    assert all(set(t["scopes"]) <= {"pipeline", "action"} for t in types)
    by_kind = {t["kind"]: t for t in types}
    assert set(by_kind) == {
        "trigger",
        "stage",
        "action",
        "pipeline",
        "complete",
        "timer",
        "output",
        "code",
        "http",
        "if",
        "switch",
        "agent",
        "set",
        "mcp_tool",
        "github_tool",
        "openartifact_tool",
        "http_tool",
        "code_tool",
        "github",
        "postgres",
        "postgres_tool",
        "sqlite",
        "sqlite_tool",
        "handover_tool",
        "artifact",
        "context",
    }
    timer = by_kind["timer"]
    assert (timer["scopes"], timer["addable"], timer["fixed"]) == (["action"], True, False)
    assert timer["settings"] == [
        {
            "key": "seconds",
            "label": "Seconds",
            "type": "integer",
            "minimum": 1,
            "maximum": 86400,
            "default": 5,
            "stored_in": "column",
            "section": "definition",  # the metadata of ADR-053, with its defaults
            "level": "core",
            "inherits": None,
        }
    ]
    stage = by_kind["stage"]
    assert stage["scopes"] == ["pipeline"] and stage["addable"] is True
    assert [p["name"] for p in stage["inputs"]] == ["start", "end"]
    assert [p["name"] for p in stage["outputs"]] == ["start", "end"]
    output = by_kind["output"]
    assert (output["addable"], output["fixed"], output["ending"]) == (False, True, True)
    assert [p["name"] for p in output["inputs"]] == ["pass", "fail"]


# ── Migration 0020: workflows become graphs ───────────────────────────
