"""The flow of an execution: frozen graphs, the path walked through them (visits), steps on demand."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.engine.flow import build_flow
from openartifact.engine.flow_schemas import ExecutionFlow
from openartifact.engine.schemas import ExecutionRead
from tests.helpers import (
    build_definition,
    build_pipeline,
    connect,
    graph_url,
    link,
    make_task,
    post,
    slow_pipeline,
    wait_for_run,
    wait_until,
)
from tests.test_engine import _call
from tests.test_execution_nodes import _definition, _use

TOKEN = "flow-token-" + "x" * 24
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def _start(client: TestClient, pipeline: dict[str, Any], task: dict[str, Any], **at: Any) -> None:
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"], **at)


def _executions(client: TestClient, task: dict[str, Any]) -> list[dict[str, Any]]:
    return client.get(f"/api/tasks/{task['id']}/executions").json()["items"]  # type: ignore[no-any-return]


def _flow(
    client: TestClient, task: dict[str, Any], execution: dict[str, Any] | None = None, **q: Any
) -> dict[str, Any]:
    execution = execution or _executions(client, task)[0]
    response = client.get(f"/api/tasks/{task['id']}/executions/{execution['id']}/flow", params=q)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def _edge_keys(visit: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    return [
        (e["source_id"], e["source_port"], e["target_id"], e["target_port"]) for e in visit["edges"]
    ]


def _code(client: TestClient, code: str, **config: Any) -> dict[str, Any]:
    return _definition(client, "code", language="sh", code=code, **config)


def _two_stage_pipeline(
    client: TestClient, code: str = "echo hi"
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Two stages: the first action runs a code definition, the second is an empty action."""
    pipeline = build_pipeline(client, stages=2)
    definition = _code(client, code)
    _use(client, pipeline, definition)
    return pipeline, definition


def test_a_pipeline_with_two_stages_and_a_code_node(client: TestClient) -> None:
    pipeline, definition = _two_stage_pipeline(client)
    (s1, a1), (s2, a2) = pipeline["stages"]
    task = make_task(client)
    _start(client, pipeline, task)
    wait_for_run(client, task, "done")
    flow = _flow(client, task)

    assert flow["execution"]["status"] == "done" and flow["execution"]["number"] == 1
    assert flow["root_graph_id"] == pipeline["id"]
    assert set(flow["graphs"]) == {pipeline["id"], definition["id"]}
    root, action = flow["graphs"][pipeline["id"]], flow["graphs"][definition["id"]]
    assert (root["kind"], action["kind"], action["name"]) == (
        "pipeline",
        "action",
        definition["name"],
    )
    kinds = {n["id"]: n["kind"] for n in root["nodes"]}
    complete = next(i for i, k in kinds.items() if k == "complete")
    trigger = next(i for i, k in kinds.items() if k == "trigger")
    # the editor's shape: sizes for stages, edge ids, definition names
    stage = next(n for n in root["nodes"] if n["id"] == s1["id"])
    assert (stage["width"], stage["height"]) == (360.0, 240.0)
    node = next(n for n in root["nodes"] if n["id"] == a1["id"])
    assert node["definition_name"] == definition["name"] and node["definition_fail_enabled"] is True
    assert all(e["id"] for e in root["edges"] + action["edges"])
    code_node = next(n for n in action["nodes"] if n["kind"] == "code")
    assert code_node["config"]["code"] == "echo hi"

    root_visit, action_visit = flow["visits"]
    assert (root_visit["graph_id"], root_visit["level"], root_visit["entered_via"]) == (
        pipeline["id"],
        0,
        None,
    )
    assert root_visit["nodes"] == [trigger, s1["id"], a1["id"], s2["id"], a2["id"], complete]
    assert root_visit["outcome"] == "pass" and root_visit["skipped_nodes"] == []
    assert _edge_keys(root_visit) == [
        (trigger, "out", s1["id"], "start"),
        (s1["id"], "start", a1["id"], "in"),
        (a1["id"], "pass", s1["id"], "end"),
        (s1["id"], "end", s2["id"], "start"),
        (s2["id"], "start", a2["id"], "in"),
        (a2["id"], "pass", s2["id"], "end"),
        (s2["id"], "end", complete, "in"),
    ]
    assert root_visit["started_at"].endswith("Z") and root_visit["finished_at"].endswith("Z")
    assert (root_visit["first_seq"], root_visit["last_seq"]) == (1, 3)

    assert action_visit["graph_id"] == definition["id"] and action_visit["level"] == 1
    assert action_visit["entered_via"] == {"graph_id": pipeline["id"], "node_id": a1["id"]}
    assert action_visit["parent"] == 0 and action_visit["index"] == 1
    assert action_visit["nodes"] == [
        next(n["id"] for n in action["nodes"] if n["kind"] == "trigger"),
        code_node["id"],
        definition["output"]["id"],
    ]
    assert (action_visit["outcome"], action_visit["left_port"]) == ("pass", "pass")
    assert [e["target_id"] for e in action_visit["edges"]] == action_visit["nodes"][1:]
    assert [s["kind"] for s in flow["steps"]] == ["trigger", "code", "output"]

    reached = flow["reached"]
    assert reached[pipeline["id"]]["nodes"] == root_visit["nodes"]
    assert len(reached[pipeline["id"]]["edges"]) == 7
    assert reached[definition["id"]]["edges"] == [e["id"] for e in action_visit["edges"]]
    # the not-run part is what the graph has beyond `reached`: here the failing branch of the output
    assert len(reached[definition["id"]]["edges"]) < len(action["edges"])


