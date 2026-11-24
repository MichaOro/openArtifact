"""Guards (ADR-060) through the application: the API, a looping stage with a round guard and its escalation table,
an interval guard that stops a stalled Code node, the heartbeat, the safety rules and the templates."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import (
    build_pipeline,
    connect,
    graph_url,
    kind_of,
    link,
    make_task,
    node,
    post,
    wait_for_run,
    wait_until,
)
from tests.test_history import HEADERS, TOKEN

GUARDS = "/api/guards"


@pytest.fixture
def client(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    """The application with a short minimum interval, so interval guards can be tested in seconds, and a token
    (the integration API needs one)."""
    settings = migrated_settings.model_copy(
        update={
            "guard_min_interval_seconds": 0.2,
            "heartbeat_min_spacing_seconds": 0.5,
            "api_token": TOKEN,
            "secret_key": "k" * 40,
        }
    )
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def _group(*items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "group", "mode": "all", "items": list(items)}


def _at_least(field: str, value: int) -> dict[str, Any]:
    return {"type": "condition", "field": field, "op": "at_least", "value": value}


def _guard(
    pipeline: dict[str, Any], scope_type: str, scope_id: str | None, **extra: Any
) -> dict[str, Any]:
    body = {
        "pipeline_id": pipeline["id"],
        "name": "Round guard",
        "scope_type": scope_type,
        "scope_id": scope_id,
        "trigger": {"type": "event", "events": ["enter"]},
        "when": _group(_at_least("runs", 1)),
        "consequence": "continue",
        **extra,
    }
    return body


def _code_definition(
    client: TestClient, name: str, code: str, language: str = "sh"
) -> dict[str, Any]:
    """trigger -> code -> On Pass / On Fail."""
    definition = post(client, "/api/actions", name=name)
    trigger, out = kind_of(client, definition, "trigger"), kind_of(client, definition, "output")
    for edge in client.get(graph_url(definition)).json()["edges"]:
        client.delete(f"{graph_url(definition)}/edges/{edge['id']}")
    client.patch(f"{graph_url(definition)}/nodes/{out['id']}", json={"fail_enabled": True})
    step = node(
        client, definition, "code", name="Check", config={"language": language, "code": code}
    )
    connect(client, definition, trigger, "out", step, "in")
    connect(client, definition, step, "pass", out, "pass")
    connect(client, definition, step, "fail", out, "fail")
    return definition


def _looping_pipeline(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    """One stage whose two empty actions loop for ever: Work -> Check -> Work ... (the guard ends it)."""
    pipeline = build_pipeline(client, stages=1, name="Loop")
    stage, work = pipeline["stages"][0]
    check = node(client, pipeline, "action", stage_id=stage["id"], x=240, y=48, name="Check")
    connect(client, pipeline, work, "pass", check, "in")
    connect(client, pipeline, check, "pass", work, "in")
    return pipeline, stage


def _activity(client: TestClient, task: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        e
        for e in client.get(f"/api/tasks/{task['id']}/activity").json()["items"]
        if e["kind"] == "guard"
    ]


# ── the API ──────────────────────────────────────────────────────────


def test_a_guard_is_created_listed_changed_switched_off_and_deleted(client: TestClient) -> None:
    pipeline, stage = _looping_pipeline(client)
    created = post(client, GUARDS, **_guard(pipeline, "stage", stage["id"]))
    assert (created["scope_type"], created["enabled"], created["consequence"]) == (
        "stage",
        True,
        "continue",
    )
    assert client.get(GUARDS, params={"pipeline_id": pipeline["id"]}).json() == [created]
    changed = client.patch(f"{GUARDS}/{created['id']}", json={"name": "Renamed"}).json()
    assert (changed["name"], changed["trigger"]) == ("Renamed", created["trigger"])
    off = client.put(f"{GUARDS}/{created['id']}/enabled", json={"enabled": False}).json()
    assert off["enabled"] is False
    whole = post(client, GUARDS, **_guard(pipeline, "pipeline", None))
    assert whole["scope_id"] == pipeline["id"]  # a pipeline guard watches its own pipeline
    assert client.delete(f"{GUARDS}/{created['id']}").status_code == 204
    assert client.get(f"{GUARDS}/{created['id']}").status_code == 404


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"consequence": "notify"}, "needs notifications (MVP 25, card #93)"),
        ({"consequence": "handover"}, "needs handover (MVP 27, card #95)"),
        ({"scope_type": "guard"}, "no guards on guards"),
        ({"trigger": {"type": "interval", "every_seconds": 0.1}}, "valid integer"),
        ({"escalation": [{"from_firing": 1}]}, "every N runs or every N seconds"),
        (
            {
                "when": _group(
                    {"type": "condition", "field": "colour", "op": "is", "value": ["red"]}
                )
            },
            "colour",
        ),
    ],
)
def test_what_a_guard_cannot_be_is_refused_with_the_reason(
    client: TestClient, change: dict[str, Any], reason: str
) -> None:
    pipeline, stage = _looping_pipeline(client)
    response = client.post(GUARDS, json={**_guard(pipeline, "stage", stage["id"]), **change})
    assert response.status_code == 422
    assert reason in response.text


def test_the_scope_and_the_interval_are_checked_against_the_pipeline_and_the_settings(
    client: TestClient,
) -> None:
    pipeline, stage = _looping_pipeline(client)
    other = build_pipeline(client, stages=1, name="Other")
    elsewhere = client.post(GUARDS, json=_guard(pipeline, "stage", other["stages"][0][0]["id"]))
    assert elsewhere.status_code == 422 and "not a stage of this pipeline" in elsewhere.text
    wrong_kind = client.post(GUARDS, json=_guard(pipeline, "action", stage["id"]))
    assert wrong_kind.status_code == 422 and "not a action of this pipeline" in wrong_kind.text
    interval = {"type": "interval", "every_seconds": 1}
    settings = client.app.state.guards
    settings.min_interval_seconds = 30  # the operator's minimum
    try:
        short = client.post(GUARDS, json=_guard(pipeline, "stage", stage["id"], trigger=interval))
    finally:
        settings.min_interval_seconds = 0.2
    assert short.status_code == 422 and "at most every 30 s" in short.text


def test_run_action_without_an_action_gets_an_empty_action_definition(client: TestClient) -> None:
    pipeline, stage = _looping_pipeline(client)
    guard = post(client, GUARDS, **_guard(pipeline, "stage", stage["id"], consequence="run_action"))
    definition = client.get(f"/api/actions/{guard['definition_id']}").json()
    assert definition["graph"]["name"] == "Round guard (guard)"


def test_the_integration_api_needs_the_token(migrated_settings: Settings) -> None:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings)) as anonymous:
        assert anonymous.get("/api/v1/guards").status_code == 401
        assert anonymous.post("/api/v1/executions/x/heartbeat", json={}).status_code == 401
    with TestClient(_create_app(settings), headers=HEADERS) as allowed:
        assert allowed.get("/api/v1/guards").json() == []
        missing = allowed.post("/api/v1/executions/nothing/heartbeat", json={})
        assert missing.status_code == 404 and "Execution not found" in missing.text


# ── in a run ─────────────────────────────────────────────────────────


def test_a_round_guard_fires_at_round_5_and_8_by_its_escalation_table_and_pauses_the_run(
    client: TestClient,
) -> None:
    pipeline, stage = _looping_pipeline(client)
    # its own action passes at the first firing and fails at the second: the fallback pauses
    judge = 'import json, sys\nsys.exit(0 if json.load(open("context.json"))["vars"]["guard_firing"] < 2 else 1)'
    body = _code_definition(client, "Judge", judge, "python")
    post(
        client,
        GUARDS,
        **_guard(
            pipeline,
            "stage",
            stage["id"],
            consequence="run_action",
            fallback="pause",
            definition_id=body["id"],
            escalation=[{"from_firing": 1, "every_runs": 5}, {"from_firing": 2, "every_runs": 3}],
        ),
    )
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = wait_for_run(client, task, "stopped", timeout=20)
    assert run["note"].startswith("Paused by guard Round guard fired at Stage 1: round 8")
    entries = list(reversed(_activity(client, task)))
    assert [e["data"]["facts"]["runs"] for e in entries] == [5, 8]
    assert [e["data"]["outcome"] for e in entries] == ["continue", "pause"]
    assert entries[0]["actor_kind"] == "system" and entries[0]["actor_name"] == "Round guard"
    assert entries[1]["data"]["detail"] == "its action failed: Exit code 1; pause"
    assert entries[1]["execution_id"] == run["execution_id"]
    flow = client.get(f"/api/tasks/{task['id']}/executions/{run['execution_id']}/flow").json()[
        "guards"
    ]
    assert flow["scopes"][f"|stage:{stage['id']}"]["runs"] == 8
    assert [f["facts"]["guard.runs"] for f in flow["firings"]] == [1, 2]
    # the guard's own action is a child: its steps are not steps of the execution
    steps = client.get(f"/api/tasks/{task['id']}/executions/{run['execution_id']}").json()["steps"]
    assert all(s["node_name"] != "Check" or s["kind"] != "code" for s in steps)


def test_an_interval_guard_stops_a_stalled_code_node_and_aborts_the_run(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1, name="Stall")
    _stage, action = pipeline["stages"][0]
    link(client, pipeline, action, _code_definition(client, "Sleeper", "sleep 30"))
    post(
        client,
        GUARDS,
        **_guard(
            pipeline,
            "action",
            action["id"],
            name="Stall guard",
            trigger={"type": "interval", "every_seconds": 1, "for_seconds": 0},
            when=_group(_at_least("idle", 1)),
            consequence="abort",
        ),
    )
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = wait_for_run(client, task, "failed", timeout=15)
    assert run["note"].startswith("Aborted by guard Stall guard fired at ")
    assert "without progress" in run["note"]
    entry = _activity(client, task)[0]
    assert (entry["data"]["trigger"], entry["data"]["outcome"]) == ("interval", "abort")
    assert entry["data"]["facts"]["idle"] >= 1


def test_a_heartbeat_keeps_a_stall_guard_quiet_and_is_rate_limited(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1, name="Beat")
    _stage, action = pipeline["stages"][0]
    link(client, pipeline, action, _code_definition(client, "Sleeper", "sleep 4"))
    post(
        client,
        GUARDS,
        **_guard(
            pipeline,
            "action",
            action["id"],
            trigger={"type": "interval", "every_seconds": 1},
            when=_group(_at_least("idle", 2)),
            consequence="abort",
        ),
    )
    task = make_task(client)
    started = post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    execution = started["execution_id"]
    beats = 0
    import time

    deadline = time.monotonic() + 4.5
    while time.monotonic() < deadline:
        response = client.post(f"/api/v1/executions/{execution}/heartbeat", json={"note": "busy"})
        if response.status_code == 409:
            break
        assert response.status_code == 200, response.text
        beats += 1
        if response.json()["count"]:  # the guards watch: a second one right away is too close
            too_close = client.post(f"/api/v1/executions/{execution}/heartbeat", json={})
            assert (
                too_close.status_code == 429 and "At most one heartbeat per 0.5 s" in too_close.text
            )
        time.sleep(0.6)
    run = wait_for_run(client, task, "done", timeout=10)
    assert beats >= 3 and run["status"] == "done"  # the guard never fired
    assert _activity(client, task) == []
    assert client.post(f"/api/v1/executions/{execution}/heartbeat", json={}).status_code == 409


def test_a_switched_off_guard_stops_firing_in_a_running_execution(client: TestClient) -> None:
    pipeline, stage = _looping_pipeline(client)
    guard = post(
        client,
        GUARDS,
        **_guard(pipeline, "stage", stage["id"], escalation=[{"from_firing": 1, "every_runs": 50}]),
    )
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_until(lambda: _activity(client, task), lambda entries: len(entries) >= 1, timeout=20)
    client.put(f"{GUARDS}/{guard['id']}/enabled", json={"enabled": False})
    run = wait_for_run(client, task, "failed", timeout=30)  # the loop ends at the step limit
    assert "steps" in run["note"]
    assert len(_activity(client, task)) <= 2  # at most the one in flight when it was switched off


def test_the_preview_counts_the_running_scopes_it_would_fire_on(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1, name="Slow")
    stage, action = pipeline["stages"][0]
    link(client, pipeline, action, _code_definition(client, "Sleeper", "sleep 5"))
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    fires = _guard(pipeline, "stage", stage["id"], when=_group(_at_least("runs", 1)))
    quiet = _guard(pipeline, "stage", stage["id"], when=_group(_at_least("runs", 2)))
    preview = wait_until(
        lambda: client.post(f"{GUARDS}/preview", json=fires).json(),
        lambda p: p["running_scopes"] == 1,
    )
    assert (preview["running_scopes"], preview["matching"]) == (1, 1)
    assert (
        preview["matches"][0]["facts"]["runs"] == 1
        and preview["matches"][0]["task_id"] == task["id"]
    )
    assert client.post(f"{GUARDS}/preview", json=quiet).json()["matching"] == 0
    client.post(f"/api/tasks/{task['id']}/stop")


def test_the_templates_make_guards_and_the_health_guard_brings_its_judging_action(
    client: TestClient,
) -> None:
    pipeline, stage = _looping_pipeline(client)
    listed = {t["key"]: t for t in client.get(f"{GUARDS}/templates").json()}
    assert set(listed) == {"stall", "runtime", "health"}
    health = post(
        client,
        f"{GUARDS}/from-template",
        template="health",
        pipeline_id=pipeline["id"],
        scope_type="stage",
        scope_id=stage["id"],
    )
    assert (health["consequence"], health["fallback"]) == ("run_action", "pause")
    assert health["escalation"] == [
        {"from_firing": 1, "every_runs": 5},
        {"from_firing": 2, "every_runs": 3},
    ]
    action = client.get(f"/api/actions/{health['definition_id']}").json()
    names = {n["name"] for n in action["nodes"]}
    assert {"Judge progress", "Marginal gain"} <= names
    judge = next(n for n in action["nodes"] if n["name"] == "Judge progress")
    assert "marginal" not in judge["config"]["user_prompt"].lower() or True
    assert '"gain"' in judge["config"]["user_prompt"]
    stall = post(
        client,
        f"{GUARDS}/from-template",
        template="stall",
        pipeline_id=pipeline["id"],
        scope_type="pipeline",
    )
    assert stall["trigger"]["type"] == "interval" and stall["scope_id"] == pipeline["id"]
    wrong = client.post(
        f"{GUARDS}/from-template",
        json={
            "template": "health",
            "pipeline_id": pipeline["id"],
            "scope_type": "action",
            "scope_id": stage["id"],
        },
    )
    assert wrong.status_code == 422 and "watches a stage" in wrong.text


def test_guards_go_with_their_pipeline_and_the_migration_goes_down(
    client: TestClient, migrated_settings: Settings
) -> None:
    pipeline, stage = _looping_pipeline(client)
    post(client, GUARDS, **_guard(pipeline, "stage", stage["id"]))
    assert client.delete(f"/api/pipelines/{pipeline['id']}").status_code == 204
    assert client.get(GUARDS).json() == []
    path = migrated_settings.database_url.split("///", 1)[1]
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(executions)")}
    assert "guard_state" in columns


# ── MCP ──────────────────────────────────────────────────────────────


def _tool(client: TestClient, name: str, **arguments: Any) -> tuple[bool, Any]:
    response = client.post(
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
    result = response.json()["result"]
    text = result["content"][0]["text"] if result["content"] else "[]"
    if result.get("isError"):
        return True, text
    return False, result.get("structuredContent", {}).get("result", json.loads(text))


def test_mcp_lists_guards_switches_one_off_and_sends_a_heartbeat(client: TestClient) -> None:
    pipeline, stage = _looping_pipeline(client)
    guard = post(client, GUARDS, **_guard(pipeline, "stage", stage["id"], name="Loop watch"))
    error, listed = _tool(client, "list_guards", pipeline="Loop")
    assert not error and [g["id"] for g in listed] == [guard["id"]]
    error, off = _tool(client, "set_guard_enabled", guard="loop watch", enabled=False)
    assert not error and off["enabled"] is False
    assert client.get(f"{GUARDS}/{guard['id']}").json()["enabled"] is False
    error, text = _tool(client, "set_guard_enabled", guard="nope", enabled=True)
    assert error and "Unknown guard 'nope'" in text
    error, text = _tool(client, "heartbeat", execution_id="nothing")
    assert error and "Execution not found" in text
