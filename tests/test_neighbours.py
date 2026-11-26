"""Neighbours of a graph and the position of an execution (ADR-069 addendum 2): read only, and the same story as the editor and the flow.

The tests hold the API against what the pages draw from: the graph the editor reads (``GET /api/pipelines/{id}``, ``GET /api/actions/{id}``,
the labels of ``GET /api/node-types``) and the flow the flow view reads (``GET .../executions/{id}/flow``). A connection the editor
draws must be a successor and a predecessor, a node the flow view marks as the one the run waits in must be where the position says.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import (
    build_definition,
    build_pipeline,
    connect,
    graph_url,
    make_task,
    post,
    slow_pipeline,
    wait_for_run,
    wait_until,
)
from tests.test_execution_flow import _executions, _flow, _start
from tests.test_execution_nodes import _definition, _use

TOKEN = "neighbours-token-" + "x" * 24
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def secured(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def _editor(client: TestClient, graph: dict[str, Any]) -> dict[str, Any]:
    """What the graph editor reads and draws."""
    response = client.get(graph_url(graph))
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def _neighbours(client: TestClient, graph: dict[str, Any], **query: Any) -> dict[str, Any]:
    response = client.get(f"{graph_url(graph)}/neighbours", params=query)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def _editor_name(node: dict[str, Any]) -> str:
    """What the editor writes on a node (``nameOf`` of the page: a linked node carries the name of what it links to)."""
    return str(node.get("definition_name") or node["name"])


def _port_labels(client: TestClient) -> dict[tuple[str, str], str]:
    """The label the editor writes at every connector, by (kind, connector), from the node types it loads."""
    labels: dict[tuple[str, str], str] = {}
    for kind in client.get("/api/node-types").json():
        for port in (*kind["inputs"], *kind["outputs"]):
            labels[(kind["kind"], port["name"])] = port["label"]
    return labels


def _agree(client: TestClient, graph: dict[str, Any], neighbours: dict[str, Any]) -> None:
    """Every connection the editor draws is once a successor of its source and once a predecessor of its target, with the
    editor's names and connector labels, and the answer has nothing else."""
    editor = _editor(client, graph)
    nodes = {n["id"]: n for n in editor["nodes"]}
    labels = _port_labels(client)
    drawn = {
        (e["source_id"], e["source_port"], e["target_id"], e["target_port"])
        for e in editor["edges"]
    }
    assert drawn, "the fixture must have connections, or the comparison proves nothing"
    assert [n["id"] for n in neighbours["nodes"]] == [n["id"] for n in editor["nodes"]]
    successors: set[tuple[str, str, str, str]] = set()
    predecessors: set[tuple[str, str, str, str]] = set()
    for entry in neighbours["nodes"]:
        node = nodes[entry["id"]]
        assert entry["name"] == _editor_name(node) and entry["kind"] == node["kind"]
        assert entry["stage_id"] == node["stage_id"]
        for link in entry["successors"]:
            successors.add((entry["id"], link["port"], link["node_id"], link["target_port"]))
            assert link["name"] == _editor_name(nodes[link["node_id"]])
            assert link["port_label"] == labels.get((node["kind"], link["port"]), link["port"])
        for link in entry["predecessors"]:
            predecessors.add((link["node_id"], link["port"], entry["id"], link["target_port"]))
            source_kind = nodes[link["node_id"]]["kind"]
            assert link["port_label"] == labels.get((source_kind, link["port"]), link["port"])
    assert successors == drawn
    assert predecessors == drawn


def test_the_neighbours_of_a_pipeline_are_the_connections_the_editor_draws(
    client: TestClient,
) -> None:
    pipeline = build_pipeline(client, stages=2)
    definition = _definition(client, "code", language="sh", code="echo hi")
    _use(client, pipeline, definition)
    answer = _neighbours(client, pipeline, version="draft")
    _agree(client, pipeline, answer)
    (s1, a1), (s2, _) = pipeline["stages"]
    by_id = {n["id"]: n for n in answer["nodes"]}
    # the linked action carries the definition's name, its pass leaves into the end of its stage
    assert by_id[a1["id"]]["name"] == definition["name"]
    assert by_id[a1["id"]]["stage_name"] == s1["name"]
    assert [
        (link["port"], link["connection"], link["node_id"])
        for link in by_id[a1["id"]]["successors"]
    ] == [("pass", "pass", s1["id"])]
    assert [(link["port"], link["node_id"]) for link in by_id[s1["id"]]["successors"]] == [
        ("start", a1["id"]),
        ("end", s2["id"]),
    ]