def test_a_failing_action_leaves_by_its_error_port(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1)
    stage, action = pipeline["stages"][0]
    definition = _code(client, "exit 3")
    _use(client, pipeline, definition)
    connect(client, pipeline, action, "error", stage, "end")
    task = make_task(client)
    _start(client, pipeline, task)
    wait_for_run(client, task, "done")
    flow = _flow(client, task)
    root, action_visit = flow["visits"]
    assert (action_visit["outcome"], action_visit["left_port"]) == ("fail", "error")
    assert (action["id"], "error", stage["id"], "end") in _edge_keys(root)
    assert not any(e[:2] == (action["id"], "pass") for e in _edge_keys(root))
    assert root["outcome"] == "pass"
    assert [(s["kind"], s["outcome"]) for s in flow["steps"]][-1] == ("output", "fail")


def test_a_failed_execution_ends_failed_at_the_action(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=2)
    _use(client, pipeline, _code(client, "exit 1"))
    task = make_task(client)
    _start(client, pipeline, task)
    wait_for_run(client, task, "failed")
    flow = _flow(client, task)
    root, action_visit = flow["visits"]
    assert root["outcome"] == "fail" and action_visit["outcome"] == "fail"
    (_s1, a1), (s2, _) = pipeline["stages"]
    assert s2["id"] not in root["nodes"] and a1["id"] in root["nodes"]


def test_a_pipeline_that_calls_a_pipeline_has_a_nested_visit(client: TestClient) -> None:
    outer, inner = build_pipeline(client, stages=1), build_pipeline(client, stages=1, name="Inner")
    definition = _code(client, "echo in")
    _use(client, inner, definition)
    block = _call(client, outer, inner)
    task = make_task(client)
    _start(client, outer, task)
    wait_for_run(client, task, "done")
    flow = _flow(client, task)
    assert set(flow["graphs"]) == {outer["id"], inner["id"], definition["id"]}
    assert flow["graphs"][inner["id"]]["name"] == "Inner"
    assert [(v["graph_id"], v["level"], v["parent"]) for v in flow["visits"]] == [
        (outer["id"], 0, None),
        (inner["id"], 1, 0),
        (definition["id"], 2, 1),
    ]
    nested = flow["visits"][1]
    assert nested["entered_via"] == {"graph_id": outer["id"], "node_id": block["id"]}
    assert nested["outcome"] == "pass" and block["id"] in flow["visits"][0]["nodes"]
    assert flow["visits"][2]["entered_via"] == {
        "graph_id": inner["id"],
        "node_id": inner["stages"][0][1]["id"],
    }
    assert flow["visits"][0]["outcome"] == "pass"
    assert nested["first_seq"] == 1 and nested["last_seq"] == 3  # spans the steps below it
    # steps know where they ran
    assert {(s["depth"], s["pipeline_id"]) for s in flow["steps"]} == {(1, inner["id"])}


