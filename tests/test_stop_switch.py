"""The STOP switch (ADR-076): no execution starts and every running one is aborted while it is on."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.engine import stop_switch
from openartifact.engine.runner import RunEngine
from tests.helpers import build_pipeline, make_task, run_of, wait_for_run
from tests.test_execution_nodes import _definition, _start, _use
from tests.test_mcp import _call as mcp_call

TOKEN = "stop-token-" + "x" * 30
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}
RETRY_WAITING = {"enabled": True, "max_tries": 5, "wait_ms": 120_000}


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def _offer(client: TestClient, on: bool = True) -> None:
    assert client.put("/api/settings/personal", json={"show_stop_switch": on}).status_code == 200


def _stop(client: TestClient, active: bool) -> dict[str, Any]:
    response = client.put("/api/settings/stop", json={"active": active})
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def _long_run(client: TestClient, **config: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """A task running an Execute Command that would run for a minute; returns (pipeline, task)."""
    pipeline, task = build_pipeline(client, stages=1), make_task(client)
    _use(client, pipeline, _definition(client, "code", code="sleep 60", **config))
    _start(client, pipeline, task)
    wait_for_run(client, task, "running")
    return pipeline, task


# ── the state ─────────────────────────────────────────────────────────


def test_a_new_system_has_stop_off_and_the_switch_not_offered(api: TestClient) -> None:
    state = api.get("/api/settings/stop").json()
    assert state == {"active": False, "since": None, "available": False, "running": 0, "aborted": 0}
    assert api.get("/api/settings/personal").json()["show_stop_switch"] is False


def test_switching_on_needs_the_setting_and_says_which(api: TestClient) -> None:
    refused = api.put("/api/settings/stop", json={"active": True})
    assert refused.status_code == 409
    assert refused.json()["code"] == "stop_unavailable"
    assert 'switch on "Show the STOP switch"' in refused.json()["detail"]
    assert api.get("/api/settings/stop").json()["active"] is False  # nothing was switched on
    _offer(api)
    assert _stop(api, True)["active"] is True
    assert _stop(api, True)["active"] is True  # asking again changes nothing and is no error


def test_switching_off_is_always_allowed_so_a_stop_cannot_get_stuck(api: TestClient) -> None:
    _offer(api)
    _stop(api, True)
    # the setting is changed behind the back of the API (a hand-edited row): off must still work
    engine: RunEngine = api.app.state.engine  # type: ignore[attr-defined]
    sessions = engine._session

    async def hide() -> None:
        async with sessions() as session:
            from openartifact import personal_settings

            await personal_settings.save(session, {"show_stop_switch": False})
            await session.commit()

    api.portal.call(hide)  # type: ignore[union-attr]
    assert api.get("/api/settings/stop").json()["available"] is False
    assert _stop(api, False)["active"] is False


def test_the_switch_cannot_be_hidden_while_stop_is_on(api: TestClient) -> None:
    _offer(api)
    _stop(api, True)
    refused = api.put("/api/settings/personal", json={"show_stop_switch": False})
    assert refused.status_code == 409
    assert refused.json()["code"] == "stop_active"
    assert "switch STOP off before you hide the switch" in refused.json()["detail"]
    assert api.get("/api/settings/personal").json()["show_stop_switch"] is True
    _stop(api, False)
    assert api.put("/api/settings/personal", json={"show_stop_switch": False}).status_code == 200


def test_the_state_is_the_same_under_v1_and_a_change_is_published(api: TestClient) -> None:
    published: list[tuple[str, dict[str, Any]]] = []
    bus = api.app.state.event_bus  # type: ignore[attr-defined]
    original = bus.publish

    def spy(kind: str, data: dict[str, Any]) -> None:
        published.append((kind, data))
        original(kind, data)

    bus.publish = spy
    _offer(api)
    assert api.put("/api/v1/settings/stop", json={"active": True}).json()["active"] is True
    assert api.get("/api/settings/stop").json()["active"] is True
    events = [d["stop"] for t, d in published if t == "settings.changed" and "stop" in d]
    assert events[-1]["active"] is True and events[-1]["since"] is not None


def test_the_body_is_checked(api: TestClient) -> None:
    assert api.put("/api/settings/stop", json={"active": "yes"}).status_code == 422
    assert api.put("/api/settings/stop", json={}).status_code == 422


# ── no execution starts from any source ───────────────────────────────


def test_no_source_can_start_an_execution_while_stop_is_on(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    _use(api, pipeline, _definition(api, "code", code="echo hi"))
    _offer(api)
    _stop(api, True)
    body = {"pipeline_id": pipeline["id"]}

    browser = api.post(f"/api/tasks/{task['id']}/run", json=body)
    integration = api.post(f"/api/v1/artifacts/{task['id']}/run", json=body)
    for refused in (browser, integration):
        assert refused.status_code == 409
        assert refused.json() == {"detail": stop_switch.MESSAGE, "code": "stopped"}
    is_error, text = mcp_call(api, "start_processing", artifact=task["id"], pipeline=pipeline["id"])
    assert is_error is True and text.endswith(f"stopped: {stop_switch.MESSAGE}")
    # nothing was half started: no run, no execution
    assert [r for r in api.get("/api/runs").json() if r["task_id"] == task["id"]] == []
    assert api.get(f"/api/tasks/{task['id']}/executions").json()["items"] == []

    _stop(api, False)
    assert api.post(f"/api/tasks/{task['id']}/run", json=body).status_code == 201
    wait_for_run(api, task, "done")


def test_everything_but_the_execution_keeps_working(api: TestClient) -> None:
    _offer(api)
    _stop(api, True)
    task = make_task(api, "while stopped")
    assert api.patch(f"/api/tasks/{task['id']}", json={"title": "renamed"}).status_code == 200
    assert api.get("/api/tasks").status_code == 200
    assert api.post("/api/pipelines", json={"name": "Made while stopped"}).status_code == 201
    assert api.get("/api/runs").status_code == 200


# ── activation aborts what runs ───────────────────────────────────────


def test_switching_on_aborts_every_running_execution_with_its_note(api: TestClient) -> None:
    _offer(api)
    runs = [_long_run(api) for _ in range(2)]
    assert api.get("/api/settings/stop").json()["running"] == 2
    state = _stop(api, True)
    assert (state["active"], state["aborted"]) == (True, 2)
    for _, task in runs:
        run = run_of(api, task)
        assert (run["status"], run["note"]) == ("stopped", stop_switch.NOTE)
        (execution,) = api.get(f"/api/tasks/{task['id']}/executions").json()["items"]
        assert (execution["status"], execution["note"]) == ("stopped", stop_switch.NOTE)
    assert api.get("/api/settings/stop").json()["running"] == 0


def test_a_node_that_waits_between_tries_is_aborted_at_once(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    _use(api, pipeline, _definition(api, "code", code="exit 1", retry=RETRY_WAITING))
    _start(api, pipeline, task)
    wait_for_run(api, task, "running")
    time.sleep(0.5)  # the first try failed and the node now waits two minutes for the next
    _offer(api)
    began = time.monotonic()
    assert _stop(api, True)["aborted"] == 1
    assert time.monotonic() - began < 5
    assert run_of(api, task)["status"] == "stopped"


def test_a_start_that_is_on_its_way_when_the_switch_goes_on_does_not_slip_through(
    api: TestClient,
) -> None:
    pipeline = build_pipeline(api, stages=1)
    _use(api, pipeline, _definition(api, "code", code="sleep 60"))
    tasks = [make_task(api, f"racer {i}") for i in range(6)]
    _offer(api)
    engine: RunEngine = api.app.state.engine  # type: ignore[attr-defined]

    async def race() -> list[str]:
        async def start(task_id: str) -> str:
            try:
                await engine.start(task_id, pipeline["id"])
                return "started"
            except Exception as error:  # a refused start is the other good outcome
                return getattr(error, "code", None) or repr(error)

        starts = [asyncio.ensure_future(start(t["id"])) for t in tasks]
        await asyncio.sleep(0)  # the starts have begun and wait for the database
        await engine.set_stop(True)
        return list(await asyncio.gather(*starts))

    outcomes = api.portal.call(race)  # type: ignore[union-attr]
    assert set(outcomes) <= {"started", "stopped"}, outcomes
    # whatever started was aborted by the switch; nothing runs and nothing can start now
    assert api.get("/api/settings/stop").json()["running"] == 0
    assert all(r["status"] != "running" for r in api.get("/api/runs").json())
    refused = api.post(f"/api/tasks/{tasks[0]['id']}/run", json={"pipeline_id": pipeline["id"]})
    assert refused.status_code == 409 and refused.json()["code"] == "stopped"


def test_a_start_from_another_thread_while_the_switch_goes_on_is_never_left_running(
    api: TestClient,
) -> None:
    pipeline = build_pipeline(api, stages=1)
    _use(api, pipeline, _definition(api, "code", code="sleep 60"))
    tasks = [make_task(api, f"thread {i}") for i in range(4)]
    _offer(api)
    codes: list[int] = []

    def start(task: dict[str, Any]) -> None:
        codes.append(
            api.post(
                f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]}
            ).status_code
        )

    threads = [threading.Thread(target=start, args=(t,)) for t in tasks]
    for thread in threads:
        thread.start()
    _stop(api, True)
    for thread in threads:
        thread.join()
    assert set(codes) <= {201, 409}
    assert api.get("/api/settings/stop").json()["running"] == 0


# ── a restart keeps it ────────────────────────────────────────────────


def test_stop_survives_a_restart_and_a_new_system_starts_with_it_off(
    migrated_settings: Settings,
) -> None:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as first:
        pipeline, task = build_pipeline(first, stages=1), make_task(first)
        _use(first, pipeline, _definition(first, "code", code="echo hi"))
        _offer(first)
        _stop(first, True)
    with TestClient(_create_app(settings), headers=HEADERS) as second:
        state = second.get("/api/settings/stop").json()
        assert state["active"] is True and state["since"] is not None
        refused = second.post(f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]})
        assert refused.status_code == 409 and refused.json()["code"] == "stopped"
        _stop(second, False)
    with TestClient(_create_app(settings), headers=HEADERS) as third:
        assert third.get("/api/settings/stop").json()["active"] is False


# ── MCP ───────────────────────────────────────────────────────────────


def test_mcp_reads_and_sets_the_switch_under_the_same_rules(api: TestClient) -> None:
    is_error, state = mcp_call(api, "get_stop_switch")
    assert is_error is False and state["active"] is False and state["available"] is False
    is_error, text = mcp_call(api, "set_stop_switch", active=True)
    assert is_error is True and "stop_unavailable: The STOP switch is switched off" in text
    _offer(api)
    is_error, state = mcp_call(api, "set_stop_switch", active=True)
    assert is_error is False and state["active"] is True
    assert api.get("/api/settings/stop").json()["active"] is True
    is_error, state = mcp_call(api, "set_stop_switch", active=False)
    assert is_error is False and state["active"] is False
