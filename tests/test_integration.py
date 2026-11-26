"""The integration API (/api/v1) and the MCP server: creating artifacts completely, and following them."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.engine.runner import RunEngine
from openartifact.models import StartedBy
from tests.helpers import build_pipeline, slow_pipeline, wait_for_run, wait_until

TOKEN = "integration-token-" + "x" * 20
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
    pipeline = build_pipeline(api, stages=2)
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
    pipeline, other = build_pipeline(api), build_pipeline(api)

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
    pipeline = build_pipeline(api, stages=1)
    created = _create(api, title="Item", pipeline_id=pipeline["id"])
    assert api.get(f"/api/v1/artifacts/{created['number']}/run").status_code == 404  # never started
    started = api.post(f"/api/v1/artifacts/{created['number']}/run")  # the artifact's own pipeline
    assert started.status_code == 201, started.text
    assert (started.json()["started_by"], started.json()["root_pipeline_id"]) == (
        "api",
        pipeline["id"],
    )
    run = wait_until(
        lambda: api.get(f"/api/v1/artifacts/{created['number']}/run").json(),
        lambda run: run["status"] != "running",
    )
    assert run["status"] == "done"


def test_starting_without_a_pipeline_is_refused(api: TestClient) -> None:
    created = _create(api, title="Item")
    assert api.post(f"/api/v1/artifacts/{created['number']}/run").status_code == 422


def test_the_pipelines_list_gives_the_ids_to_start_with(api: TestClient) -> None:
    pipeline = build_pipeline(api, stages=2)
    listed = api.get("/api/v1/pipelines").json()
    mine = next(p for p in listed if p["id"] == pipeline["id"])
    assert [s["name"] for s in mine["stages"]] == ["Stage 1", "Stage 2"]
    assert mine["stages"][0]["actions"][0]["id"] == pipeline["stages"][0][1]["id"]


def test_changing_the_target_of_an_artifact(api: TestClient) -> None:
    pipeline = build_pipeline(api, stages=2)
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
        "get_processing_results",
    } <= names


def test_an_agent_creates_an_artifact_by_names_and_numbers(api: TestClient) -> None:
    pipeline = build_pipeline(api, stages=2)
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
    build_pipeline(api)
    result = _tool(api, "create_artifact", title="x", pipeline="Nope")
    assert result["isError"] is True
    assert "Available: Flow" in str(result["content"])
    assert api.get("/api/v1/artifacts").json() == []


def _content(result: dict[str, Any]) -> Any:
    """What a tool returned, as data."""
    if "structuredContent" in result:
        data = result["structuredContent"]
        return data["result"] if list(data) == ["result"] else data  # a list comes wrapped
    return json.loads(result["content"][0]["text"])


def _text(result: dict[str, Any]) -> str:
    return " ".join(part.get("text", "") for part in result["content"])


def test_an_agent_follows_an_artifact(api: TestClient) -> None:
    pipeline = build_pipeline(api, stages=1)
    _tool(api, "create_artifact", title="Item", pipeline="Flow")
    assert _content(_tool(api, "get_processing_status", artifact="1")) == {
        "status": "never processed"
    }
    started = _tool(api, "start_processing", artifact="1")
    assert not started.get("isError"), started
    status = wait_until(
        lambda: _content(_tool(api, "get_processing_status", artifact="1")),
        lambda run: run["status"] != "running",
    )
    assert status["status"] == "done"
    assert status["root_pipeline_id"] == pipeline["id"]
    assert [s["status"] for s in status["stages"]] == ["passed"]
    assert status["started_by"] == "mcp"


def test_an_agent_lists_pipelines_and_artifacts_and_reads_one(api: TestClient) -> None:
    pipeline = build_pipeline(api, stages=2)
    first = _create(api, title="First", status="backlog")
    _create(api, title="Second", status="in_progress")

    pipelines = _content(_tool(api, "list_pipelines"))
    mine = next(p for p in pipelines if p["id"] == pipeline["id"])
    assert [s["name"] for s in mine["stages"]] == ["Stage 1", "Stage 2"]

    assert len(_content(_tool(api, "list_artifacts"))) == 2
    in_progress = _content(_tool(api, "list_artifacts", lane="in_progress"))
    assert [a["title"] for a in in_progress] == ["Second"]
    assert _content(_tool(api, "list_artifacts", lane="done")) == []

    assert _content(_tool(api, "get_artifact", artifact="#1"))["id"] == first["id"]
    assert _content(_tool(api, "get_artifact", artifact=first["id"]))["title"] == "First"
    missing = _tool(api, "get_artifact", artifact="#99")
    assert missing["isError"] and "not found" in _text(missing).lower()


def test_an_agent_changes_an_artifact(api: TestClient) -> None:
    _create(api, title="Old", body="text")
    renamed = _tool(api, "update_artifact", artifact="1", title="New")
    assert _content(renamed)["title"] == "New" and _content(renamed)["body"] == "text"
    moved = _tool(api, "update_artifact", artifact="#1", lane="done", body="more")
    assert (_content(moved)["status"], _content(moved)["body"]) == ("done", "more")
    assert api.get("/api/v1/artifacts/1").json()["status"] == "done"

    empty = _tool(api, "update_artifact", artifact="1")
    assert empty["isError"] and "Give a title, a body, a lane or fields" in _text(empty)
    bad_lane = _tool(api, "update_artifact", artifact="1", lane="sideways")
    assert bad_lane["isError"] and "Valid lanes: backlog, in_progress, done" in _text(bad_lane)
    assert _tool(api, "update_artifact", artifact="99", title="x")["isError"]


def test_an_agent_cannot_move_an_artifact_that_is_being_processed_but_can_stop_it(
    api: TestClient,
) -> None:
    slow_pipeline(api)
    _tool(api, "create_artifact", title="Item", pipeline="Flow")
    assert not _tool(api, "start_processing", artifact="1").get("isError")

    refused = _tool(api, "update_artifact", artifact="1", lane="done")
    assert refused["isError"] and "being processed" in _text(refused)
    assert not _tool(api, "update_artifact", artifact="1", title="Renamed").get("isError")
    again = _tool(api, "start_processing", artifact="1")
    assert again["isError"] and "being processed" in _text(again)

    stopped = _content(_tool(api, "stop_processing", artifact="1"))
    assert (stopped["status"], stopped["note"]) == ("stopped", "stopped")
    nothing = _tool(api, "stop_processing", artifact="1")
    assert nothing["isError"] and "not being processed" in _text(nothing)
    assert not _tool(api, "update_artifact", artifact="1", lane="done").get("isError")


def test_an_agent_names_stage_and_action_and_gets_errors_for_what_does_not_fit(
    api: TestClient,
) -> None:
    pipeline = build_pipeline(api, stages=2)
    stage, action = pipeline["stages"][1]
    made = _tool(
        api, "create_artifact", title="Exact", pipeline="flow", stage="stage 2", action="Action"
    )
    assert not made.get("isError"), made
    assert (_content(made)["stage_id"], _content(made)["action_id"]) == (stage["id"], action["id"])

    for arguments, message in [
        ({"stage": "Stage 1"}, "needs a pipeline"),
        ({"pipeline": "Flow", "action": "Action"}, "needs its stage"),
        (
            {"pipeline": "Flow", "stage": "Nope"},
            "Unknown stage 'Nope'. Available: Stage 1, Stage 2",
        ),
        ({"pipeline": "Flow", "stage": "Stage 1", "action": "Nope"}, "Unknown action"),
        ({"lane": "sideways"}, "Unknown lane 'sideways'"),
        ({"parent": "#99"}, "not found"),
    ]:
        result = _tool(api, "create_artifact", title="x", **arguments)
        assert result["isError"] is True and message in _text(result), (arguments, result)
    assert len(api.get("/api/v1/artifacts").json()) == 1  # none of the refused calls made one


# ── the integration API v1 ────────────────────────────────────────────


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_an_unknown_artifact_is_a_404_everywhere(api: TestClient, method: str) -> None:
    body = {"json": {"title": "x"}} if method == "patch" else {}
    for ref in ("99", "nope"):
        response = getattr(api, method)(f"/api/v1/artifacts/{ref}", **body)
        assert response.status_code == 404, (method, ref)
    assert api.get("/api/v1/artifacts/99/run").status_code == 404
    assert api.post("/api/v1/artifacts/99/run").status_code == 404
    assert api.post("/api/v1/artifacts/99/run/stop").status_code == 404


def test_a_running_artifact_over_v1_is_locked_stoppable_and_then_deletable(
    api: TestClient,
) -> None:
    pipeline = slow_pipeline(api)
    created = _create(api, title="Item", pipeline_id=pipeline["id"])
    url = f"/api/v1/artifacts/{created['number']}"
    assert api.post(f"{url}/run").status_code == 201

    assert api.patch(url, json={"status": "done"}).status_code == 409
    assert api.delete(url).status_code == 409
    assert api.post(f"{url}/run").status_code == 409  # already being processed
    assert api.patch(url, json={"title": "Renamed"}).json()["title"] == "Renamed"

    stopped = api.post(f"{url}/run/stop")
    assert stopped.status_code == 200 and stopped.json()["status"] == "stopped"
    assert api.post(f"{url}/run/stop").status_code == 409
    assert api.delete(url).status_code == 204
    assert api.get(url).status_code == 404


def test_a_pipeline_that_does_not_exist_is_a_422_on_update(api: TestClient) -> None:
    created = _create(api, title="Item")
    url = f"/api/v1/artifacts/{created['number']}"
    assert api.patch(url, json={"pipeline_id": "nope"}).status_code == 422
    assert api.patch(url, json={"stage_id": "nope"}).status_code == 422


def test_the_v1_run_can_name_its_own_stage(api: TestClient) -> None:
    pipeline = build_pipeline(api, stages=2)
    created = _create(api, title="Item")
    second = pipeline["stages"][1][0]
    body = {"pipeline_id": pipeline["id"], "stage_id": second["id"]}
    assert api.post(f"/api/v1/artifacts/{created['number']}/run", json=body).status_code == 201
    run = wait_for_run(api, created, "done")
    assert [s["status"] for s in run["stages"]] == ["skipped", "passed"]


def test_the_integration_api_and_mcp_refuse_a_wrong_or_missing_token(api: TestClient) -> None:
    bare = TestClient(api.app)  # the application of ``api``, without its default header
    accept = {"Accept": MCP_HEADERS["Accept"]}
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {TOKEN}"}):
        assert bare.get("/api/v1/artifacts", headers=headers).status_code == 401
        assert bare.post("/mcp", headers={**accept, **headers}, json={}).status_code == 401
    assert bare.get("/api/v1/artifacts", headers=HEADERS).status_code == 200


def test_every_interface_starts_a_run_through_the_one_engine_path(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Browser API, integration API and MCP all end in ``RunEngine.start`` and differ only in who started."""
    pipeline = build_pipeline(api, stages=1)
    calls: list[tuple[str, str]] = []
    original = RunEngine.start

    async def spy(self: RunEngine, task_id: str, *args: Any, **kwargs: Any) -> Any:
        started_by = kwargs.get("started_by") or (args[3] if len(args) > 3 else StartedBy.USER)
        calls.append((task_id, str(started_by.value)))
        return await original(self, task_id, *args, **kwargs)

    monkeypatch.setattr(RunEngine, "start", spy)
    tasks = [_create(api, title=f"Item {i}", pipeline_id=pipeline["id"]) for i in range(3)]

    assert api.post(f"/api/tasks/{tasks[0]['id']}/run", json={}).status_code == 201
    assert api.post(f"/api/v1/artifacts/{tasks[1]['number']}/run").status_code == 201
    assert not _tool(api, "start_processing", artifact=str(tasks[2]["number"])).get("isError")

    assert calls == [
        (tasks[0]["id"], "user"),
        (tasks[1]["id"], "api"),
        (tasks[2]["id"], "mcp"),
    ]
    for task in tasks:
        wait_for_run(api, task, "done")


