"""The integration API (/api/v1) and the MCP server: creating artifacts completely, and following them."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from tests.test_engine import _pipeline

TOKEN = "integration-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
MCP_HEADERS = {**HEADERS, "Accept": "application/json, text/event-stream"}


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    """The application with a token; the client sends it with every request."""
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def _create(api: TestClient, **body: Any) -> dict[str, Any]:
    response = api.post("/api/v1/artifacts", json=body)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def test_an_artifact_is_created_with_title_body_lane_and_origin(api: TestClient) -> None:
    created = _create(api, title="Analyse", body="Details", status="in_progress")
    assert (created["title"], created["body"], created["status"]) == (
        "Analyse",
        "Details",
        "in_progress",
    )
    assert (created["created_by"], created["number"]) == ("api", 1)
    assert (created["pipeline_id"], created["stage_id"], created["action_id"]) == (None, None, None)
    assert (
        api.get(f"/api/v1/artifacts/{created['number']}").json()["id"] == created["id"]
    )  # by number
    assert api.get(f"/api/v1/artifacts/{created['id']}").json()["title"] == "Analyse"


def test_a_new_artifact_can_be_a_child(api: TestClient) -> None:
    parent = _create(api, title="Epic")
    child = _create(api, title="Story", parent_id=parent["id"])
    assert child["parent_id"] == parent["id"]
    missing = api.post("/api/v1/artifacts", json={"title": "x", "parent_id": "nope"})
    assert missing.status_code == 422


def test_choosing_a_pipeline_selects_its_first_stage_and_action(api: TestClient) -> None:
    pipeline = _pipeline(api, stages=2)
    first_stage, first_action = pipeline["stages"][0]
    created = _create(api, title="Item", pipeline_id=pipeline["id"])
    assert (created["pipeline_id"], created["stage_id"], created["action_id"]) == (
        pipeline["id"],
        first_stage["id"],
        first_action["id"],
    )
    second_stage, second_action = pipeline["stages"][1]
    later = _create(api, title="Later", pipeline_id=pipeline["id"], stage_id=second_stage["id"])
    assert (later["stage_id"], later["action_id"]) == (second_stage["id"], second_action["id"])


def test_a_stage_or_action_that_does_not_fit_is_refused(api: TestClient) -> None:
    pipeline, other = _pipeline(api), _pipeline(api)

    def post(**body: Any) -> int:
        return api.post("/api/v1/artifacts", json={"title": "x", **body}).status_code

    assert post(pipeline_id="nope") == 422
    assert post(stage_id=pipeline["stages"][0][0]["id"]) == 422  # a stage needs a pipeline
    assert post(pipeline_id=pipeline["id"], stage_id=other["stages"][0][0]["id"]) == 422
    stage = pipeline["stages"][0][0]["id"]
    assert (
        post(pipeline_id=pipeline["id"], stage_id=stage, action_id=other["stages"][0][1]["id"])
        == 422
    )


def test_creating_and_starting_are_two_calls(api: TestClient) -> None:
    pipeline = _pipeline(api, stages=1)
    created = _create(api, title="Item", pipeline_id=pipeline["id"])
    assert api.get(f"/api/v1/artifacts/{created['number']}/run").status_code == 404  # never started
    started = api.post(f"/api/v1/artifacts/{created['number']}/run")  # the artifact's own pipeline
    assert started.status_code == 201, started.text
    assert (started.json()["started_by"], started.json()["root_pipeline_id"]) == (
        "system",
        pipeline["id"],
    )
    for _ in range(100):
        run = api.get(f"/api/v1/artifacts/{created['number']}/run").json()
        if run["status"] == "done":
            break
        time.sleep(0.05)
    assert run["status"] == "done"


def test_starting_without_a_pipeline_is_refused(api: TestClient) -> None:
    created = _create(api, title="Item")
    assert api.post(f"/api/v1/artifacts/{created['number']}/run").status_code == 422


def test_the_pipelines_list_gives_the_ids_to_start_with(api: TestClient) -> None:
    pipeline = _pipeline(api, stages=2)
    listed = api.get("/api/v1/pipelines").json()
    mine = next(p for p in listed if p["id"] == pipeline["id"])
    assert [s["name"] for s in mine["stages"]] == ["Stage 1", "Stage 2"]
    assert mine["stages"][0]["actions"][0]["id"] == pipeline["stages"][0][1]["id"]


def test_changing_the_target_of_an_artifact(api: TestClient) -> None:
    pipeline = _pipeline(api, stages=2)
    created = _create(api, title="Item")
    url = f"/api/v1/artifacts/{created['number']}"
    second = pipeline["stages"][1][0]
    changed = api.patch(url, json={"pipeline_id": pipeline["id"], "stage_id": second["id"]}).json()
    assert (changed["pipeline_id"], changed["stage_id"]) == (pipeline["id"], second["id"])
    cleared = api.patch(url, json={"pipeline_id": None}).json()
    assert (cleared["pipeline_id"], cleared["stage_id"], cleared["action_id"]) == (None, None, None)


# ── MCP ───────────────────────────────────────────────────────────────


def _mcp(
    api: TestClient, method: str, params: dict[str, Any] | None = None, call_id: int = 1
) -> Any:
    response = api.post(
        "/mcp",
        headers=MCP_HEADERS,
        json={"jsonrpc": "2.0", "id": call_id, "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _tool(api: TestClient, name: str, **arguments: Any) -> dict[str, Any]:
    body = _mcp(api, "tools/call", {"name": name, "arguments": arguments})
    return body["result"]  # type: ignore[no-any-return]


def test_mcp_lists_its_tools(api: TestClient) -> None:
    _mcp(
        api,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "t", "version": "1"},
        },
    )
    names = {t["name"] for t in _mcp(api, "tools/list")["result"]["tools"]}
    assert {
        "list_pipelines",
        "create_artifact",
        "get_artifact",
        "list_artifacts",
        "update_artifact",
        "start_processing",
        "stop_processing",
        "get_processing_status",
    } <= names


def test_an_agent_creates_an_artifact_by_names_and_numbers(api: TestClient) -> None:
    pipeline = _pipeline(api, stages=2)
    parent = _create(api, title="Epic")
    result = _tool(
        api,
        "create_artifact",
        title="By agent",
        parent=f"#{parent['number']}",
        pipeline="Flow",
        stage="Stage 2",
    )
    assert not result.get("isError"), result
    made = api.get("/api/v1/artifacts/2").json()
    assert (made["created_by"], made["parent_id"]) == ("mcp", parent["id"])
    assert (made["pipeline_id"], made["stage_id"]) == (
        pipeline["id"],
        pipeline["stages"][1][0]["id"],
    )


def test_an_agent_gets_a_helpful_error_for_an_unknown_name(api: TestClient) -> None:
    _pipeline(api)
    result = _tool(api, "create_artifact", title="x", pipeline="Nope")
    assert result["isError"] is True
    assert "Available: Flow" in str(result["content"])
    assert api.get("/api/v1/artifacts").json() == []


def test_an_agent_follows_an_artifact(api: TestClient) -> None:
    pipeline = _pipeline(api, stages=1)
    _tool(api, "create_artifact", title="Item", pipeline="Flow")
    assert "never processed" in str(_tool(api, "get_processing_status", artifact="1")["content"])
    started = _tool(api, "start_processing", artifact="1")
    assert not started.get("isError"), started
    for _ in range(100):
        status = str(_tool(api, "get_processing_status", artifact="1")["content"])
        if '"status": "done"' in status or "'status': 'done'" in status or "done" in status:
            break
        time.sleep(0.05)
    assert pipeline["id"] in status