def test_the_neighbours_of_an_action_definition_name_pass_and_fail(client: TestClient) -> None:
    definition = _definition(client, "code", language="sh", code="exit 1")
    answer = _neighbours(client, definition, version="draft")
    _agree(client, definition, answer)
    code = next(n for n in answer["nodes"] if n["id"] == definition["node"]["id"])
    assert [
        (link["port_label"], link["connection"], link["node_id"]) for link in code["successors"]
    ] == [
        ("On Pass", "pass", definition["output"]["id"]),
        ("On Fail", "failure", definition["output"]["id"]),
    ]
    output = next(n for n in answer["nodes"] if n["id"] == definition["output"]["id"])
    assert {link["node_id"] for link in output["predecessors"]} == {definition["node"]["id"]}
    assert output["successors"] == []


def test_a_node_with_a_condition_has_a_branch_per_port(client: TestClient) -> None:
    definition = build_definition(client, "Branching", output=None)
    nodes = {n["kind"]: n for n in _editor(client, definition)["nodes"]}
    branch = post(client, f"{graph_url(definition)}/nodes", kind="if")
    connect(client, definition, nodes["trigger"], "out", branch, "in")
    connect(client, definition, branch, "yes", nodes["output"], "pass")
    answer = _neighbours(client, definition, version="draft")
    _agree(client, definition, answer)
    entry = next(n for n in answer["nodes"] if n["id"] == branch["id"])
    assert [(link["port"], link["connection"]) for link in entry["successors"]] == [
        ("yes", "branch")
    ]


def test_the_published_version_is_the_default_and_the_draft_is_what_the_editor_shows(
    client: TestClient,
) -> None:
    definition = build_definition(client, "Versioned", seconds=5)
    before = _neighbours(client, definition)
    assert before["version"] == {
        "source": "draft",
        "number": None,
    }  # nothing published: the draft runs
    post(client, f"{graph_url(definition)}/publish")
    published = _neighbours(client, definition)
    assert published["version"] == {"source": "published", "number": 1}
    nodes = {n["kind"]: n for n in _editor(client, definition)["nodes"]}
    extra = post(client, f"{graph_url(definition)}/nodes", kind="timer", seconds=7)
    client.delete(f"{graph_url(definition)}/edges/{_editor(client, definition)['edges'][-1]['id']}")
    connect(client, definition, nodes["timer"], "out", extra, "in")
    draft = _neighbours(client, definition, version="draft")
    assert draft["version"] == {"source": "draft", "number": None}
    assert {n["id"] for n in draft["nodes"]} - {n["id"] for n in published["nodes"]} == {
        extra["id"]
    }
    assert (
        _neighbours(client, definition) == published
    )  # the draft change does not leak into what runs
    assert _neighbours(client, definition, version="1") == published
    _agree(client, definition, draft)


def test_unknown_version_kind_and_graph_are_refused(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1)
    definition = build_definition(client, "Other kind")
    assert client.get(f"{graph_url(pipeline)}/neighbours?version=9").status_code == 404
    assert client.get(f"{graph_url(pipeline)}/neighbours?version=latest").status_code == 422
    # a pipeline is not found under /api/actions, and the other way round
    assert client.get(f"/api/actions/{pipeline['id']}/neighbours").status_code == 404
    assert client.get(f"/api/pipelines/{definition['id']}/neighbours").status_code == 404
    assert client.get("/api/pipelines/nope/neighbours").status_code == 404


# ── the position of an execution ──────────────────────────────────────


