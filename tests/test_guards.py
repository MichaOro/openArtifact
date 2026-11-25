"""Guards (ADR-060) through the application: the library of definitions and their attachments, a looping stage with a
round guard and its escalation table, an interval guard that stops a stalled Code node, the heartbeat, the safety
rules, the templates, the frozen definition of a running execution and the migration of 0046's guards (0047)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import (
    alembic_config,
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
ATTACHMENTS = "/api/guard-attachments"


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


def _definition(**extra: Any) -> dict[str, Any]:
    """A guard definition of the library: fires at every entry of its scope and only records."""
    return {
        "name": "Round guard",
        "trigger": {"type": "event", "events": ["enter"]},
        "when": _group(_at_least("runs", 1)),
        "consequence": "continue",
        **extra,
    }


def _attach(
    client: TestClient,
    guard: dict[str, Any],
    pipeline: dict[str, Any],
    scope_type: str,
    scope_id: str | None,
) -> dict[str, Any]:
    return post(
        client,
        ATTACHMENTS,
        guard_id=guard["id"],
        pipeline_id=pipeline["id"],
        scope_type=scope_type,
        scope_id=scope_id,
    )


def _guard_on(
    client: TestClient,
    pipeline: dict[str, Any],
    scope_type: str,
    scope_id: str | None,
    **extra: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A definition made for this test and attached to one scope: (definition, attachment)."""
    guard = post(client, GUARDS, **_definition(**extra))
    return guard, _attach(client, guard, pipeline, scope_type, scope_id)


def _code_definition(
    client: TestClient, name: str, code: str, language: str = "sh", purpose: str = "pipeline"
) -> dict[str, Any]:
    """trigger -> code -> On Pass / On Fail. ``purpose``: ``guard`` for the action a guard runs (ADR-066)."""
    definition = post(client, "/api/actions", name=name, purpose=purpose)
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


def test_a_definition_is_created_attached_switched_off_detached_and_only_then_deleted(
    client: TestClient,
) -> None:
    pipeline, stage = _looping_pipeline(client)
    created = post(client, GUARDS, **_definition())
    assert (created["used_by"], created["attachments"], created["consequence"]) == (
        0,
        [],
        "continue",
    )
    assert created["scope_types"] == [
        "pipeline",
        "stage",
        "action",
        "definition",
        "node",
    ]  # every scope unless narrowed
    placed = _attach(client, created, pipeline, "stage", stage["id"])
    assert (placed["guard_id"], placed["name"], placed["scope_id"], placed["enabled"]) == (
        created["id"],
        "Round guard",
        stage["id"],
        True,
    )
    whole = _attach(client, created, pipeline, "pipeline", None)
    assert whole["scope_id"] == pipeline["id"]  # a pipeline guard watches its own pipeline
    [listed] = client.get(GUARDS).json()
    assert listed["used_by"] == 2 and [a["id"] for a in listed["attachments"]] == [
        placed["id"],
        whole["id"],
    ]
    assert [
        a["id"] for a in client.get(ATTACHMENTS, params={"pipeline_id": pipeline["id"]}).json()
    ] == [
        placed["id"],
        whole["id"],
    ]
    changed = client.patch(f"{GUARDS}/{created['id']}", json={"name": "Renamed"}).json()
    assert (changed["name"], changed["trigger"], changed["used_by"]) == (
        "Renamed",
        created["trigger"],
        2,
    )
    off = client.put(f"{ATTACHMENTS}/{placed['id']}/enabled", json={"enabled": False}).json()
    assert (off["enabled"], off["name"]) == (False, "Renamed")
    used = client.delete(f"{GUARDS}/{created['id']}")
    assert used.status_code == 409
    assert "attached in 2 places: detach it first" in used.text
    assert client.delete(f"{ATTACHMENTS}/{placed['id']}").status_code == 204
    assert client.delete(f"{ATTACHMENTS}/{whole['id']}").status_code == 204
    assert client.get(f"{GUARDS}/{created['id']}").json()["used_by"] == 0
    assert client.delete(f"{GUARDS}/{created['id']}").status_code == 204
    assert client.get(f"{GUARDS}/{created['id']}").status_code == 404
    gone = client.get(f"{ATTACHMENTS}/{placed['id']}")
    assert gone.status_code == 404 and "Guard attachment not found" in gone.text


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"consequence": "notify"}, "needs notifications (MVP 25, card #93)"),
        ({"consequence": "handover"}, "needs handover (MVP 27, card #95)"),
        ({"scope_types": ["guard"]}, "no guards on guards"),
        ({"scope_types": []}, "at least 1 item"),
        ({"name": "   "}, "a guard needs a name"),
        ({"name": "x" * 121}, "at most 120 characters"),
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
    response = client.post(GUARDS, json={**_definition(), **change})
    assert response.status_code == 422
    assert reason in response.text