def test_an_action_that_runs_twice_has_two_visits(client: TestClient) -> None:
    """On Fail loops back to the same action's definition: one visit per run through it."""
    pipeline = build_pipeline(client, stages=1)
    stage, first = pipeline["stages"][0]
    second = post(
        client, f"{graph_url(pipeline)}/nodes", kind="action", stage_id=stage["id"], x=240, y=48
    )
    definition = _code(client, "exit 1")
    link(client, pipeline, first, definition)
    link(client, pipeline, second, build_definition(client, "Ok"))
    connect(client, pipeline, first, "error", second, "in")
    connect(client, pipeline, second, "pass", stage, "end")
    task = make_task(client)
    _start(client, pipeline, task)
    wait_for_run(client, task, "done")
    flow = _flow(client, task)
    assert [(v["graph_id"], v["outcome"]) for v in flow["visits"]] == [
        (pipeline["id"], "pass"),
        (definition["id"], "fail"),
        (flow["visits"][2]["graph_id"], "pass"),
    ]
    assert flow["visits"][0]["nodes"].count(first["id"]) == 1
    assert flow["visits"][2]["entered_via"]["node_id"] == second["id"]


def test_a_start_at_a_later_stage_lists_the_skipped_ones(client: TestClient) -> None:
    pipeline, _ = _two_stage_pipeline(client)
    (s1, a1), (s2, a2) = pipeline["stages"]
    task = make_task(client)
    _start(client, pipeline, task, stage_id=s2["id"])
    wait_for_run(client, task, "done")
    flow = _flow(client, task)
    root = flow["visits"][0]
    assert root["skipped_nodes"] == [s1["id"], a1["id"]]
    assert [n for n in root["nodes"] if n in (s1["id"], a1["id"])] == []
    assert root["nodes"][0] == s2["id"] and a2["id"] in root["nodes"]
    assert len(flow["visits"]) == 1  # the code action of stage 1 did not run
    assert s1["id"] not in flow["reached"][pipeline["id"]]["nodes"]


def test_a_restart_gives_a_separate_execution_with_its_own_flow(client: TestClient) -> None:
    pipeline, _ = _two_stage_pipeline(client)
    s2 = pipeline["stages"][1][0]
    task = make_task(client)
    _start(client, pipeline, task)
    wait_for_run(client, task, "done")
    _start(client, pipeline, task, stage_id=s2["id"])
    wait_until(
        lambda: _executions(client, task),
        lambda items: len(items) == 2 and items[0]["status"] == "done",
    )
    newest, oldest = _executions(client, task)
    assert len(_flow(client, task, oldest)["visits"]) == 2
    assert len(_flow(client, task, newest)["visits"]) == 1
    assert _flow(client, task, newest)["execution"]["id"] == newest["id"]


def test_the_flow_is_frozen_while_the_live_pipeline_changes(client: TestClient) -> None:
    pipeline, definition = _two_stage_pipeline(client)
    task = make_task(client)
    _start(client, pipeline, task)
    wait_for_run(client, task, "done")
    before = _flow(client, task)
    (s1, _a1), (s2, _) = pipeline["stages"]
    client.patch(f"{graph_url(pipeline)}/nodes/{s1['id']}", json={"name": "Renamed", "x": 999})
    client.patch(f"{graph_url(definition)}", json={"name": "Renamed definition"})
    client.delete(f"{graph_url(pipeline)}/nodes/{s2['id']}")
    client.delete(f"{graph_url(definition)}/nodes/{definition['node']['id']}")
    assert _flow(client, task) == before
    # even the whole pipeline may go: the execution keeps it
    assert client.delete(graph_url(pipeline)).status_code in (204, 409)
    assert _flow(client, task) == before


