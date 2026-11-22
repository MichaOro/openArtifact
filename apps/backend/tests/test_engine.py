"""Pipeline runs: starting, skipping, locking, stopping and failing."""

from __future__ import annotations

import asyncio
import itertools
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.engine.runner import RunEngine
from openartifact.exceptions import ArtifactError
from tests.helpers import (
    build_definition,
    build_pipeline,
    connect,
    graph_url,
    link,
    make_task,
    node,
    post,
    run_of,
    slow_pipeline,
    wait_for_run,
)


def test_the_stages_come_in_the_order_of_the_pipeline(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=3)
    chain = client.get(f"{graph_url(pipeline)}/stages").json()
    assert [s["name"] for s in chain] == ["Stage 1", "Stage 2", "Stage 3"]
    assert chain[0]["first_action_id"] == pipeline["stages"][0][1]["id"]


def test_a_run_goes_through_every_stage_to_done(client: TestClient) -> None:
    pipeline = build_pipeline(client)
    task = make_task(client)
    started = post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    assert (started["started_by"], started["stage_name"]) == ("user", "Stage 1")
    run = wait_for_run(client, task, "done")
    assert [s["status"] for s in run["stages"]] == ["passed", "passed"]


def test_starting_in_a_later_stage_skips_the_earlier_ones(client: TestClient) -> None:
    pipeline = build_pipeline(client)
    task = make_task(client)
    second = pipeline["stages"][1][0]
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"], stage_id=second["id"])
    run = wait_for_run(client, task, "done")
    assert [s["status"] for s in run["stages"]] == ["skipped", "passed"]
    # going back: the first stage runs again, the second is pending until it is reached again
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = wait_for_run(client, task, "done")
    assert [s["status"] for s in run["stages"]] == ["passed", "passed"]


def test_a_start_must_name_a_stage_and_action_of_the_pipeline(client: TestClient) -> None:
    pipeline = build_pipeline(client)
    other = build_pipeline(client)
    task = make_task(client)
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


def test_a_running_artifact_is_locked_until_it_is_stopped(client: TestClient) -> None:
    pipeline = slow_pipeline(client)
    task = make_task(client)
    url = f"/api/tasks/{task['id']}"
    post(client, f"{url}/run", pipeline_id=pipeline["id"])
    assert client.post(f"{url}/run", json={"pipeline_id": pipeline["id"]}).status_code == 409
    assert client.patch(url, json={"status": "done"}).status_code == 409
    assert client.patch(url, json={"parent_id": None}).status_code == 409
    assert client.delete(url).status_code == 409
    assert client.patch(url, json={"title": "Renamed"}).status_code == 200  # content stays editable

    stopped = post(client, f"{url}/run/stop")
    assert (stopped["status"], stopped["note"]) == ("stopped", "stopped")
    assert stopped["stage_name"] == "Stage 1"  # it stays where it was
    assert client.post(f"{url}/run/stop").status_code == 409
    assert client.patch(url, json={"status": "done"}).status_code == 200
    assert client.delete(url).status_code == 204


def test_an_artifact_can_start_again_the_moment_its_run_is_over(client: TestClient) -> None:
    """The in-process job is forgotten before the final events go out, not after.

    A client that has seen `done` in the database must not be refused ("already being processed")
    while the engine is still publishing: the guard follows the database state.
    """
    engine = client.app.state.engine  # type: ignore[attr-defined]
    seen: list[bool] = []
    real_publish = engine._publish

    async def watching(task_id: str) -> None:
        seen.append(task_id in engine._jobs)
        await real_publish(task_id)

    engine._publish = watching
    pipeline = build_pipeline(client, stages=1)
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(client, task, "done")
    assert seen and not seen[-1], "the finished run was still registered while publishing"
    # and it really can start again at once, many times in a row
    for _ in range(3):
        again = client.post(f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]})
        assert again.status_code == 201, again.text
        wait_for_run(client, task, "done")