def test_an_attachment_is_checked_against_the_pipeline_and_the_scope_types_of_its_guard(
    client: TestClient,
) -> None:
    pipeline, stage = _looping_pipeline(client)
    other = build_pipeline(client, stages=1, name="Other")
    guard = post(client, GUARDS, **_definition(scope_types=["stage"]))
    body = {"guard_id": guard["id"], "pipeline_id": pipeline["id"], "scope_type": "stage"}
    elsewhere = client.post(ATTACHMENTS, json={**body, "scope_id": other["stages"][0][0]["id"]})
    assert elsewhere.status_code == 422 and "not a stage of this pipeline" in elsewhere.text
    action = pipeline["stages"][0][1]
    not_allowed = client.post(
        ATTACHMENTS, json={**body, "scope_type": "action", "scope_id": action["id"]}
    )
    assert not_allowed.status_code == 422
    assert "The guard 'Round guard' watches a stage, not a action" in not_allowed.text
    on_a_guard = client.post(ATTACHMENTS, json={**body, "scope_type": "guard", "scope_id": "x"})
    assert on_a_guard.status_code == 422 and "no guards on guards" in on_a_guard.text
    no_pipeline = client.post(ATTACHMENTS, json={**body, "pipeline_id": "nope"})
    assert (
        no_pipeline.status_code == 404
        and "Pipeline or action definition not found" in no_pipeline.text
    )
    no_guard = client.post(ATTACHMENTS, json={**body, "guard_id": "nope", "scope_id": stage["id"]})
    assert no_guard.status_code == 404 and "Guard not found" in no_guard.text
    post(client, ATTACHMENTS, **body, scope_id=stage["id"])
    twice = client.post(ATTACHMENTS, json={**body, "scope_id": stage["id"]})
    assert twice.status_code == 409 and "attached there already" in twice.text
    narrowed = client.patch(f"{GUARDS}/{guard['id']}", json={"scope_types": ["action"]})
    assert narrowed.status_code == 422
    assert "attached to a stage: detach it there first" in narrowed.text


def test_the_interval_is_checked_against_the_settings(client: TestClient) -> None:
    interval = {"type": "interval", "every_seconds": 1}
    settings = client.app.state.guards
    settings.min_interval_seconds = 30  # the operator's minimum
    try:
        short = client.post(GUARDS, json=_definition(trigger=interval))
    finally:
        settings.min_interval_seconds = 0.2
    assert short.status_code == 422 and "at most every 30 s" in short.text


def test_an_attachment_goes_with_its_stage_and_its_actions_and_the_definition_stays(
    client: TestClient,
) -> None:
    pipeline, stage = _looping_pipeline(client)
    action = pipeline["stages"][0][1]
    guard, _ = _guard_on(client, pipeline, "stage", stage["id"])
    _attach(client, guard, pipeline, "action", action["id"])
    _attach(client, guard, pipeline, "pipeline", None)
    assert client.delete(f"{graph_url(pipeline)}/nodes/{stage['id']}").status_code == 204
    left = client.get(f"{GUARDS}/{guard['id']}").json()
    assert [a["scope_type"] for a in left["attachments"]] == ["pipeline"]