# ── runs that never happened, secrets, the event stream ───────────────


def test_the_results_of_an_artifact_that_was_never_processed_are_404(api: TestClient) -> None:
    created = _create(api, title="Idle")
    for ref in (created["id"], created["number"]):
        response = api.get(f"/api/v1/artifacts/{ref}/run/results")
        assert (response.status_code, response.json()["detail"]) == (
            404,
            "The artifact was never processed",
        )
    assert api.get("/api/v1/artifacts/nope/run/results").json()["detail"] == "Artifact not found"


def test_putting_a_secret_twice_creates_then_replaces_and_never_returns_the_value(
    api: TestClient,
) -> None:
    first = api.put("/api/v1/secrets/TOKEN_A", json={"value": "first-value"})
    second = api.put("/api/v1/secrets/TOKEN_A", json={"value": "second-value"})
    assert (first.status_code, second.status_code) == (201, 200)
    for response in (first, second):
        assert set(response.json()) == {"name", "created_at", "updated_at"}
        assert "value" not in response.text
    assert first.json()["created_at"] == second.json()["created_at"]
    assert [s["name"] for s in api.get("/api/v1/secrets").json()] == ["TOKEN_A"]


def test_the_event_stream_answers_as_text_event_stream_and_starts_with_a_retry_frame(
    api: TestClient,
) -> None:
    """Read the real endpoint through the ASGI interface: the stream never ends, so stop it after a frame."""
    sent: list[dict[str, Any]] = []
    first_frame = threading.Event()
    stop: list[asyncio.Event] = []

    async def make_stop() -> None:
        stop.append(asyncio.Event())

    async def consume() -> None:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/events",
            "raw_path": b"/api/events",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"authorization", HEADERS["Authorization"].encode()),
            ],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 80),
        }

        async def receive() -> dict[str, Any]:
            await stop[0].wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)
            if message["type"] == "http.response.body" and message.get("body"):
                first_frame.set()

        await api.app(scope, receive, send)  # type: ignore[arg-type]

    assert api.portal is not None
    api.portal.call(make_stop)
    done = api.portal.start_task_soon(consume)
    assert first_frame.wait(10)
    created = _create(api, title="Seen")
    wait_until(lambda: b"task.created" in b"".join(m.get("body", b"") for m in sent), bool)
    api.portal.call(stop[0].set)
    done.result(10)

    start = sent[0]
    assert start["status"] == 200
    headers = {k.decode(): v.decode() for k, v in start["headers"]}
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["cache-control"] == "no-cache"
    body = b"".join(m.get("body", b"") for m in sent).decode()
    assert body.startswith("retry:")
    assert f'"id":"{created["id"]}"' in body


def test_the_mcp_read_carries_the_original_the_fields_and_the_filled_in_text(
    api: TestClient,
) -> None:
    api.put(
        "/api/artifact-fields", json={"fields": [{"name": "test", "label": "Test", "kind": "text"}]}
    ).raise_for_status()
    made = _create(
        api,
        title="Der letzte Leuchtturm",
        body="${card.test} / ${card.title}",
        fields={"test": "v"},
    )
    got = _content(_tool(api, "get_artifact", artifact=f"#{made['number']}"))
    assert got["body"] == "${card.test} / ${card.title}" and got["fields"]["test"] == "v"
    assert got["body_resolved"] == "v / Der letzte Leuchtturm"
