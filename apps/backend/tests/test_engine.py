"""Pipeline runs: starting, skipping, locking, stopping and failing."""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient


def _post(client: TestClient, url: str, **body: Any) -> dict[str, Any]:
    response = client.post(url, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()  # type: ignore[no-any-return]


def _connect(
    client: TestClient,
    workflow: dict[str, Any],
    a: dict[str, Any],
    ap: str,
    b: dict[str, Any],
    bp: str,
) -> None:
    _post(
        client,
        f"/api/workflows/{workflow['id']}/edges",
        source_id=a["id"],
        source_port=ap,
        target_id=b["id"],
        target_port=bp,
    )


def _node(client: TestClient, workflow: dict[str, Any], kind: str, **extra: Any) -> dict[str, Any]:
    return _post(client, f"/api/workflows/{workflow['id']}/nodes", kind=kind, **extra)


def _pipeline(client: TestClient, stages: int = 2) -> dict[str, Any]:
    """Trigger → stage 1 → ... → complete, each stage with one empty action."""
    workflow = _post(client, "/api/workflows", name="Flow")
    nodes = client.get(f"/api/workflows/{workflow['id']}").json()["nodes"]
    trigger = next(n for n in nodes if n["kind"] == "trigger")
    complete = next(n for n in nodes if n["kind"] == "complete")
    previous, port = trigger, "out"
    made = []
    for i in range(stages):
        stage = _node(client, workflow, "stage", name=f"Stage {i + 1}")
        action = _node(client, workflow, "action", stage_id=stage["id"], x=24, y=48)
        _connect(client, workflow, previous, port, stage, "start")
        _connect(client, workflow, stage, "start", action, "in")
        _connect(client, workflow, action, "pass", stage, "end")
        previous, port = stage, "end"
        made.append((stage, action))
    _connect(client, workflow, previous, port, complete, "in")
    workflow["stages"] = made
    return workflow


def _task(client: TestClient) -> dict[str, Any]:
    return _post(client, "/api/tasks", title="Item", status="backlog")


def _run(client: TestClient, task: dict[str, Any]) -> dict[str, Any]:
    runs = [r for r in client.get("/api/runs").json() if r["task_id"] == task["id"]]
    return runs[0]  # type: ignore[no-any-return]


def _wait(client: TestClient, task: dict[str, Any], status: str) -> dict[str, Any]:
    for _ in range(100):
        run = _run(client, task)
        if run["status"] == status:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run is {_run(client, task)['status']}, not {status}")


def test_the_stages_come_in_the_order_of_the_pipeline(client: TestClient) -> None:
    workflow = _pipeline(client, stages=3)
    chain = client.get(f"/api/workflows/{workflow['id']}/stages").json()
    assert [s["name"] for s in chain] == ["Stage 1", "Stage 2", "Stage 3"]
    assert chain[0]["first_action_id"] == workflow["stages"][0][1]["id"]


def test_a_run_goes_through_every_stage_to_done(client: TestClient) -> None:
    workflow = _pipeline(client)
    task = _task(client)
    started = _post(client, f"/api/tasks/{task['id']}/run", workflow_id=workflow["id"])
    assert (started["started_by"], started["stage_name"]) == ("user", "Stage 1")
    run = _wait(client, task, "done")
    assert [s["status"] for s in run["stages"]] == ["passed", "passed"]


def test_starting_in_a_later_stage_skips_the_earlier_ones(client: TestClient) -> None:
    workflow = _pipeline(client)
    task = _task(client)
    second = workflow["stages"][1][0]
    _post(client, f"/api/tasks/{task['id']}/run", workflow_id=workflow["id"], stage_id=second["id"])
    run = _wait(client, task, "done")
    assert [s["status"] for s in run["stages"]] == ["skipped", "passed"]
    # going back: the first stage runs again, the second is pending until it is reached again
    _post(client, f"/api/tasks/{task['id']}/run", workflow_id=workflow["id"])
    run = _wait(client, task, "done")
    assert [s["status"] for s in run["stages"]] == ["passed", "passed"]


def test_a_start_must_name_a_stage_and_action_of_the_pipeline(client: TestClient) -> None:
    workflow = _pipeline(client)
    other = _pipeline(client)
    task = _task(client)
    url = f"/api/tasks/{task['id']}/run"
    stranger = other["stages"][0][0]["id"]
    assert (
        client.post(url, json={"workflow_id": workflow["id"], "stage_id": stranger}).status_code
        == 422
    )
    wrong_action = other["stages"][0][1]["id"]
    body = {
        "workflow_id": workflow["id"],
        "stage_id": workflow["stages"][0][0]["id"],
        "action_id": wrong_action,
    }
    assert client.post(url, json=body).status_code == 422
    assert client.post(url, json={"workflow_id": "nope"}).status_code == 422
    assert (
        client.post("/api/tasks/nope/run", json={"workflow_id": workflow["id"]}).status_code == 404
    )


def _slow_pipeline(client: TestClient) -> dict[str, Any]:
    """A pipeline whose only action waits 30 seconds (a timer in its definition)."""
    workflow = _pipeline(client, stages=1)
    definition = _post(client, "/api/workflows", name="Wait", kind="action")
    nodes = client.get(f"/api/workflows/{definition['id']}").json()["nodes"]
    trigger = next(n for n in nodes if n["kind"] == "trigger")
    output = next(n for n in nodes if n["kind"] == "output")
    timer = _node(client, definition, "timer", seconds=30)
    _connect(client, definition, trigger, "out", timer, "in")
    _connect(client, definition, timer, "out", output, "pass")
    action = workflow["stages"][0][1]
    response = client.patch(
        f"/api/workflows/{workflow['id']}/nodes/{action['id']}",
        json={"definition_id": definition["id"]},
    )
    assert response.status_code == 200
    return workflow


def test_a_running_artifact_is_locked_until_it_is_stopped(client: TestClient) -> None:
    workflow = _slow_pipeline(client)
    task = _task(client)
    url = f"/api/tasks/{task['id']}"
    _post(client, f"{url}/run", workflow_id=workflow["id"])
    assert client.post(f"{url}/run", json={"workflow_id": workflow["id"]}).status_code == 409
    assert client.patch(url, json={"status": "done"}).status_code == 409
    assert client.patch(url, json={"parent_id": None}).status_code == 409
    assert client.delete(url).status_code == 409
    assert client.patch(url, json={"title": "Renamed"}).status_code == 200  # content stays editable

    stopped = _post(client, f"{url}/run/stop")
    assert (stopped["status"], stopped["note"]) == ("stopped", "stopped")
    assert stopped["stage_name"] == "Stage 1"  # it stays where it was
    assert client.post(f"{url}/run/stop").status_code == 409
    assert client.patch(url, json={"status": "done"}).status_code == 200
    assert client.delete(url).status_code == 204


def test_an_action_without_a_way_to_its_output_fails_the_run(client: TestClient) -> None:
    workflow = _pipeline(client, stages=1)
    definition = _post(client, "/api/workflows", name="Broken", kind="action")
    graph = client.get(f"/api/workflows/{definition['id']}").json()
    client.delete(
        f"/api/workflows/{definition['id']}/edges/{graph['edges'][0]['id']}"
    )  # cut trigger → output
    action = workflow["stages"][0][1]
    client.patch(
        f"/api/workflows/{workflow['id']}/nodes/{action['id']}",
        json={"definition_id": definition["id"]},
    )
    task = _task(client)
    _post(client, f"/api/tasks/{task['id']}/run", workflow_id=workflow["id"])
    run = _wait(client, task, "failed")
    assert "Broken" in run["note"]
    assert run["stages"][0]["status"] == "failed"


def test_runs_are_published_as_events_and_removed_with_their_artifact(client: TestClient) -> None:
    workflow = _pipeline(client, stages=1)
    task = _task(client)
    _post(client, f"/api/tasks/{task['id']}/run", workflow_id=workflow["id"])
    _wait(client, task, "done")
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert client.get("/api/runs").json() == []


# ── pipeline nodes: a pipeline that calls another pipeline ────────────


def _call(client: TestClient, caller: dict[str, Any], called: dict[str, Any]) -> dict[str, Any]:
    """A pipeline node in ``caller`` (between its last stage and complete) that calls ``called``."""
    graph = client.get(f"/api/workflows/{caller['id']}").json()
    complete = next(n for n in graph["nodes"] if n["kind"] == "complete")
    last_stage = caller["stages"][-1][0]
    block = _node(client, caller, "pipeline")
    _connect(client, caller, last_stage, "end", block, "in")
    _connect(client, caller, block, "out", complete, "in")
    response = client.patch(
        f"/api/workflows/{caller['id']}/nodes/{block['id']}", json={"definition_id": called["id"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["definition_name"] == called["name"]
    return block


def test_a_pipeline_node_joins_the_chain_and_a_pipeline_cannot_call_itself(
    client: TestClient,
) -> None:
    outer, inner = _pipeline(client, stages=1), _pipeline(client, stages=1)
    outer["name"] = "Flow"
    block = _call(client, outer, inner)
    chain = client.get(f"/api/workflows/{outer['id']}/stages").json()
    assert [(e["kind"], e["name"]) for e in chain] == [("stage", "Stage 1"), ("pipeline", "Flow")]
    assert chain[1]["pipeline_id"] == inner["id"]
    url = f"/api/workflows/{outer['id']}/nodes/{block['id']}"
    assert client.patch(url, json={"definition_id": outer["id"]}).status_code == 422  # itself
    inner_block = _node(client, inner, "pipeline")  # inner → outer would close a circle
    response = client.patch(
        f"/api/workflows/{inner['id']}/nodes/{inner_block['id']}",
        json={"definition_id": outer["id"]},
    )
    assert response.status_code == 422
    action = client.post("/api/workflows", json={"name": "An action", "kind": "action"}).json()
    assert client.patch(url, json={"definition_id": action["id"]}).status_code == 422


def test_a_run_goes_through_the_called_pipeline_and_on(client: TestClient) -> None:
    outer, inner = _pipeline(client, stages=1), _pipeline(client, stages=2)
    _call(client, outer, inner)
    task = _task(client)
    _post(client, f"/api/tasks/{task['id']}/run", workflow_id=outer["id"])
    run = _wait(client, task, "done")
    assert [s["status"] for s in run["stages"]] == ["passed", "passed"]  # Stage 1 and the node
    # the run rests where it ended: in the called pipeline, at its last stage and action
    assert (run["pipeline_id"], run["stage_name"]) == (inner["id"], "Stage 2")
    assert run["action_name"] == "Action" and run["resume_stage_id"] == run["stages"][1]["id"]


def test_a_pipeline_node_without_a_pipeline_fails_the_run(client: TestClient) -> None:
    outer = _pipeline(client, stages=1)
    graph = client.get(f"/api/workflows/{outer['id']}").json()
    complete = next(n for n in graph["nodes"] if n["kind"] == "complete")
    block = _node(client, outer, "pipeline")
    _connect(client, outer, outer["stages"][0][0], "end", block, "in")
    _connect(client, outer, block, "out", complete, "in")
    task = _task(client)
    _post(client, f"/api/tasks/{task['id']}/run", workflow_id=outer["id"])
    run = _wait(client, task, "failed")
    assert "no pipeline" in run["note"]
    assert run["stages"][1]["status"] == "failed"


def test_a_pipeline_node_calls_only_pipelines_in_a_pipeline(client: TestClient) -> None:
    definition = client.post("/api/workflows", json={"name": "Def", "kind": "action"}).json()
    response = client.post(f"/api/workflows/{definition['id']}/nodes", json={"kind": "pipeline"})
    assert response.status_code == 422