def test_an_action_without_a_way_to_its_output_fails_the_run(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1)
    definition = post(client, "/api/actions", name="Broken")
    graph = client.get(graph_url(definition)).json()
    client.delete(
        f"{graph_url(definition)}/edges/{graph['edges'][0]['id']}"
    )  # cut trigger → output
    action = pipeline["stages"][0][1]
    client.patch(
        f"{graph_url(pipeline)}/nodes/{action['id']}",
        json={"definition_id": definition["id"]},
    )
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = wait_for_run(client, task, "failed")
    assert "Broken" in run["note"]
    assert run["stages"][0]["status"] == "failed"


def test_a_run_publishes_every_change_as_an_event(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    pipeline = build_pipeline(client, stages=2)
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(client, task, "done")
    runs = [data for kind, data in published if kind == "run.updated"]
    assert runs[0]["status"] == "running" and runs[-1]["status"] == "done"
    assert {r["status"] for r in runs} == {"running", "done"}
    # the progress is visible in the stream: stage 1 is passed while stage 2 is still to do
    assert any([s["status"] for s in r["stages"]] == ["passed", "running"] for r in runs), (
        "no event showed the run between its stages"
    )
    assert runs[-1]["stage_name"] == "Stage 2"


def test_stopping_publishes_the_stopped_run(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    pipeline = slow_pipeline(client)
    task = make_task(client)
    url = f"/api/tasks/{task['id']}/run"
    post(client, url, pipeline_id=pipeline["id"])
    wait_for_run(client, task, "running", lambda r: r["stages"][0]["status"] == "running")
    post(client, f"{url}/stop")
    last = [data for kind, data in published if kind == "run.updated"][-1]
    assert (last["status"], last["note"]) == ("stopped", "stopped")
    assert last["stages"][0]["status"] == "pending"  # it waits for the next start


def test_a_failed_run_is_published_with_its_note(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    pipeline = build_pipeline(client, stages=1)
    link(
        client, pipeline, pipeline["stages"][0][1], build_definition(client, "Broken", output=None)
    )
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(client, task, "failed")
    last = [data for kind, data in published if kind == "run.updated"][-1]
    assert (last["status"], last["note"]) == ("failed", '"Broken" failed')


def test_runs_are_removed_with_their_artifact(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1)
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(client, task, "done")
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert client.get("/api/runs").json() == []


# ── pipeline nodes: a pipeline that calls another pipeline ────────────


def _call(client: TestClient, caller: dict[str, Any], called: dict[str, Any]) -> dict[str, Any]:
    """A pipeline node in ``caller`` (between its last stage and complete) that calls ``called``."""
    graph = client.get(graph_url(caller)).json()
    complete = next(n for n in graph["nodes"] if n["kind"] == "complete")
    last_stage = caller["stages"][-1][0]
    block = node(client, caller, "pipeline")
    connect(client, caller, last_stage, "end", block, "in")
    connect(client, caller, block, "out", complete, "in")
    response = client.patch(
        f"{graph_url(caller)}/nodes/{block['id']}", json={"definition_id": called["id"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["definition_name"] == called["name"]
    return block


def test_a_pipeline_node_joins_the_chain_and_a_pipeline_cannot_call_itself(
    client: TestClient,
) -> None:
    outer, inner = build_pipeline(client, stages=1), build_pipeline(client, stages=1)
    outer["name"] = "Flow"
    block = _call(client, outer, inner)
    chain = client.get(f"{graph_url(outer)}/stages").json()
    assert [(e["kind"], e["name"]) for e in chain] == [("stage", "Stage 1"), ("pipeline", "Flow")]
    assert chain[1]["pipeline_id"] == inner["id"]
    url = f"{graph_url(outer)}/nodes/{block['id']}"
    assert client.patch(url, json={"definition_id": outer["id"]}).status_code == 422  # itself
    inner_block = node(client, inner, "pipeline")  # inner → outer would close a circle
    response = client.patch(
        f"{graph_url(inner)}/nodes/{inner_block['id']}",
        json={"definition_id": outer["id"]},
    )
    assert response.status_code == 422
    action = client.post("/api/actions", json={"name": "An action"}).json()
    assert client.patch(url, json={"definition_id": action["id"]}).status_code == 422


def test_a_run_goes_through_the_called_pipeline_and_on(client: TestClient) -> None:
    outer, inner = build_pipeline(client, stages=1), build_pipeline(client, stages=2)
    _call(client, outer, inner)
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=outer["id"])
    run = wait_for_run(client, task, "done")
    assert [s["status"] for s in run["stages"]] == ["passed", "passed"]  # Stage 1 and the node
    # the run rests where it ended: in the called pipeline, at its last stage and action
    assert (run["pipeline_id"], run["stage_name"]) == (inner["id"], "Stage 2")
    assert run["action_name"] == "Action" and run["resume_stage_id"] == run["stages"][1]["id"]


def test_a_pipeline_node_without_a_pipeline_fails_the_run(client: TestClient) -> None:
    outer = build_pipeline(client, stages=1)
    graph = client.get(graph_url(outer)).json()
    complete = next(n for n in graph["nodes"] if n["kind"] == "complete")
    block = node(client, outer, "pipeline")
    connect(client, outer, outer["stages"][0][0], "end", block, "in")
    connect(client, outer, block, "out", complete, "in")
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=outer["id"])
    run = wait_for_run(client, task, "failed")
    assert "no pipeline" in run["note"]
    assert run["stages"][1]["status"] == "failed"


def test_a_pipeline_node_calls_only_pipelines_in_a_pipeline(client: TestClient) -> None:
    definition = client.post("/api/actions", json={"name": "Def"}).json()
    response = client.post(f"{graph_url(definition)}/nodes", json={"kind": "pipeline"})
    assert response.status_code == 422


# ── how a run is returned and what a start publishes ──────────────────


def _drain(queue: Any) -> list[Any]:
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


def test_a_run_is_returned_typed_with_utc_timestamps_everywhere(client: TestClient) -> None:
    """The start, the list and the ``run.updated`` event all write ``updated_at`` the way tasks do."""
    pipeline = build_pipeline(client, stages=1)
    task = make_task(client)
    queue = client.app.state.event_bus.subscribe()  # type: ignore[attr-defined]
    started = post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(client, task, "done")
    listed = run_of(client, task)
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
    pipeline = build_pipeline(client, stages=1)
    task = make_task(client)
    queue = client.app.state.event_bus.subscribe()  # type: ignore[attr-defined]
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(client, task, "done")

    updates = [e.data for e in _drain(queue) if e.type == "task.updated"]
    assert [u["id"] for u in updates] == [task["id"]]
    assert updates[0]["pipeline_id"] == pipeline["id"]
    assert updates[0]["stage_id"] == pipeline["stages"][0][0]["id"]

    # starting again with what the artifact has changes nothing, so nothing is published
    post(client, f"/api/tasks/{task['id']}/run")
    wait_for_run(client, task, "done")
    assert not [e for e in _drain(queue) if e.type == "task.updated"]


# ── what an action's definition decides ───────────────────────────────


def test_an_action_whose_definition_reaches_its_output_passes(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1)
    link(client, pipeline, pipeline["stages"][0][1], build_definition(client, "Check"))
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = wait_for_run(client, task, "done")
    assert [s["status"] for s in run["stages"]] == ["passed"]
    assert run["action_name"] == "Check"


def test_a_definition_that_ends_on_fail_follows_the_on_error_connection(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1)
    stage, action = pipeline["stages"][0]
    definition = build_definition(client, "Check", output="fail", fail_enabled=True)
    link(client, pipeline, action, definition)
    task = make_task(client)
    url = f"/api/tasks/{task['id']}/run"

    post(client, url, pipeline_id=pipeline["id"])  # On Fail leads nowhere: the run fails
    run = wait_for_run(client, task, "failed")
    assert run["note"] == '"Check" failed'
    assert run["stages"][0]["status"] == "failed"

    connect(client, pipeline, action, "error", stage, "end")  # On Error leaves the stage
    post(client, url, pipeline_id=pipeline["id"])
    assert [s["status"] for s in wait_for_run(client, task, "done")["stages"]] == ["passed"]


def test_an_action_that_passes_without_an_on_pass_connection_fails_the_run(
    client: TestClient,
) -> None:
    pipeline = build_pipeline(client, stages=1)
    action = pipeline["stages"][0][1]
    edges = client.get(graph_url(pipeline)).json()["edges"]
    on_pass = next(
        e for e in edges if e["source_id"] == action["id"] and e["source_port"] == "pass"
    )
    assert client.delete(f"{graph_url(pipeline)}/edges/{on_pass['id']}").status_code == 204
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    assert "no On Pass connection" in wait_for_run(client, task, "failed")["note"]


def test_a_timer_that_finishes_lets_the_run_go_on(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import openartifact.engine.executors as executors

    waited: list[float] = []
    real_asyncio = asyncio

    async def sleep(seconds: float) -> None:
        waited.append(seconds)
        await real_asyncio.sleep(0)

    monkeypatch.setattr(
        executors, "asyncio", SimpleNamespace(**{**vars(real_asyncio), "sleep": sleep})
    )
    pipeline = slow_pipeline(client, seconds=3600)
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    assert wait_for_run(client, task, "done")["stages"][0]["status"] == "passed"
    assert waited == [3600]


def test_a_definition_without_a_way_out_is_a_loop_that_ends(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Error back into the same action: the run fails instead of running for ever."""
    import openartifact.engine.runner as runner

    monkeypatch.setattr(runner, "MAX_STEPS", 5)
    pipeline = build_pipeline(client, stages=1)
    _, action = pipeline["stages"][0]
    link(
        client, pipeline, action, build_definition(client, "Never", output=None, fail_enabled=True)
    )
    connect(client, pipeline, action, "error", action, "in")
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    assert wait_for_run(client, task, "failed")["note"] == "The pipeline does not come to an end"


def test_an_unexpected_error_fails_the_run_without_leaking_details(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def boom(node: Any, walk: Any) -> bool:
        raise RuntimeError("secret detail")

    monkeypatch.setattr(RunEngine, "_run_action", staticmethod(boom))
    pipeline = build_pipeline(client, stages=1)
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = wait_for_run(client, task, "failed")
    assert run["note"] == "Internal error"
    assert "secret detail" not in str(client.get("/api/runs").json())


# ── what cannot be started ────────────────────────────────────────────


def test_a_pipeline_without_stages_cannot_be_started(client: TestClient) -> None:
    empty = post(client, "/api/pipelines", name="Empty")
    task = make_task(client)
    response = client.post(f"/api/tasks/{task['id']}/run", json={"pipeline_id": empty["id"]})
    assert response.status_code == 422 and "no stages" in response.json()["detail"]
    assert client.get("/api/runs").json() == []  # nothing was claimed


def _chain_of_pipelines(client: TestClient, count: int) -> list[dict[str, Any]]:
    pipelines = [build_pipeline(client, stages=1, name=f"P{i}") for i in range(count)]
    for caller, called in itertools.pairwise(pipelines):
        _call(client, caller, called)
    return pipelines


def test_pipelines_can_be_nested_five_deep_but_not_deeper(client: TestClient) -> None:
    task = make_task(client)
    url = f"/api/tasks/{task['id']}/run"

    five = _chain_of_pipelines(client, 5)
    post(client, url, pipeline_id=five[0]["id"])
    run = wait_for_run(client, task, "done")
    assert run["pipeline_id"] == five[-1]["id"]  # it rests in the innermost pipeline
    assert run["resume_stage_id"] == run["stages"][-1]["id"]

    six = _chain_of_pipelines(client, 6)
    response = client.post(url, json={"pipeline_id": six[0]["id"]})
    assert response.status_code == 422 and "nested too deeply" in response.json()["detail"]


def test_data_from_before_the_cycle_rule_cannot_be_started(
    client: TestClient, migrated_settings: Settings
) -> None:
    """A pipeline node that calls its own pipeline (possible only in old data) is refused."""
    pipeline = build_pipeline(client, stages=1)
    block = _call(client, pipeline, build_pipeline(client, stages=1))
    with sqlite3.connect(migrated_settings.data_dir / migrated_settings.database_filename) as db:
        db.execute(
            "UPDATE graph_nodes SET definition_id = ? WHERE id = ?", (pipeline["id"], block["id"])
        )
    task = make_task(client)
    response = client.post(f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]})
    assert response.status_code == 422 and "calls itself" in response.json()["detail"]


def test_a_stop_during_a_start_is_refused(client: TestClient) -> None:
    pipeline = slow_pipeline(client)
    task = make_task(client)
    engine: RunEngine = client.app.state.engine  # type: ignore[attr-defined]

    async def stop_while_starting() -> int:
        start = asyncio.ensure_future(engine.start(task["id"], pipeline["id"]))
        await asyncio.sleep(0)  # the start has begun and waits for the database
        with pytest.raises(ArtifactError) as refused:
            await engine.stop(task["id"])
        await start
        return refused.value.status

    assert client.portal.call(stop_while_starting) == 409  # type: ignore[union-attr]
    post(client, f"/api/tasks/{task['id']}/run/stop")


# ── a failing or stopped run inside a called pipeline ─────────────────


def test_a_failure_inside_a_called_pipeline_fails_the_entry_of_the_outer_one(
    client: TestClient,
) -> None:
    outer, inner = build_pipeline(client, stages=1), build_pipeline(client, stages=1, name="Inner")
    link(client, inner, inner["stages"][0][1], build_definition(client, "Broken", output=None))
    block = _call(client, outer, inner)
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=outer["id"])
    run = wait_for_run(client, task, "failed")
    assert [s["status"] for s in run["stages"]] == ["passed", "failed"]
    assert [s["id"] for s in run["stages"]][1] == block["id"]
    assert (run["pipeline_id"], run["pipeline_name"]) == (inner["id"], "Inner")
    assert run["note"] == '"Broken" failed'


def test_a_run_stopped_inside_a_called_pipeline_resumes_at_the_calling_entry(
    client: TestClient,
) -> None:
    outer, inner = build_pipeline(client, stages=1), slow_pipeline(client)
    block = _call(client, outer, inner)
    task = make_task(client)
    url = f"/api/tasks/{task['id']}/run"
    post(client, url, pipeline_id=outer["id"])
    inner_stage = inner["stages"][0][0]
    wait_for_run(client, task, "running", lambda r: r["stage_id"] == inner_stage["id"])

    stopped = post(client, f"{url}/stop")
    assert stopped["status"] == "stopped" and stopped["pipeline_id"] == inner["id"]
    assert stopped["resume_stage_id"] == block["id"]
    assert stopped["resume_action_id"] is None  # a pipeline node has no action to resume at
    assert [s["status"] for s in stopped["stages"]] == ["passed", "pending"]

    again = post(client, url, pipeline_id=outer["id"], stage_id=stopped["resume_stage_id"])
    assert again["status"] == "running"
    post(client, f"{url}/stop")


def test_the_position_of_a_run_is_found_through_two_levels_of_calls(client: TestClient) -> None:
    a, _, c = _chain_of_pipelines(client, 3)
    task = make_task(client)
    url = f"/api/tasks/{task['id']}/run"
    # make the innermost pipeline slow, so the run is in it while we look
    link(client, c, c["stages"][0][1], build_definition(client, "Wait", seconds=30))
    post(client, url, pipeline_id=a["id"])
    wait_for_run(client, task, "running", lambda r: r["stage_id"] == c["stages"][0][0]["id"])
    stopped = post(client, f"{url}/stop")
    assert stopped["pipeline_id"] == c["id"] and stopped["root_pipeline_id"] == a["id"]
    block_in_a = client.get(f"{graph_url(a)}/stages").json()[1]
    assert stopped["resume_stage_id"] == block_in_a["id"]


# ── after a restart ───────────────────────────────────────────────────


def test_a_restart_stops_the_runs_that_were_running_and_unlocks_their_artifacts(
    migrated_settings: Settings,
) -> None:
    with TestClient(_create_app(migrated_settings)) as first:
        pipeline = slow_pipeline(first)
        task = make_task(first)
        post(first, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
        wait_for_run(first, task, "running", lambda r: r["stages"][0]["status"] == "running")
    # leaving the block cancelled the job; the row still says running, as after a crash

    with TestClient(_create_app(migrated_settings)) as second:
        run = run_of(second, task)
        assert (run["status"], run["note"]) == ("stopped", "interrupted")
        assert [s["status"] for s in run["stages"]] == ["pending"]
        assert run["stage_name"] == "Stage 1"  # it can be started again where it was
        url = f"/api/tasks/{task['id']}"
        assert second.patch(url, json={"status": "done"}).status_code == 200
        assert second.delete(url).status_code == 204