def test_an_old_snapshot_is_filled_in() -> None:
    """A snapshot from before ids, names, sizes and edge ids were stored still gives a drawable flow."""
    snapshot = {
        "name": "Old flow",
        "nodes": [
            {
                "id": "t",
                "label": "Trigger",
                "kind": "trigger",
                "stage_id": None,
                "name": "Trigger",
                "definition_id": None,
                "seconds": None,
                "x": 0,
                "y": 0,
            },
            {
                "id": "s1",
                "label": "Build",
                "kind": "stage",
                "stage_id": None,
                "name": "Build",
                "definition_id": None,
                "seconds": None,
                "x": 10,
                "y": 0,
            },
            {
                "id": "a1",
                "label": "Compile",
                "kind": "action",
                "stage_id": "s1",
                "name": "Action",
                "definition_id": "d1",
                "seconds": None,
                "x": 5,
                "y": 5,
            },
            {
                "id": "c",
                "label": "Complete",
                "kind": "complete",
                "stage_id": None,
                "name": "Complete",
                "definition_id": None,
                "seconds": None,
                "x": 0,
                "y": 0,
            },
        ],
        "edges": [
            {"source_id": "t", "source_port": "out", "target_id": "s1", "target_port": "start"},
            {"source_id": "s1", "source_port": "start", "target_id": "a1", "target_port": "in"},
            {"source_id": "a1", "source_port": "pass", "target_id": "s1", "target_port": "end"},
            {"source_id": "s1", "source_port": "end", "target_id": "c", "target_port": "in"},
        ],
        "pipelines": {},
        "definitions": {
            "d1": {
                "nodes": [
                    {
                        "id": "dt",
                        "label": "Trigger",
                        "kind": "trigger",
                        "stage_id": None,
                        "name": "Trigger",
                        "definition_id": None,
                        "seconds": None,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "id": "do",
                        "label": "Output",
                        "kind": "output",
                        "stage_id": None,
                        "name": "Output",
                        "definition_id": None,
                        "seconds": None,
                        "x": 0,
                        "y": 0,
                    },
                ],
                "edges": [
                    {
                        "source_id": "dt",
                        "source_port": "out",
                        "target_id": "do",
                        "target_port": "pass",
                    }
                ],
            }
        },
    }
    execution = ExecutionRead.model_validate(
        {
            "id": "e",
            "task_id": "t",
            "number": 1,
            "status": "done",
            "note": None,
            "pipeline_id": "p1",
            "pipeline_name": "Old flow",
            "started_stage_id": None,
            "started_stage_name": None,
            "started_action_id": None,
            "started_action_name": None,
            "final_stage_name": None,
            "final_action_name": None,
            "started_by": "user",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "duration_seconds": 1.0,
            "step_count": 2,
        }
    )
    step = {
        "id": "x", "seq": 1, "pipeline_id": "p1", "depth": 0, "top_stage_id": "s1", "definition_id": "d1",
        "port": "out", "node_id": "dt", "node_name": "Trigger", "stage_id": "s1", "action_id": "a1",
        "kind": "trigger", "outcome": "pass", "exit_code": None, "output": "", "output_truncated": False,
        "reason": None, "data": None, "started_at": "2026-01-01T00:00:00Z", "finished_at": "2026-01-01T00:00:00Z",
    }  # fmt: skip
    from openartifact.engine.schemas import ExecutionStepRead

    steps = [
        ExecutionStepRead.model_validate(step),
        ExecutionStepRead.model_validate(
            {**step, "id": "y", "seq": 2, "node_id": "do", "kind": "output", "port": None}
        ),
    ]
    flow: ExecutionFlow = build_flow(execution, json.dumps(snapshot), steps, False, (None, None))
    assert flow.root_graph_id == "p1"
    assert (
        flow.graphs["d1"].name == "Compile"
    )  # no name stored: the label of the node that calls it
    assert flow.graphs["p1"].name == "Old flow"
    stage = next(n for n in flow.graphs["p1"].nodes if n.id == "s1")
    assert (stage.width, stage.height) == (360.0, 240.0)
    assert flow.graphs["p1"].edges[0].id == "t:out>s1:start"
    assert [v.outcome for v in flow.visits] == ["pass", "pass"]
    assert flow.visits[0].nodes == ["t", "s1", "a1", "c"]
    assert flow.visits[1].nodes == ["dt", "do"]
    assert flow.reached["d1"].edges == ["dt:out>do:pass"]
    assert flow.steps[0].output_length == 0 and not flow.steps[0].output_included


def test_a_snapshot_that_is_hardly_there_does_not_break_the_flow() -> None:
    """Backfilled executions have snapshots with nodes of an id, label and kind only."""
    execution = ExecutionRead.model_validate(
        {
            "id": "e", "task_id": "t", "number": 1, "status": "stopped", "note": None,
            "pipeline_id": None, "pipeline_name": "Old", "started_stage_id": None,
            "started_stage_name": None, "started_action_id": None, "started_action_name": None,
            "final_stage_name": None, "final_action_name": None, "started_by": "system",
            "started_at": "2026-01-01T00:00:00Z", "finished_at": None, "duration_seconds": None,
            "step_count": 0,
        }
    )  # fmt: skip
    snapshot = {
        "name": "Old",
        "nodes": [{"id": "s1", "label": "Build", "kind": "stage"}],
        "edges": [],
    }
    flow = build_flow(execution, json.dumps(snapshot), [], False, (None, None))
    assert flow.root_graph_id == "root" and flow.visits[0].outcome is None
    assert build_flow(execution, "not json", [], False, (None, None)).visits[0].nodes == []