def _position(
    client: TestClient, task: dict[str, Any], execution: dict[str, Any]
) -> dict[str, Any]:
    response = client.get(f"/api/tasks/{task['id']}/executions/{execution['id']}/position")
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_a_running_execution_is_where_the_flow_view_says_it_waits(client: TestClient) -> None:
    pipeline = slow_pipeline(client, seconds=30)
    task = make_task(client)
    _start(client, pipeline, task)
    wait_for_run(client, task, "running")
    flow = wait_until(lambda: _flow(client, task), lambda f: len(f["steps"]) >= 1)
    execution = _executions(client, task)[0]
    position = _position(client, task, execution)

    # the view marks the tail of the running visit as the node it waits in (ExecutionFlow doc): the position names the same node
    root, action = flow["visits"]
    definition = flow["graphs"][action["graph_id"]]
    timer = next(n for n in definition["nodes"] if n["kind"] == "timer")
    assert action["nodes"][-1] == timer["id"]
    assert position["execution"]["status"] == "running"
    assert [(w["graph_id"], w["node"]["id"]) for w in position["at"]] == [
        (flow["root_graph_id"], action["entered_via"]["node_id"]),
        (definition["id"], timer["id"]),
    ]
    assert position["at"][-1]["node"]["kind"] == "timer"

    # what leaves that node is what the frozen graph draws at it, with the editor's labels
    leaving = [
        (e["source_port"], e["target_id"])
        for e in definition["edges"]
        if e["source_id"] == timer["id"]
    ]
    assert leaving, "the timer must lead somewhere, or the comparison proves nothing"
    assert [(link["port"], link["node_id"]) for link in position["next"]] == leaving
    # and what the action's own node leaves into, one level out
    shell = action["entered_via"]["node_id"]
    outer = [
        (e["source_port"], e["target_id"])
        for e in flow["graphs"][flow["root_graph_id"]]["edges"]
        if e["source_id"] == shell
    ]
    assert [(link["port"], link["node_id"]) for link in position["afterwards"][0]] == outer

    # the path has the same visits as the flow, the running tail is marked running
    assert [(v["index"], v["graph_id"], v["outcome"]) for v in position["path"]] == [
        (v["index"], v["graph_id"], v["outcome"]) for v in flow["visits"]
    ]
    assert position["path"][1]["nodes"][-1] == {
        **position["path"][1]["nodes"][-1],
        "id": timer["id"],
        "state": "running",
    }
    assert root["outcome"] == "running"

    post(client, f"/api/tasks/{task['id']}/run/stop")
    stopped = _position(client, task, execution)
    assert stopped["execution"]["status"] == "stopped"
    assert stopped["at"][-1]["node"]["kind"] != "timer"  # the timer was never recorded as reached
    # as the flow view draws it (FlowModel.describe): inside the action the last node reached has its step ("pass"), the stop shows
    # on the action node of the pipeline, whose last visit was stopped
    shell = stopped["path"][1]["entered_via"]["id"]
    states = {n["id"]: n["state"] for n in stopped["path"][0]["nodes"]}
    assert states[shell] == "stopped"
    assert stopped["path"][1]["nodes"][-1]["state"] == "pass"


def test_a_finished_execution_ends_where_the_flow_ends(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=2)
    definition = _definition(client, "code", language="sh", code="echo hi")
    _use(client, pipeline, definition)
    task = make_task(client)
    _start(client, pipeline, task)
    wait_for_run(client, task, "done")
    flow = _flow(client, task)
    position = _position(client, task, _executions(client, task)[0])
    assert position["execution"]["status"] == "done"
    last = flow["visits"][-1]
    assert position["at"][-1]["node"]["id"] == last["nodes"][-1]
    assert position["next"] == []  # the end leads nowhere
    steps = [s for v in position["path"] for s in v["steps"]]
    assert [s["node_id"] for s in steps] == [s["node_id"] for s in flow["steps"] if s["node_id"]][
        : len(steps)
    ]
    assert all("output" not in s for s in steps), "outputs stay in get_execution_step"
    assert {n["state"] for v in position["path"] for n in v["nodes"]} == {"pass"}


