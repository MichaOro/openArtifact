"""Pipeline runs: starting, skipping, locking, stopping and failing."""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient


def _url(graph: dict[str, Any]) -> str:
    return f"/api/{'actions' if graph['kind'] == 'action' else 'pipelines'}/{graph['id']}"


def _post(client: TestClient, url: str, **body: Any) -> dict[str, Any]:
    response = client.post(url, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()  # type: ignore[no-any-return]


def _connect(
    client: TestClient,
    pipeline: dict[str, Any],
    a: dict[str, Any],
    ap: str,
    b: dict[str, Any],
    bp: str,
) -> None:
    _post(
        client,
        f"{_url(pipeline)}/edges",
        source_id=a["id"],
        source_port=ap,
        target_id=b["id"],
        target_port=bp,
    )


def _node(client: TestClient, pipeline: dict[str, Any], kind: str, **extra: Any) -> dict[str, Any]:
    return _post(client, f"{_url(pipeline)}/nodes", kind=kind, **extra)


def _pipeline(client: TestClient, stages: int = 2) -> dict[str, Any]:
    """Trigger → stage 1 → ... → complete, each stage with one empty action."""
    pipeline = _post(client, "/api/pipelines", name="Flow")
    nodes = client.get(_url(pipeline)).json()["nodes"]
    trigger = next(n for n in nodes if n["kind"] == "trigger")
    complete = next(n for n in nodes if n["kind"] == "complete")
    previous, port = trigger, "out"
    made = []
    for i in range(stages):
        stage = _node(client, pipeline, "stage", name=f"Stage {i + 1}")
        action = _node(client, pipeline, "action", stage_id=stage["id"], x=24, y=48)
        _connect(client, pipeline, previous, port, stage, "start")
        _connect(client, pipeline, stage, "start", action, "in")
        _connect(client, pipeline, action, "pass", stage, "end")
        previous, port = stage, "end"
        made.append((stage, action))
    _connect(client, pipeline, previous, port, complete, "in")
    pipeline["stages"] = made
    return pipeline


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
    pipeline = _pipeline(client, stages=3)
    chain = client.get(f"{_url(pipeline)}/stages").json()
    assert [s["name"] for s in chain] == ["Stage 1", "Stage 2", "Stage 3"]
    assert chain[0]["first_action_id"] == pipeline["stages"][0][1]["id"]


def test_a_run_goes_through_every_stage_to_done(client: TestClient) -> None:
    pipeline = _pipeline(client)
    task = _task(client)
    started = _post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    assert (started["started_by"], started["stage_name"]) == ("user", "Stage 1")
    run = _wait(client, task, "done")
    assert [s["status"] for s in run["stages"]] == ["passed", "passed"]


def test_starting_in_a_later_stage_skips_the_earlier_ones(client: TestClient) -> None:
    pipeline = _pipeline(client)
    task = _task(client)
    second = pipeline["stages"][1][0]
    _post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"], stage_id=second["id"])
    run = _wait(client, task, "done")
    assert [s["status"] for s in run["stages"]] == ["skipped", "passed"]
    # going back: the first stage runs again, the second is pending until it is reached again
    _post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = _wait(client, task, "done")
    assert [s["status"] for s in run["stages"]] == ["passed", "passed"]


def test_a_start_must_name_a_stage_and_action_of_the_pipeline(client: TestClient) -> None:
    pipeline = _pipeline(client)
    other = _pipeline(client)
    task = _task(client)
    url = f"/api/tasks/{task['id']}/run"
    stranger = other["stages"][0][0]["id"]
    assert (
        client.post(url, json={"pipeline_id": pipeline["id"], "stage_id": stranger}).status_code
        == 422
    )
    wrong_action = other["stages"][0][1]["id"]
    body = {
        "pipeline_id": pipeline["id"],
        "stage_id": pipeline["stages"][0][0]["id"],
        "action_id": wrong_action,
    }
    assert client.post(url, json=body).status_code == 422
    assert client.post(url, json={"pipeline_id": "nope"}).status_code == 422
    assert (
        client.post("/api/tasks/nope/run", json={"pipeline_id": pipeline["id"]}).status_code == 404
    )


def _slow_pipeline(client: TestClient) -> dict[str, Any]:
    """A pipeline whose only action waits 30 seconds (a timer in its definition)."""
    pipeline = _pipeline(client, stages=1)
    definition = _post(client, "/api/actions", name="Wait")
    nodes = client.get(_url(definition)).json()["nodes"]
    trigger = next(n for n in nodes if n["kind"] == "trigger")
    output = next(n for n in nodes if n["kind"] == "output")
    timer = _node(client, definition, "timer", seconds=30)
    _connect(client, definition, trigger, "out", timer, "in")
    _connect(client, definition, timer, "out", output, "pass")
    action = pipeline["stages"][0][1]
    response = client.patch(
        f"{_url(pipeline)}/nodes/{action['id']}",
        json={"definition_id": definition["id"]},
    )
    assert response.status_code == 200
    return pipeline


def test_a_running_artifact_is_locked_until_it_is_stopped(client: TestClient) -> None:
    pipeline = _slow_pipeline(client)
    task = _task(client)
    url = f"/api/tasks/{task['id']}"
    _post(client, f"{url}/run", pipeline_id=pipeline["id"])
    assert client.post(f"{url}/run", json={"pipeline_id": pipeline["id"]}).status_code == 409
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
    pipeline = _pipeline(client, stages=1)
    definition = _post(client, "/api/actions", name="Broken")
    graph = client.get(_url(definition)).json()
    client.delete(f"{_url(definition)}/edges/{graph['edges'][0]['id']}")  # cut trigger → output
    action = pipeline["stages"][0][1]
    client.patch(
        f"{_url(pipeline)}/nodes/{action['id']}",
        json={"definition_id": definition["id"]},
    )
    task = _task(client)
    _post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = _wait(client, task, "failed")
    assert "Broken" in run["note"]
    assert run["stages"][0]["status"] == "failed"


def test_runs_are_published_as_events_and_removed_with_their_artifact(client: TestClient) -> None:
    pipeline = _pipeline(client, stages=1)
    task = _task(client)
    _post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    _wait(client, task, "done")
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert client.get("/api/runs").json() == []


# ── pipeline nodes: a pipeline that calls another pipeline ────────────


def _call(client: TestClient, caller: dict[str, Any], called: dict[str, Any]) -> dict[str, Any]:
    """A pipeline node in ``caller`` (between its last stage and complete) that calls ``called``."""
    graph = client.get(_url(caller)).json()
    complete = next(n for n in graph["nodes"] if n["kind"] == "complete")
    last_stage = caller["stages"][-1][0]
    block = _node(client, caller, "pipeline")
    _connect(client, caller, last_stage, "end", block, "in")
    _connect(client, caller, block, "out", complete, "in")
    response = client.patch(
        f"{_url(caller)}/nodes/{block['id']}", json={"definition_id": called["id"]}
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
    chain = client.get(f"{_url(outer)}/stages").json()
    assert [(e["kind"], e["name"]) for e in chain] == [("stage", "Stage 1"), ("pipeline", "Flow")]
    assert chain[1]["pipeline_id"] == inner["id"]
    url = f"{_url(outer)}/nodes/{block['id']}"
    assert client.patch(url, json={"definition_id": outer["id"]}).status_code == 422  # itself
    inner_block = _node(client, inner, "pipeline")  # inner → outer would close a circle
    response = client.patch(
        f"{_url(inner)}/nodes/{inner_block['id']}",
        json={"definition_id": outer["id"]},
    )
    assert response.status_code == 422
    action = client.post("/api/actions", json={"name": "An action"}).json()
    assert client.patch(url, json={"definition_id": action["id"]}).status_code == 422


def test_a_run_goes_through_the_called_pipeline_and_on(client: TestClient) -> None:
    outer, inner = _pipeline(client, stages=1), _pipeline(client, stages=2)
    _call(client, outer, inner)
    task = _task(client)
    _post(client, f"/api/tasks/{task['id']}/run", pipeline_id=outer["id"])
    run = _wait(client, task, "done")
    assert [s["status"] for s in run["stages"]] == ["passed", "passed"]  # Stage 1 and the node
    # the run rests where it ended: in the called pipeline, at its last stage and action
    assert (run["pipeline_id"], run["stage_name"]) == (inner["id"], "Stage 2")
    assert run["action_name"] == "Action" and run["resume_stage_id"] == run["stages"][1]["id"]


def test_a_pipeline_node_without_a_pipeline_fails_the_run(client: TestClient) -> None:
    outer = _pipeline(client, stages=1)
    graph = client.get(_url(outer)).json()
    complete = next(n for n in graph["nodes"] if n["kind"] == "complete")
    block = _node(client, outer, "pipeline")
    _connect(client, outer, outer["stages"][0][0], "end", block, "in")
    _connect(client, outer, block, "out", complete, "in")
    task = _task(client)
    _post(client, f"/api/tasks/{task['id']}/run", pipeline_id=outer["id"])
    run = _wait(client, task, "failed")
    assert "no pipeline" in run["note"]
    assert run["stages"][1]["status"] == "failed"


def test_a_pipeline_node_calls_only_pipelines_in_a_pipeline(client: TestClient) -> None:
    definition = client.post("/api/actions", json={"name": "Def"}).json()
    response = client.post(f"{_url(definition)}/nodes", json={"kind": "pipeline"})
    assert response.status_code == 422


# ── how a run is returned and what a start publishes ──────────────────


def _drain(queue: Any) -> list[Any]:
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


def test_a_run_is_returned_typed_with_utc_timestamps_everywhere(client: TestClient) -> None:
    """The start, the list and the ``run.updated`` event all write ``updated_at`` the way tasks do."""
    pipeline = _pipeline(client, stages=1)
    task = _task(client)
    queue = client.app.state.event_bus.subscribe()  # type: ignore[attr-defined]
    started = _post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    _wait(client, task, "done")
    listed = _run(client, task)
    published = [e.data for e in _drain(queue) if e.type == "run.updated"]

    assert published
    for run in (started, listed, *published):
        assert run["updated_at"].endswith("Z"), run["updated_at"]
        assert "+" not in run["updated_at"]
    assert set(started) == set(listed) == set(published[0])
    assert listed["status"] == "done"
    assert {s["status"] for s in listed["stages"]} == {"passed"}


def test_the_first_start_tells_the_boards_that_the_artifact_got_a_pipeline(
    client: TestClient,
) -> None:
    """The engine sets the artifact's pipeline, stage and action: ``task.updated`` says so."""
    pipeline = _pipeline(client, stages=1)
    task = _task(client)
    queue = client.app.state.event_bus.subscribe()  # type: ignore[attr-defined]
    _post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    _wait(client, task, "done")

    updates = [e.data for e in _drain(queue) if e.type == "task.updated"]
    assert [u["id"] for u in updates] == [task["id"]]
    assert updates[0]["pipeline_id"] == pipeline["id"]
    assert updates[0]["stage_id"] == pipeline["stages"][0][0]["id"]

    # starting again with what the artifact has changes nothing, so nothing is published
    _post(client, f"/api/tasks/{task['id']}/run")
    _wait(client, task, "done")
    assert not [e for e in _drain(queue) if e.type == "task.updated"]