def test_a_running_execution_shows_where_it_waits(client: TestClient) -> None:
    pipeline = slow_pipeline(client, seconds=30)
    task = make_task(client)
    _start(client, pipeline, task)
    wait_for_run(client, task, "running")
    flow = wait_until(lambda: _flow(client, task), lambda f: len(f["steps"]) >= 1)
    root, action = flow["visits"]
    assert flow["execution"]["finished_at"] is None
    assert (root["outcome"], action["outcome"]) == ("running", "running")
    definition = flow["graphs"][action["graph_id"]]
    timer = next(n for n in definition["nodes"] if n["kind"] == "timer")
    assert action["nodes"][-1] == timer["id"]  # not recorded yet: it is the node it waits in
    assert action["left_port"] is None
    post(client, f"/api/tasks/{task['id']}/run/stop")
    stopped = _flow(client, task)
    assert stopped["execution"]["status"] == "stopped"
    assert [v["outcome"] for v in stopped["visits"]] == [None, None]
    assert stopped["visits"][1]["nodes"] == action["nodes"][:-1]


def test_scoping_and_errors(client: TestClient) -> None:
    pipeline, _ = _two_stage_pipeline(client)
    task, other = make_task(client), make_task(client, "Other")
    _start(client, pipeline, task)
    wait_for_run(client, task, "done")
    execution = _executions(client, task)[0]
    base = f"/api/tasks/{task['id']}/executions"
    assert client.get(f"{base}/{execution['id']}/flow").status_code == 200
    by_number = client.get(f"/api/tasks/{task['number']}/executions/{execution['id']}/flow")
    assert by_number.status_code == 200
    assert client.get(f"{base}/nope/flow").status_code == 404
    assert client.get(f"/api/tasks/nope/executions/{execution['id']}/flow").status_code == 404
    assert (
        client.get(f"/api/tasks/{other['id']}/executions/{execution['id']}/flow").status_code == 404
    )
    assert client.get(f"{base}/{execution['id']}/flow?outputs=maybe").status_code == 422
    step = _flow(client, task)["steps"][0]
    assert client.get(f"{base}/{execution['id']}/steps/nope").status_code == 404
    assert (
        client.get(
            f"/api/tasks/{other['id']}/executions/{execution['id']}/steps/{step['id']}"
        ).status_code
        == 404
    )


def test_outputs_are_left_out_unless_asked_for_and_a_step_has_its_own_endpoint(
    client: TestClient,
) -> None:
    pipeline, _ = _two_stage_pipeline(client, code="echo hello-world")
    task = make_task(client)
    _start(client, pipeline, task)
    wait_for_run(client, task, "done")
    execution = _executions(client, task)[0]
    lean = _flow(client, task)
    code = next(s for s in lean["steps"] if s["kind"] == "code")
    assert code["output"] == "" and code["output_included"] is False
    assert code["output_length"] == len("hello-world\n")
    full = _flow(client, task, outputs=True)
    full_code = next(s for s in full["steps"] if s["id"] == code["id"])
    assert full_code["output"] == "hello-world\n" and full_code["output_included"] is True
    one = client.get(f"/api/tasks/{task['id']}/executions/{execution['id']}/steps/{code['id']}")
    assert one.status_code == 200 and one.json()["output"] == "hello-world\n"
    assert one.json()["stage_name"] == "Stage 1"
    # the detail endpoint keeps the full outputs
    detail = client.get(f"/api/tasks/{task['id']}/executions/{execution['id']}").json()
    assert next(s for s in detail["steps"] if s["id"] == code["id"])["output"] == "hello-world\n"