def test_a_failed_execution_names_the_failing_node_and_where_a_fail_would_go(
    client: TestClient,
) -> None:
    pipeline = build_pipeline(client, stages=1)
    definition = _definition(client, "code", language="sh", code="exit 3")
    _use(client, pipeline, definition)
    task = make_task(client)
    _start(client, pipeline, task)
    wait_for_run(client, task, "failed")
    position = _position(client, task, _executions(client, task)[0])
    assert position["execution"]["status"] == "failed"
    assert position["at"][-1]["node"]["id"] == definition["output"]["id"]
    failed = [s for v in position["path"] for s in v["steps"] if s["outcome"] == "fail"]
    # the steps the flow records as failed (the Code node, then the Output it reached by On Fail), in the same order
    recorded = [s["node_id"] for s in _flow(client, task)["steps"] if s["outcome"] == "fail"]
    assert [s["node_id"] for s in failed] == recorded
    assert recorded[0] == definition["node"]["id"]
    assert failed[0]["port"] == "fail" and failed[0]["reason"]


def test_the_position_is_refused_for_an_unknown_execution(client: TestClient) -> None:
    task = make_task(client)
    refused = client.get(f"/api/tasks/{task['id']}/executions/nope/position")
    assert refused.status_code == 404


# ── the integration API and MCP ───────────────────────────────────────


def _mcp_tool(api: TestClient, name: str, **arguments: Any) -> dict[str, Any]:
    response = api.post(
        "/mcp",
        headers={**HEADERS, "Accept": "application/json, text/event-stream"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]  # type: ignore[no-any-return]


def test_the_integration_api_and_the_mcp_tools_give_the_same_answers_and_need_the_token(
    secured: TestClient,
) -> None:
    pipeline = build_pipeline(secured, stages=2)
    definition = _definition(secured, "code", language="sh", code="echo hi")
    _use(secured, pipeline, definition)
    task = make_task(secured)
    _start(secured, pipeline, task)
    wait_for_run(secured, task, "done")
    execution = _executions(secured, task)[0]
    ref = task["number"]

    rest = _neighbours(secured, pipeline, version="draft")
    v1 = secured.get(f"/api/v1/pipelines/{pipeline['name']}/neighbours?version=draft").json()
    assert v1 == rest
    via_mcp = json.loads(
        _mcp_tool(
            secured, "get_graph_neighbours", graph=pipeline["id"], kind="pipeline", version="draft"
        )["content"][0]["text"]
    )
    assert via_mcp == rest
    action_rest = _neighbours(secured, definition, version="draft")
    assert secured.get(f"/api/v1/actions/{definition['id']}/neighbours?version=draft").json() == (
        action_rest
    )
    assert (
        json.loads(
            _mcp_tool(
                secured,
                "get_graph_neighbours",
                graph=definition["name"],
                kind="action",
                version="draft",
            )["content"][0]["text"]
        )
        == action_rest
    )

    position = _position(secured, task, execution)
    assert (
        secured.get(f"/api/v1/artifacts/{ref}/executions/{execution['id']}/position").json()
        == position
    )
    told = json.loads(
        _mcp_tool(secured, "get_execution_position", artifact=str(ref), execution=execution["id"])[
            "content"
        ][0]["text"]
    )
    assert told == position

    for bad in (
        _mcp_tool(secured, "get_execution_position", artifact=str(ref), execution="nope"),
        _mcp_tool(secured, "get_graph_neighbours", graph="no such graph"),
        _mcp_tool(secured, "get_graph_neighbours", graph=pipeline["id"], version="latest"),
    ):
        assert bad["isError"]

    bare = TestClient(secured.app)
    for url in (
        f"/api/pipelines/{pipeline['id']}/neighbours",
        f"/api/v1/pipelines/{pipeline['id']}/neighbours",
        f"/api/v1/actions/{definition['id']}/neighbours",
        f"/api/tasks/{task['id']}/executions/{execution['id']}/position",
        f"/api/v1/artifacts/{ref}/executions/{execution['id']}/position",
    ):
        assert bare.get(url).status_code == 401, url