def test_run_action_without_an_action_gets_an_empty_action_definition(client: TestClient) -> None:
    guard = post(client, GUARDS, **_definition(consequence="run_action"))
    definition = client.get(f"/api/actions/{guard['action_id']}").json()
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
    body = _code_definition(client, "Judge", judge, "python", purpose="guard")
    _guard_on(
        client,
        pipeline,
        "stage",
        stage["id"],
        consequence="run_action",
        fallback="pause",
        action_id=body["id"],
        escalation=[{"from_firing": 1, "every_runs": 5}, {"from_firing": 2, "every_runs": 3}],
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
    _guard_on(
        client,
        pipeline,
        "action",
        action["id"],
        name="Stall guard",
        trigger={"type": "interval", "every_seconds": 1, "for_seconds": 0},
        when=_group(_at_least("idle", 1)),
        consequence="abort",
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
    _guard_on(
        client,
        pipeline,
        "action",
        action["id"],
        trigger={"type": "interval", "every_seconds": 1},
        when=_group(_at_least("idle", 2)),
        consequence="abort",
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
    _guard, place = _guard_on(
        client, pipeline, "stage", stage["id"], escalation=[{"from_firing": 1, "every_runs": 50}]
    )
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_until(lambda: _activity(client, task), lambda entries: len(entries) >= 1, timeout=60)
    client.put(f"{ATTACHMENTS}/{place['id']}/enabled", json={"enabled": False})
    run = wait_for_run(client, task, "failed", timeout=90)  # the loop ends at the step limit
    assert "steps" in run["note"]
    assert len(_activity(client, task)) <= 2  # at most the one in flight when it was switched off


def test_the_preview_counts_the_running_scopes_it_would_fire_on(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1, name="Slow")
    stage, action = pipeline["stages"][0]
    link(client, pipeline, action, _code_definition(client, "Sleeper", "sleep 5"))
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    guard, _ = _guard_on(client, pipeline, "stage", stage["id"], when=_group(_at_least("runs", 5)))
    fires = {
        "guard_id": guard["id"],
        "when": _group(_at_least("runs", 1)),
    }  # the condition being edited
    quiet = {"guard_id": guard["id"], "when": _group(_at_least("runs", 2))}
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
    unattached = client.post(f"{GUARDS}/preview", json={"when": fires["when"]}).json()
    assert unattached["running_scopes"] == 0  # a new guard watches nothing yet
    client.post(f"/api/tasks/{task['id']}/stop")


def test_the_templates_make_library_guards_and_the_health_guard_brings_its_judging_action(
    client: TestClient,
) -> None:
    pipeline, stage = _looping_pipeline(client)
    listed = {t["key"]: t for t in client.get(f"{GUARDS}/templates").json()}
    assert set(listed) == {"stall", "runtime", "health"}
    health = post(client, f"{GUARDS}/from-template", template="health")
    assert (health["name"], health["consequence"], health["fallback"]) == (
        "Health guard",
        "run_action",
        "pause",
    )
    assert health["scope_types"] == ["stage"] and health["used_by"] == 0
    assert health["description"] == listed["health"]["summary"]
    assert health["escalation"] == [
        {"from_firing": 1, "every_runs": 5},
        {"from_firing": 2, "every_runs": 3},
    ]
    action = client.get(f"/api/actions/{health['action_id']}").json()
    names = {n["name"] for n in action["nodes"]}
    assert {"Judge progress", "Marginal gain"} <= names
    judge = next(n for n in action["nodes"] if n["name"] == "Judge progress")
    assert '"gain"' in judge["config"]["user_prompt"]
    _attach(client, health, pipeline, "stage", stage["id"])
    wrong = client.post(
        ATTACHMENTS,
        json={
            "guard_id": health["id"],
            "pipeline_id": pipeline["id"],
            "scope_type": "action",
            "scope_id": pipeline["stages"][0][1]["id"],
        },
    )
    assert wrong.status_code == 422 and "watches a stage, not a action" in wrong.text
    stall = post(
        client,
        f"{GUARDS}/from-template",
        template="stall",
        name="Stall watch",
        description="Mein Text",
    )
    assert (stall["name"], stall["description"], stall["trigger"]["type"]) == (
        "Stall watch",
        "Mein Text",
        "interval",
    )
    missing = client.post(f"{GUARDS}/from-template", json={"template": "nope"})
    assert missing.status_code == 404 and "Guard template not found" in missing.text
    v1 = client.post("/api/v1/guards/from-template", json={"template": "runtime"})
    assert v1.status_code == 201 and v1.json()["consequence"] == "abort"


def test_a_running_execution_keeps_the_definition_it_started_with_and_the_next_one_takes_the_change(
    client: TestClient,
) -> None:
    pipeline, stage = _looping_pipeline(client)
    guard, _ = _guard_on(
        client,
        pipeline,
        "stage",
        stage["id"],
        consequence="pause",
        when=_group(_at_least("runs", 5)),
    )
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    changed = {"name": "Renamed", "when": _group(_at_least("runs", 7))}
    assert client.patch(f"{GUARDS}/{guard['id']}", json=changed).status_code == 200
    first = wait_for_run(client, task, "stopped", timeout=20)
    assert first["note"].startswith("Paused by guard Round guard fired at Stage 1: round 5")
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    second = wait_for_run(
        client, task, "stopped", where=lambda run: run["note"] != first["note"], timeout=20
    )
    assert second["note"].startswith("Paused by guard Renamed fired at Stage 1: round 7")


def test_guards_attached_to_a_pipeline_go_with_it_and_the_definition_stays(
    client: TestClient, migrated_settings: Settings
) -> None:
    pipeline, stage = _looping_pipeline(client)
    guard, _ = _guard_on(client, pipeline, "stage", stage["id"])
    assert client.delete(f"/api/pipelines/{pipeline['id']}").status_code == 204
    assert client.get(ATTACHMENTS).json() == []
    assert client.get(f"{GUARDS}/{guard['id']}").json()["used_by"] == 0
    path = migrated_settings.database_url.split("///", 1)[1]
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(executions)")}
    assert "guard_state" in columns


# ── migration 0047 ───────────────────────────────────────────────────

_GUARD_ROW = (
    "INSERT INTO guards (id, pipeline_id, name, scope_type, scope_id, trigger, condition, consequence, fallback, "
    "escalation, definition_id, enabled, created_at, updated_at) VALUES (?, 'p', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
    "'2026-11-01 10:00:00', '2026-11-02 10:00:00')"
)


def test_0047_makes_every_guard_one_definition_and_one_attachment_with_its_id_and_goes_down(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0046")
    trigger = json.dumps(
        {"type": "interval", "every_seconds": 60, "for_seconds": 0, "cooldown_seconds": 600}
    )
    when = json.dumps(_group(_at_least("idle", 900)))
    steps = json.dumps([{"from_firing": 1, "every_runs": 5}])
    with sqlite3.connect(db) as conn:
        for graph, kind in (("p", "pipeline"), ("body", "action")):
            conn.execute(
                "INSERT INTO graphs (id, name, status, kind, slug, created_at, updated_at) "
                "VALUES (?, ?, 'draft', ?, ?, '2026-11-01', '2026-11-01')",
                (graph, graph, kind, graph),
            )
        conn.execute(
            "INSERT INTO graph_nodes (id, graph_id, kind, name, x, y, fail_enabled, config, created_at, updated_at) "
            "VALUES ('s', 'p', 'stage', 'Draft', 0, 0, 0, '{}', '2026-11-01', '2026-11-01')"
        )
        conn.execute(
            _GUARD_ROW,
            ("g1", "Stall", "pipeline", "p", trigger, when, "pause", "pause", "[]", None, 1),
        )
        conn.execute(
            _GUARD_ROW,
            ("g2", "Health", "stage", "s", "{}", when, "run_action", "abort", steps, "body", 0),
        )
        conn.execute(
            _GUARD_ROW,
            ("g3", "Orphan", "action", "gone", "{}", when, "abort", "pause", "[]", None, 1),
        )
    command.upgrade(alembic_config(), "0047")
    with sqlite3.connect(db) as conn:
        definitions = conn.execute(
            "SELECT id, name, scope_types, trigger, condition, consequence, fallback, escalation, action_id "
            "FROM guard_definitions ORDER BY id"
        ).fetchall()
        attachments = conn.execute(
            "SELECT id, guard_id, pipeline_id, scope_type, scope_id, enabled FROM guard_attachments ORDER BY id"
        ).fetchall()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    everywhere = '["pipeline", "stage", "action"]'
    assert definitions == [
        ("g1", "Stall", everywhere, trigger, when, "pause", "pause", "[]", None),
        ("g2", "Health", everywhere, "{}", when, "run_action", "abort", steps, "body"),
        ("g3", "Orphan", everywhere, "{}", when, "abort", "pause", "[]", None),
    ]
    # same ids, same place, same on/off; the guard of a node that is gone watched nothing and is not attached
    assert attachments == [
        ("g1", "g1", "p", "pipeline", "p", 1),
        ("g2", "g2", "p", "stage", "s", 0),
    ]
    assert "guards" not in tables
    command.downgrade(alembic_config(), "0046")
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT id, pipeline_id, name, scope_type, scope_id, consequence, fallback, escalation, definition_id, "
            "enabled FROM guards ORDER BY id"
        ).fetchall()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert rows == [
        ("g1", "p", "Stall", "pipeline", "p", "pause", "pause", "[]", None, 1),
        ("g2", "p", "Health", "stage", "s", "run_action", "abort", steps, "body", 0),
    ]
    assert not {"guard_definitions", "guard_attachments"} & tables
    command.upgrade(alembic_config(), "head")


# ── guards on an action definition and on its nodes (0049) ───────────


def _attach_to(
    client: TestClient,
    guard: dict[str, Any],
    holder: dict[str, Any],
    scope_type: str,
    scope_id: str | None,
) -> Any:
    return client.post(
        ATTACHMENTS,
        json={
            "guard_id": guard["id"],
            "graph_id": holder["id"],
            "scope_type": scope_type,
            "scope_id": scope_id,
        },
    )


def test_a_guard_is_attached_to_an_action_definition_and_to_a_node_of_it_and_refused_elsewhere(
    client: TestClient,
) -> None:
    action = _code_definition(client, "Summarise", "echo ok")
    code = kind_of(client, action, "code")
    trigger = kind_of(client, action, "trigger")
    guard = post(client, GUARDS, **_definition())
    whole = _attach_to(client, guard, action, "definition", None)
    assert whole.status_code == 201, whole.text
    body = whole.json()
    assert (body["graph_id"], body["pipeline_id"], body["holder_kind"], body["scope_type"]) == (
        action["id"],
        None,
        "action",
        "definition",
    )
    assert (body["scope_id"], body["scope_name"], body["holder_name"]) == (
        action["id"],
        "Summarise",
        "Summarise",
    )
    one = _attach_to(client, guard, action, "node", code["id"])
    assert one.status_code == 201 and one.json()["scope_name"] == "Check"
    assert _attach_to(client, guard, action, "node", code["id"]).status_code == 409
    # what an action definition cannot hold, and what a node must be
    elsewhere = _attach_to(
        client, guard, action, "node", kind_of(client, build_pipeline(client, 1), "trigger")["id"]
    )
    assert elsewhere.status_code == 422 and "not a node of this action" in elsewhere.text
    for scope_type in ("stage", "action", "pipeline"):
        refused = _attach_to(client, guard, action, scope_type, None)
        assert refused.status_code == 422 and "holds definition and node scopes" in refused.text
    refused = _attach_to(client, guard, action, "node", trigger["id"])
    assert refused.status_code == 422 and "cannot watch a trigger node" in refused.text
    pipeline = build_pipeline(client, 1)
    refused = _attach_to(client, guard, pipeline, "node", pipeline["stages"][0][1]["id"])
    assert (
        refused.status_code == 422 and "holds pipeline and stage and action scopes" in refused.text
    )
    narrow = post(client, GUARDS, **_definition(name="Stage only", scope_types=["stage"]))
    refused = _attach_to(client, narrow, action, "node", code["id"])
    assert refused.status_code == 422 and "watches a stage, not a node" in refused.text
    # the list of an action definition: only what is attached in it
    listed = client.get(f"{GUARDS}?pipeline_id={action['id']}").json()
    assert [g["id"] for g in listed] == [guard["id"]] and len(listed[0]["attachments"]) == 2


def test_the_guards_inside_the_actions_of_a_pipeline_are_listed_with_it_on_request_and_go_with_their_graph(
    client: TestClient,
) -> None:
    pipeline = build_pipeline(client, stages=2, name="Two")
    (_s1, first), (_s2, second) = pipeline["stages"]
    action = _code_definition(client, "Shared", "echo ok")
    link(client, pipeline, first, action)
    link(client, pipeline, second, action)
    code = kind_of(client, action, "code")
    own = post(client, GUARDS, **_definition(name="Own"))
    inner = post(client, GUARDS, **_definition(name="Inner"))
    _attach(client, own, pipeline, "action", first["id"])
    _attach_to(client, inner, action, "definition", None)
    _attach_to(client, inner, action, "node", code["id"])
    plain = client.get(f"{ATTACHMENTS}?pipeline_id={pipeline['id']}").json()
    assert [a["name"] for a in plain] == ["Own"]
    with_inner = client.get(f"{ATTACHMENTS}?pipeline_id={pipeline['id']}&inner=true").json()
    assert sorted((a["name"], a["scope_type"], a["holder_kind"]) for a in with_inner) == [
        ("Inner", "definition", "action"),
        ("Inner", "node", "action"),
        ("Own", "action", "pipeline"),
    ]
    assert {
        g["name"] for g in client.get(f"{GUARDS}?pipeline_id={pipeline['id']}&inner=true").json()
    } == {"Own", "Inner"}
    # a node that goes takes its attachment; the action definition that goes takes the rest; the definitions stay
    assert client.delete(f"{graph_url(action)}/nodes/{code['id']}").status_code in (200, 204)
    assert [
        a["scope_type"] for a in client.get(f"{ATTACHMENTS}?pipeline_id={action['id']}").json()
    ] == ["definition"]
    link_free = client.delete(f"/api/actions/{action['id']}")
    assert link_free.status_code in (200, 204, 409)
    if link_free.status_code == 409:  # in use: unlink first, then it can go
        for stage_action in (first, second):
            client.patch(
                f"{graph_url(pipeline)}/nodes/{stage_action['id']}", json={"definition_id": None}
            )
        assert client.delete(f"/api/actions/{action['id']}").status_code in (200, 204)
    assert client.get(f"{ATTACHMENTS}?pipeline_id={action['id']}").json() == []
    assert client.get(f"{GUARDS}/{inner['id']}").status_code == 200


def test_a_node_guard_stops_a_stalled_agent_like_node_inside_an_action_and_pauses_the_run(
    client: TestClient,
) -> None:
    pipeline = build_pipeline(client, stages=1, name="Inner stall")
    _stage, work = pipeline["stages"][0]
    action = _code_definition(client, "Sleeping action", "sleep 30")
    link(client, pipeline, work, action)
    code = kind_of(client, action, "code")
    guard = post(
        client,
        GUARDS,
        **_definition(
            name="Node stall",
            trigger={"type": "interval", "every_seconds": 1, "for_seconds": 0},
            when=_group(_at_least("idle", 1)),
            consequence="pause",
        ),
    )
    assert _attach_to(client, guard, action, "node", code["id"]).status_code == 201
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = wait_for_run(client, task, "stopped", timeout=15)
    assert run["note"].startswith(
        "Paused by guard Node stall fired at node 'Check' of action 'Sleeping action': "
    )
    entry = _activity(client, task)[0]
    assert (entry["data"]["scope_type"], entry["data"]["scope_name"], entry["data"]["trigger"]) == (
        "node",
        "Check",
        "interval",
    )
    assert entry["data"]["scope_label"] == "node 'Check' of action 'Sleeping action'"
    flow = client.get(f"/api/tasks/{task['id']}/executions/{run['execution_id']}/flow").json()[
        "guards"
    ]
    scope = next(s for s in flow["scopes"].values() if s["type"] == "node")
    assert (scope["name"], scope["parent"], scope["runs"]) == ("Check", "Sleeping action", 1)


def test_a_definition_guard_counts_apart_for_one_action_used_in_two_stages(
    client: TestClient,
) -> None:
    pipeline = build_pipeline(client, stages=2, name="Shared action")
    (_s1, first), (_s2, second) = pipeline["stages"]
    action = _code_definition(client, "Shared", "echo ok")
    link(client, pipeline, first, action)
    link(client, pipeline, second, action)
    guard = post(client, GUARDS, **_definition(name="Per use", when=_group(_at_least("runs", 1))))
    assert _attach_to(client, guard, action, "definition", None).status_code == 201
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = wait_for_run(client, task, "done", timeout=15)
    entries = list(reversed(_activity(client, task)))
    # one firing per use, each its own first entry: the two stages did not share one counter
    assert [(e["data"]["scope_type"], e["data"]["facts"]["runs"]) for e in entries] == [
        ("definition", 1),
        ("definition", 1),
    ]
    flow = client.get(f"/api/tasks/{task['id']}/executions/{run['execution_id']}/flow").json()[
        "guards"
    ]
    keys = [k for k, s in flow["scopes"].items() if s["type"] == "definition"]
    assert len(keys) == 2 and keys[0] != keys[1]


def test_a_node_guard_in_a_looping_action_counts_every_entry_and_hears_pass_and_error(
    client: TestClient,
) -> None:
    pipeline, _stage = _looping_pipeline(client)
    work = next(
        n
        for n in client.get(graph_url(pipeline)).json()["nodes"]
        if n["name"] != "Check" and n["kind"] == "action"
    )
    action = _code_definition(client, "Step", "echo ok")
    link(client, pipeline, work, action)
    code = kind_of(client, action, "code")
    guard = post(
        client,
        GUARDS,
        **_definition(name="Third entry", when=_group(_at_least("runs", 3)), consequence="pause"),
    )
    assert _attach_to(client, guard, action, "node", code["id"]).status_code == 201
    passed = post(
        client,
        GUARDS,
        **_definition(
            name="Heard a pass",
            trigger={"type": "event", "events": ["pass"]},
            when=_group(_at_least("passes", 2)),
            consequence="continue",
        ),
    )
    assert _attach_to(client, passed, action, "node", code["id"]).status_code == 201
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = wait_for_run(client, task, "stopped", timeout=20)
    assert "node 'Check' of action 'Step'" in run["note"] and "round 3" in run["note"]
    by_guard = {e["actor_name"]: e["data"] for e in _activity(client, task)}
    assert by_guard["Third entry"]["facts"]["runs"] == 3
    assert (
        by_guard["Heard a pass"]["event"] == "pass"
        and by_guard["Heard a pass"]["facts"]["passes"] >= 2
    )


def test_a_node_guard_hears_an_error_whatever_the_failure_setting_does_with_it(
    client: TestClient,
) -> None:
    pipeline = build_pipeline(client, stages=1, name="Fails")
    _stage, work = pipeline["stages"][0]
    action = _code_definition(client, "Broken", "exit 3")
    link(client, pipeline, work, action)
    code = kind_of(client, action, "code")
    guard = post(
        client,
        GUARDS,
        **_definition(
            name="Saw an error",
            trigger={"type": "event", "events": ["error"]},
            when=_group(_at_least("errors", 1)),
            consequence="continue",
        ),
    )
    assert _attach_to(client, guard, action, "node", code["id"]).status_code == 201
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(client, task, "failed", timeout=15)
    entry = _activity(client, task)[0]["data"]
    assert (entry["event"], entry["scope_type"], entry["facts"]["errors"]) == ("error", "node", 1)


def test_0049_renames_the_holder_widens_what_could_watch_everything_and_goes_down(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0048")
    everywhere = '["pipeline", "stage", "action"]'
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO graphs (id, name, status, kind, slug, created_at, updated_at) "
            "VALUES ('p', 'p', 'draft', 'pipeline', 'p', '2026-11-01', '2026-11-01')"
        )
        for ident, scopes in (
            ("wide", everywhere),
            ("narrow", '["stage"]'),
            ("odd", '["pipeline", "action"]'),
        ):
            conn.execute(
                "INSERT INTO guard_definitions (id, name, description, scope_types, trigger, condition, consequence, "
                "fallback, escalation, created_at, updated_at) "
                "VALUES (?, ?, '', ?, '{}', '{}', 'pause', 'pause', '[]', '2026-11-01', '2026-11-01')",
                (ident, ident, scopes),
            )
        conn.execute(
            "INSERT INTO guard_attachments (id, guard_id, pipeline_id, scope_type, scope_id, enabled, created_at) "
            "VALUES ('a1', 'wide', 'p', 'pipeline', 'p', 1, '2026-11-01')"
        )
    command.upgrade(alembic_config(), "0049")
    with sqlite3.connect(db) as conn:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(guard_attachments)")]
        scopes = dict(conn.execute("SELECT id, scope_types FROM guard_definitions").fetchall())
        attachment = conn.execute(
            "SELECT id, graph_id, scope_type, scope_id FROM guard_attachments"
        ).fetchall()
        indexes = {r[1] for r in conn.execute("PRAGMA index_list(guard_attachments)")}
    assert "graph_id" in columns and "pipeline_id" not in columns
    assert attachment == [("a1", "p", "pipeline", "p")]
    assert (
        "ix_guard_attachments_graph_id" in indexes
        and "ix_guard_attachments_pipeline_id" not in indexes
    )
    assert json.loads(scopes["wide"]) == ["pipeline", "stage", "action", "definition", "node"]
    assert json.loads(scopes["narrow"]) == ["stage"]  # narrowed on purpose: untouched
    assert json.loads(scopes["odd"]) == ["pipeline", "action"]
    with sqlite3.connect(
        db
    ) as conn:  # attachments of the new kinds are held by an action definition
        conn.execute(
            "INSERT INTO graphs (id, name, status, kind, slug, created_at, updated_at) "
            "VALUES ('act', 'act', 'draft', 'action', 'act', '2026-11-01', '2026-11-01')"
        )
        conn.execute(
            "INSERT INTO guard_attachments (id, guard_id, graph_id, scope_type, scope_id, enabled, created_at) "
            "VALUES ('a2', 'wide', 'act', 'definition', 'act', 1, '2026-11-01')"
        )
    command.downgrade(alembic_config(), "0048")
    with sqlite3.connect(db) as conn:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(guard_attachments)")]
        kept = [r[0] for r in conn.execute("SELECT id FROM guard_attachments")]
        scopes = dict(conn.execute("SELECT id, scope_types FROM guard_definitions").fetchall())
    assert "pipeline_id" in columns and "graph_id" not in columns
    assert kept == ["a1"]  # the attachment of an action definition does not fit the old rule
    assert json.loads(scopes["wide"]) == ["pipeline", "stage", "action"]
    command.upgrade(alembic_config(), "head")


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


def test_mcp_lists_the_library_switches_an_attachment_off_and_sends_a_heartbeat(
    client: TestClient,
) -> None:
    pipeline, stage = _looping_pipeline(client)
    guard, place = _guard_on(client, pipeline, "stage", stage["id"], name="Loop watch")
    post(client, GUARDS, **_definition(name="Unused"))
    error, listed = _tool(client, "list_guards", pipeline="Loop")
    assert not error and [g["id"] for g in listed] == [guard["id"]]
    assert [a["id"] for a in listed[0]["attachments"]] == [place["id"]]
    error, everything = _tool(client, "list_guards")
    assert not error and {g["name"] for g in everything} == {"Loop watch", "Unused"}
    error, off = _tool(client, "set_guard_enabled", guard="loop watch", enabled=False)
    assert not error and (off["id"], off["enabled"]) == (place["id"], False)
    assert client.get(f"{ATTACHMENTS}/{place['id']}").json()["enabled"] is False
    _attach(client, guard, pipeline, "pipeline", None)
    error, text = _tool(client, "set_guard_enabled", guard="Loop watch", enabled=True)
    assert error and "attached in 2 places: name the attachment" in text
    error, on = _tool(client, "set_guard_enabled", guard=place["id"], enabled=True)
    assert not error and on["enabled"] is True
    error, text = _tool(client, "set_guard_enabled", guard="nope", enabled=True)
    assert error and "Unknown guard 'nope'" in text
    error, text = _tool(client, "heartbeat", execution_id="nothing")
    assert error and "Execution not found" in text
