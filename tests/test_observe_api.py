"""The observe mode through the REST API, the integration API and the MCP server (ADR-088): reading, setting, publishing only the mode, releasing,
observing again, and what a start from outside is told."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import build_pipeline, make_task, node, wait_for_run
from tests.test_execution_nodes import _definition, _use
from tests.test_mcp import _call as mcp_call

TOKEN = "observe-api-token-" + "x" * 30
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def _pipeline(api: TestClient) -> dict[str, Any]:
    pipeline = build_pipeline(api, stages=1)
    _use(api, pipeline, _definition(api, "artifact", operation="Add comment", text="Hello"))
    return pipeline


def _url(pipeline: dict[str, Any], door: str = "/api", tail: str = "") -> str:
    return f"{door}/pipelines/{pipeline['id']}/observe{tail}"


def _on(
    api: TestClient, pipeline: dict[str, Any], door: str = "/api", **setting: Any
) -> dict[str, Any]:
    response = api.put(_url(pipeline, door), json={"enabled": True, "publish": True, **setting})
    assert response.status_code == 200, response.text
    return dict(response.json())


def _comments(api: TestClient, task: dict[str, Any]) -> list[Any]:
    return list(api.get(f"/api/tasks/{task['id']}/comments").json())


# ── reading and setting ──────────────────────────────────────────────


def test_a_pipeline_that_never_had_the_mode_reads_as_off(api: TestClient) -> None:
    pipeline = _pipeline(api)
    for door in ("/api", "/api/v1"):
        read = api.get(_url(pipeline, door)).json()
        assert read["pipeline_id"] == pipeline["id"] and read["pipeline_name"] == pipeline["name"]
        assert read["draft"] is None and read["published"] is None
        assert read["draft_differs"] is False
        state = read["state"]
        assert state["enabled"] is False and state["observing"] is False and state["ended"] is False
        assert state["events"] == []


def test_a_pipeline_is_found_by_id_slug_or_name_and_an_unknown_one_is_404(
    api: TestClient,
) -> None:
    pipeline = _pipeline(api)
    for ref in (pipeline["id"], pipeline["slug"], pipeline["name"]):
        assert api.get(f"/api/pipelines/{ref}/observe").status_code == 200
    assert api.get("/api/pipelines/none/observe").status_code == 404
    action = api.get("/api/actions").json()[0]
    assert api.get(f"/api/pipelines/{action['id']}/observe").status_code == 404, (
        "an action has no mode"
    )


def test_setting_the_draft_changes_nothing_that_runs_until_it_is_published(
    api: TestClient,
) -> None:
    pipeline, task = _pipeline(api), make_task(api)
    api.post(f"/api/pipelines/{pipeline['id']}/publish", json={"acknowledge": True})
    put = api.put(_url(pipeline), json={"enabled": True, "days": 7})
    assert put.status_code == 200, put.text
    read = put.json()
    assert read["draft"] == {"enabled": True, "days": 7, "runs": None}
    assert read["published"] is None and read["draft_differs"] is True
    started = api.post(f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]})
    assert started.json()["observed"] is False
    wait_for_run(api, task, "done")
    assert len(_comments(api, task)) == 1


def test_a_setting_that_does_not_fit_is_refused_and_says_why(api: TestClient) -> None:
    pipeline = _pipeline(api)
    for body, text in (
        ({"enabled": True, "days": 0}, "between 1 and 365"),
        ({"enabled": True, "runs": 100001}, "between 1 and 100000"),
    ):
        response = api.put(_url(pipeline), json=body)
        assert response.status_code == 422 and text in response.text
    unknown = api.put(_url(pipeline), json={"enabled": True, "weeks": 2})
    assert unknown.status_code == 422
    assert api.put(_url(pipeline), json={"days": 3}).status_code == 422, "enabled is needed"
    assert api.get(_url(pipeline)).json()["draft"] is None, "nothing was kept"


def test_publish_in_the_same_call_makes_every_start_observed(api: TestClient) -> None:
    pipeline, task = _pipeline(api), make_task(api)
    read = _on(api, pipeline, runs=3)
    assert read["published"] == {"enabled": True, "days": None, "runs": 3}
    assert read["draft_differs"] is False
    assert read["state"]["observing"] is True and read["state"]["runs"] == 3
    started = api.post(f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]})
    assert started.json()["observed"] is True and started.json()["dry_run"] is True
    wait_for_run(api, task, "done")
    assert _comments(api, task) == []
    assert api.get(_url(pipeline)).json()["state"]["runs_done"] == 1


def test_publish_in_the_same_call_is_refused_when_the_draft_holds_other_changes(
    api: TestClient,
) -> None:
    pipeline = _pipeline(api)
    api.post(f"/api/pipelines/{pipeline['id']}/publish", json={"acknowledge": True})
    node(api, pipeline, "stage", name="Unpublished stage")
    refused = api.put(_url(pipeline), json={"enabled": True, "publish": True})
    assert refused.status_code == 409
    assert refused.json()["code"] == "draft_has_other_changes"
    read = api.get(_url(pipeline)).json()
    assert read["published"] is None, "nothing went live"
    assert read["draft"] is None, "a refusal changes nothing, not even the draft"
    assert "nothing was changed" in refused.json()["detail"]


def test_switching_off_with_publish_makes_the_pipeline_real_again(api: TestClient) -> None:
    pipeline, task = _pipeline(api), make_task(api)
    _on(api, pipeline)
    read = api.put(_url(pipeline), json={"enabled": False, "publish": True}).json()
    assert read["published"] is None and read["state"]["enabled"] is False
    assert [e["action"] for e in read["state"]["events"]] == ["on", "off"]
    started = api.post(f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]})
    assert started.json()["observed"] is False


# ── release and observe again ────────────────────────────────────────


def _ended(api: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    pipeline = _pipeline(api)
    _on(api, pipeline, runs=1)
    first = make_task(api, "Counts")
    api.post(
        f"/api/tasks/{first['id']}/run", json={"pipeline_id": pipeline["id"]}
    ).raise_for_status()
    wait_for_run(api, first, "done")
    return pipeline, make_task(api, "Refused")


def test_an_ended_observation_refuses_a_start_from_every_door(api: TestClient) -> None:
    pipeline, task = _ended(api)
    state = api.get(_url(pipeline)).json()["state"]
    assert state["ended"] is True and "has ended" in state["reason"]
    via_ui = api.post(f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]})
    assert via_ui.status_code == 409 and via_ui.json()["code"] == "observation_ended"
    via_api = api.post(
        f"/api/v1/artifacts/{task['number']}/run", json={"pipeline_id": pipeline["id"]}
    )
    assert via_api.status_code == 409 and via_api.json()["code"] == "observation_ended"
    failed, text = mcp_call(
        api, "start_processing", artifact=str(task["number"]), pipeline=pipeline["id"]
    )
    assert failed and "Observation of the pipeline" in text and "has ended" in text


def test_release_runs_for_real_again_and_records_who_decided(api: TestClient) -> None:
    pipeline, task = _ended(api)
    released = api.post(_url(pipeline, tail="/release"))
    assert released.status_code == 200, released.text
    state = released.json()["state"]
    assert state["released"] is True and state["ended"] is False and state["observing"] is False
    started = api.post(
        f"/api/v1/artifacts/{task['number']}/run", json={"pipeline_id": pipeline["id"]}
    )
    assert started.status_code == 201 and started.json()["observed"] is False
    wait_for_run(api, task, "done")
    assert len(_comments(api, task)) == 1
    assert api.post(_url(pipeline, tail="/release")).status_code == 409, "released already"
    last = state["events"][-1]
    assert last["action"] == "release" and last["by"] == "user"


def test_observe_again_starts_a_new_observation_and_records_the_door(api: TestClient) -> None:
    pipeline, task = _ended(api)
    refused = api.post(_url(pipeline, "/api/v1", "/again"), json={"runs": 0})
    assert refused.status_code == 422
    again = api.post(_url(pipeline, "/api/v1", "/again"), json={"runs": 2})
    assert again.status_code == 200, again.text
    state = again.json()["state"]
    assert state["observing"] is True and state["runs"] == 2 and state["runs_done"] == 0
    assert state["events"][-1]["by"] == "api"
    started = api.post(f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]})
    assert started.json()["observed"] is True


def test_release_and_again_are_refused_while_the_published_version_has_no_mode(
    api: TestClient,
) -> None:
    pipeline = _pipeline(api)
    api.post(f"/api/pipelines/{pipeline['id']}/publish", json={"acknowledge": True})
    released = api.post(_url(pipeline, tail="/release"))
    assert released.status_code == 409 and "not observed" in released.text
    again = api.post(_url(pipeline, tail="/again"))
    assert again.status_code == 409 and "no observe mode" in again.text


# ── the MCP server ───────────────────────────────────────────────────


def test_the_mcp_tools_read_set_publish_release_and_observe_again(api: TestClient) -> None:
    pipeline, task = _pipeline(api), make_task(api)
    failed, read = mcp_call(api, "get_observe_mode", pipeline=pipeline["name"])
    assert not failed and read["published"] is None and read["state"]["observing"] is False
    failed, read = mcp_call(
        api, "set_observe_mode", pipeline=pipeline["name"], enabled=True, runs=1, publish=True
    )
    assert not failed, read
    assert read["published"] == {"enabled": True, "days": None, "runs": 1}
    failed, started = mcp_call(
        api, "start_processing", artifact=str(task["number"]), pipeline=pipeline["id"]
    )
    assert not failed and started["observed"] is True and started["dry_run"] is True
    wait_for_run(api, task, "done")
    other = make_task(api, "Over")
    failed, text = mcp_call(
        api, "start_processing", artifact=str(other["number"]), pipeline=pipeline["id"]
    )
    assert failed and "Decide: observe it again or release it" in text
    failed, state = mcp_call(api, "observe_again", pipeline=pipeline["id"], days=2)
    assert not failed and state["state"]["observing"] is True and state["state"]["days"] == 2
    failed, state = mcp_call(api, "release_observe_block", pipeline=pipeline["id"])
    assert not failed and state["state"]["released"] is True
    assert [e["by"] for e in state["state"]["events"]] == ["api", "mcp", "mcp"]
    failed, started = mcp_call(
        api, "start_processing", artifact=str(other["number"]), pipeline=pipeline["id"]
    )
    assert not failed and started["observed"] is False


def test_the_mcp_tool_will_not_publish_other_changes_with_the_mode(api: TestClient) -> None:
    pipeline = _pipeline(api)
    api.post(f"/api/pipelines/{pipeline['id']}/publish", json={"acknowledge": True})
    node(api, pipeline, "stage", name="Unpublished stage")
    failed, text = mcp_call(
        api, "set_observe_mode", pipeline=pipeline["id"], enabled=True, publish=True
    )
    assert failed and "other unpublished changes" in text
    failed, read = mcp_call(api, "set_observe_mode", pipeline=pipeline["id"], enabled=True)
    assert not failed and read["draft_differs"] is True and read["published"] is None


def test_the_mcp_tools_are_offered_and_none_of_them_deletes(api: TestClient) -> None:
    response = api.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in response.json()["result"]["tools"]}
    assert {
        "get_observe_mode",
        "set_observe_mode",
        "release_observe_block",
        "observe_again",
    } <= names
    assert not {n for n in names if "observe" in n and "delete" in n}