def test_the_openapi_describes_the_flow(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    for path in (
        "/api/tasks/{task_id}/executions/{execution_id}/flow",
        "/api/tasks/{task_id}/executions/{execution_id}/steps/{step_id}",
        "/api/v1/artifacts/{ref}/executions/{execution_id}/flow",
    ):
        assert path in schema["paths"]
    flow = schema["components"]["schemas"]["ExecutionFlow"]["properties"]
    assert {"execution", "root_graph_id", "graphs", "steps", "visits", "reached"} <= set(flow)
    visit = schema["components"]["schemas"]["FlowVisit"]["properties"]
    assert {
        "graph_id",
        "level",
        "nodes",
        "edges",
        "outcome",
        "entered_via",
        "skipped_nodes",
    } <= set(visit)


@pytest.fixture
def secured(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def test_the_integration_api_mirrors_the_flow_and_needs_the_token(secured: TestClient) -> None:
    pipeline, _ = _two_stage_pipeline(secured)
    task = make_task(secured)
    _start(secured, pipeline, task)
    wait_for_run(secured, task, "done")
    execution = _executions(secured, task)[0]
    ref = task["number"]
    flow = secured.get(f"/api/v1/artifacts/{ref}/executions/{execution['id']}/flow").json()
    assert flow == _flow(secured, task)
    step = flow["steps"][1]
    one = secured.get(f"/api/v1/artifacts/{ref}/executions/{execution['id']}/steps/{step['id']}")
    assert one.status_code == 200 and one.json()["id"] == step["id"]
    bare = TestClient(secured.app)
    assert bare.get(f"/api/v1/artifacts/{ref}/executions/{execution['id']}/flow").status_code == 401
    assert bare.get(f"/api/tasks/{task['id']}/executions/{execution['id']}/flow").status_code == 401


def test_a_secret_never_reaches_the_flow(secured: TestClient) -> None:
    value = "hunter2-Value-9137"
    assert secured.put("/api/secrets/PASSWORD", json={"value": value}).status_code == 201
    pipeline, task = build_pipeline(secured, stages=1), make_task(secured)
    definition = _definition(
        secured, "code", language="sh", secrets="PASSWORD", code='echo "the password is $PASSWORD"'
    )
    _use(secured, pipeline, definition)
    _start(secured, pipeline, task)
    wait_for_run(secured, task, "done")
    execution = _executions(secured, task)[0]
    for outputs in ("true", "false"):
        flow = secured.get(
            f"/api/tasks/{task['id']}/executions/{execution['id']}/flow?outputs={outputs}"
        )
        assert value not in flow.text
    assert (
        "***"
        in secured.get(
            f"/api/tasks/{task['id']}/executions/{execution['id']}/flow?outputs=true"
        ).text
    )
    step_id = _flow(secured, task)["steps"][1]["id"]
    one = secured.get(f"/api/tasks/{task['id']}/executions/{execution['id']}/steps/{step_id}")
    assert value not in one.text and "the password is" in one.text


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


def test_the_mcp_tool_returns_the_flow(secured: TestClient) -> None:
    pipeline, _ = _two_stage_pipeline(secured)
    task = make_task(secured)
    _start(secured, pipeline, task)
    wait_for_run(secured, task, "done")
    execution = _executions(secured, task)[0]
    result = _mcp_tool(
        secured, "get_execution_flow", artifact=task["id"], execution=execution["id"]
    )
    flow = json.loads(result["content"][0]["text"])
    assert flow["root_graph_id"] == pipeline["id"] and len(flow["visits"]) == 2
    assert _mcp_tool(secured, "get_execution_flow", artifact=task["id"], execution="nope")[
        "isError"
    ]


def test_new_snapshots_carry_ids_names_sizes_and_edge_ids(client: TestClient) -> None:
    pipeline, definition = _two_stage_pipeline(client)
    task = make_task(client)
    _start(client, pipeline, task)
    wait_for_run(client, task, "done")
    state = client.app.state  # type: ignore[attr-defined]
    path = state.settings.data_dir / state.settings.database_filename
    with sqlite3.connect(path) as conn:
        snapshot = json.loads(conn.execute("SELECT snapshot FROM executions").fetchone()[0])
    assert (snapshot["id"], snapshot["name"]) == (pipeline["id"], pipeline["name"])
    assert snapshot["definitions"][definition["id"]]["name"] == definition["name"]
    assert all(e["id"] for e in snapshot["edges"])
    stage = next(n for n in snapshot["nodes"] if n["kind"] == "stage")
    assert stage["width"] and stage["height"]
