"""The execution history: one execution per start, retention, the browser and integration APIs, MCP, migration."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.engine import history as history_module
from openartifact.engine.history import Changes, ExecutionHistory
from openartifact.events import EventBus
from openartifact.models import Execution, Task
from tests.helpers import (
    alembic_config,
    build_definition,
    build_pipeline,
    db_session_context,
    link,
    make_task,
    post,
    slow_pipeline,
    wait_for_run,
)
from tests.test_execution_nodes import _definition, _start, _use

TOKEN = "history-token-" + "x" * 20
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
MCP_HEADERS = {**HEADERS, "Accept": "application/json, text/event-stream"}


def _executions(client: TestClient, task: dict[str, Any], **query: Any) -> dict[str, Any]:
    response = client.get(f"/api/tasks/{task['id']}/executions", params=query)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def _run(client: TestClient, pipeline: dict[str, Any], task: dict[str, Any], status: str) -> None:
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(client, task, status)


def _failing_pipeline(client: TestClient) -> dict[str, Any]:
    """A pipeline whose action runs a definition that ends in On Fail: the run fails."""
    pipeline = build_pipeline(client, stages=1)
    definition = build_definition(client, "Fails", output="fail", fail_enabled=True)
    link(client, pipeline, pipeline["stages"][0][1], definition)
    return pipeline


# ── one execution per start ──────────────────────────────────────────


def test_every_start_makes_an_execution_and_a_restart_keeps_the_old_steps(
    client: TestClient,
) -> None:
    pipeline = build_pipeline(client, stages=1)
    link(client, pipeline, pipeline["stages"][0][1], build_definition(client, "Pass"))
    task = make_task(client)
    _run(client, pipeline, task, "done")
    first = _executions(client, task)["items"][0]
    first_steps = client.get(f"/api/tasks/{task['id']}/executions/{first['id']}").json()["steps"]
    assert first_steps and [s["seq"] for s in first_steps] == list(range(1, len(first_steps) + 1))

    _run(client, pipeline, task, "done")  # the restart
    listed = _executions(client, task)
    assert [e["number"] for e in listed["items"]] == [2, 1]
    assert listed["total"] == 2
    again = client.get(f"/api/tasks/{task['id']}/executions/{first['id']}").json()
    assert [s["id"] for s in again["steps"]] == [s["id"] for s in first_steps]
    newest = client.get(f"/api/tasks/{task['id']}/executions/{listed['items'][0]['id']}").json()
    assert [s["seq"] for s in newest["steps"]] == list(range(1, len(newest["steps"]) + 1))
    assert {s["id"] for s in newest["steps"]}.isdisjoint(s["id"] for s in first_steps)
    # the run endpoints still describe the current run only
    run = client.get("/api/runs").json()[0]
    assert (run["execution_id"], run["execution_number"]) == (listed["items"][0]["id"], 2)
    assert len(client.get(f"/api/runs/{task['id']}/results").json()) == len(newest["steps"])


def test_the_summary_says_where_it_started_and_how_it_ended(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=2)
    task = make_task(client)
    second = pipeline["stages"][1]
    post(
        client,
        f"/api/tasks/{task['id']}/run",
        pipeline_id=pipeline["id"],
        stage_id=second[0]["id"],
    )
    wait_for_run(client, task, "done")
    item = _executions(client, task)["items"][0]
    assert (item["number"], item["status"], item["note"]) == (1, "done", None)
    assert (item["pipeline_name"], item["pipeline_id"]) == ("Flow", pipeline["id"])
    assert (item["started_stage_name"], item["started_stage_id"]) == ("Stage 2", second[0]["id"])
    assert item["started_action_id"] == second[1]["id"]
    assert item["final_stage_name"] == "Stage 2"
    assert item["started_by"] == "user"
    assert item["started_at"].endswith("Z") and item["finished_at"].endswith("Z")
    assert item["duration_seconds"] >= 0
    assert "steps" not in item and "snapshot" not in item


def test_status_transitions_done_failed_and_stopped(client: TestClient) -> None:
    ok = build_pipeline(client, stages=1, name="Ok")
    bad = _failing_pipeline(client)
    slow = slow_pipeline(client, seconds=30)
    for pipeline, status in ((ok, "done"), (bad, "failed")):
        task = make_task(client)
        _run(client, pipeline, task, status)
        item = _executions(client, task)["items"][0]
        assert item["status"] == status and item["finished_at"] is not None
        assert (item["note"] is not None) == (status == "failed")
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=slow["id"])
    wait_for_run(client, task, "running")
    running = _executions(client, task)["items"][0]
    assert (running["status"], running["finished_at"], running["duration_seconds"]) == (
        "running",
        None,
        None,
    )
    client.post(f"/api/tasks/{task['id']}/run/stop")
    stopped = _executions(client, task)["items"][0]
    assert (stopped["status"], stopped["note"]) == ("stopped", "stopped")
    assert stopped["finished_at"] is not None


def test_recover_closes_running_executions_as_interrupted(migrated_settings: Settings) -> None:
    path = migrated_settings.data_dir / migrated_settings.database_filename
    with TestClient(_create_app(migrated_settings)) as client:
        pipeline = build_pipeline(client, stages=1)
        task = make_task(client)
        _run(client, pipeline, task, "done")
        _run(client, pipeline, task, "done")
    with sqlite3.connect(path) as conn:  # what a hard crash leaves behind
        conn.execute("UPDATE pipeline_runs SET status = 'running'")
        conn.execute(
            "UPDATE executions SET status = 'running', finished_at = NULL WHERE number = 2"
        )
        conn.execute(
            "UPDATE executions SET status = 'running', finished_at = NULL WHERE number = 1"
        )  # no run points to this one any more
    with TestClient(_create_app(migrated_settings)) as client:
        items = _executions(client, task)["items"]
        assert [(e["number"], e["status"], e["note"]) for e in items] == [
            (2, "stopped", "interrupted"),
            (1, "stopped", "interrupted"),
        ]
        assert all(e["finished_at"] for e in items)
        assert client.get("/api/runs").json()[0]["status"] == "stopped"


def test_numbers_are_never_reused_after_a_delete(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1)
    task = make_task(client)
    _run(client, pipeline, task, "done")
    _run(client, pipeline, task, "done")
    for item in _executions(client, task)["items"]:
        assert client.delete(f"/api/tasks/{task['id']}/executions/{item['id']}").status_code == 204
    assert _executions(client, task)["total"] == 0
    _run(client, pipeline, task, "done")
    assert [e["number"] for e in _executions(client, task)["items"]] == [3]
    assert client.get("/api/runs").json()[0]["execution_number"] == 3


# ── the browser API ──────────────────────────────────────────────────


def test_list_limit_total_policy_and_errors(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1)
    task = make_task(client)
    for _ in range(3):
        _run(client, pipeline, task, "done")
    listed = _executions(client, task, limit=2)
    assert [e["number"] for e in listed["items"]] == [3, 2]
    assert listed["total"] == 3
    assert listed["policy"] == {"keep_last": None, "keep_hours": None, "effective_default_keep": 50}
    assert client.get(f"/api/tasks/{task['number']}/executions").json()["total"] == 3
    for bad in (0, 501, "x"):
        assert client.get(f"/api/tasks/{task['id']}/executions?limit={bad}").status_code == 422
    assert client.get("/api/tasks/nope/executions").status_code == 404
    assert client.get(f"/api/tasks/{task['id']}/executions/nope").status_code == 404


def test_detail_has_the_steps_with_names_and_is_scoped_to_the_artifact(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1)
    link(client, pipeline, pipeline["stages"][0][1], build_definition(client, "Pass"))
    task, other = make_task(client), make_task(client, "Other")
    _run(client, pipeline, task, "done")
    item = _executions(client, task)["items"][0]
    detail = client.get(f"/api/tasks/{task['id']}/executions/{item['id']}").json()
    assert {k: detail[k] for k in item} == item
    kinds = [s["kind"] for s in detail["steps"]]
    assert kinds[0] == "trigger" and kinds[-1] == "output"
    step = detail["steps"][0]
    assert (step["stage_name"], step["seq"]) == ("Stage 1", 1)
    assert {"node_name", "outcome", "port", "exit_code", "reason", "data", "output"} <= set(step)
    assert step["started_at"].endswith("Z")
    # another artifact cannot reach it
    assert client.get(f"/api/tasks/{other['id']}/executions/{item['id']}").status_code == 404
    assert client.delete(f"/api/tasks/{other['id']}/executions/{item['id']}").status_code == 404


def test_delete_one_clear_and_the_refusal_while_running(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    pipeline = build_pipeline(client, stages=1)
    slow = slow_pipeline(client, seconds=30)
    task = make_task(client)
    for _ in range(3):
        _run(client, pipeline, task, "done")
    items = _executions(client, task)["items"]
    published.clear()
    assert client.delete(f"/api/tasks/{task['id']}/executions/{items[1]['id']}").status_code == 204
    assert ("execution.deleted", {"task_id": task["id"], "id": items[1]["id"]}) in published
    assert client.get(f"/api/tasks/{task['id']}/executions/{items[1]['id']}").status_code == 404
    assert client.delete(f"/api/tasks/{task['id']}/executions/{items[1]['id']}").status_code == 404

    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=slow["id"])
    wait_for_run(client, task, "running")
    running = _executions(client, task)["items"][0]
    refused = client.delete(f"/api/tasks/{task['id']}/executions/{running['id']}")
    assert refused.status_code == 409
    cleared = client.delete(f"/api/tasks/{task['id']}/executions")
    assert (cleared.status_code, cleared.json()) == (200, {"deleted": 2})
    assert [e["status"] for e in _executions(client, task)["items"]] == ["running"]
    client.post(f"/api/tasks/{task['id']}/run/stop")
    assert client.delete(f"/api/tasks/{task['id']}/executions").json() == {"deleted": 1}
    assert client.delete(f"/api/tasks/{task['id']}/executions").json() == {"deleted": 0}


def test_events_announce_creation_every_status_change_and_deletion(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    pipeline = build_pipeline(client, stages=1)
    task = make_task(client)
    _run(client, pipeline, task, "done")
    updates = [d["execution"]["status"] for t, d in published if t == "execution.updated"]
    assert updates == ["running", "done"]
    assert all(d["task_id"] == task["id"] for t, d in published if t == "execution.updated")
    slow = slow_pipeline(client, seconds=30)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=slow["id"])
    wait_for_run(client, task, "running")
    client.post(f"/api/tasks/{task['id']}/run/stop")
    updates = [d["execution"]["status"] for t, d in published if t == "execution.updated"]
    assert updates[-2:] == ["running", "stopped"]
    assert [d["execution"]["number"] for t, d in published if t == "execution.updated"] == [
        1,
        1,
        2,
        2,
    ]


def test_deleting_an_execution_deletes_its_steps_only(
    client: TestClient, migrated_settings: Settings
) -> None:
    pipeline = build_pipeline(client, stages=1)
    link(client, pipeline, pipeline["stages"][0][1], build_definition(client, "Pass"))
    task = make_task(client)
    _run(client, pipeline, task, "done")
    _run(client, pipeline, task, "done")
    old, new = (e["id"] for e in reversed(_executions(client, task)["items"]))
    path = migrated_settings.data_dir / migrated_settings.database_filename

    def steps(execution_id: str) -> int:
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                "SELECT count(*) FROM run_node_results WHERE execution_id = ?", (execution_id,)
            ).fetchone()
        return int(row[0])

    assert steps(old) > 0 and steps(new) > 0
    client.delete(f"/api/tasks/{task['id']}/executions/{old}")
    assert (steps(old), steps(new) > 0) == (0, True)
    # deleting the current one only detaches it from the run: the run itself is untouched
    client.delete(f"/api/tasks/{task['id']}/executions/{new}")
    run = client.get("/api/runs").json()[0]
    assert (run["status"], run["execution_id"], run["node_results"]) == ("done", None, [])


def test_deleting_the_artifact_deletes_its_history(
    client: TestClient, migrated_settings: Settings
) -> None:
    pipeline = build_pipeline(client, stages=1)
    link(client, pipeline, pipeline["stages"][0][1], build_definition(client, "Pass"))
    task = make_task(client)
    _run(client, pipeline, task, "done")
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    path = migrated_settings.data_dir / migrated_settings.database_filename
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM executions").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM run_node_results").fetchone() == (0,)


# ── the policy ───────────────────────────────────────────────────────


def test_policy_validation_saving_and_pruning(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1)
    task = make_task(client)
    for _ in range(4):
        _run(client, pipeline, task, "done")
    url = f"/api/tasks/{task['id']}/history-policy"
    for body in (
        {"keep_last": 0},
        {"keep_last": 1001},
        {"keep_hours": 0},
        {"keep_hours": 8761},
        {"keep_last": "5"},
        {"keep_last": True},
        {"keep_last": 1.5},
        {"keep_days": 3},
        {"keep_last": -1},
    ):
        assert client.put(url, json=body).status_code == 422, body
    assert client.put("/api/tasks/nope/history-policy", json={}).status_code == 404
    assert _executions(client, task)["total"] == 4  # nothing was changed or pruned

    saved = client.put(url, json={"keep_last": 2})
    assert saved.status_code == 200
    assert saved.json() == {
        "policy": {"keep_last": 2, "keep_hours": None, "effective_default_keep": 50},
        "deleted": 2,
    }
    listed = _executions(client, task)
    assert [e["number"] for e in listed["items"]] == [4, 3]
    assert listed["policy"]["keep_last"] == 2
    bounds = client.put(url, json={"keep_last": 1000, "keep_hours": 8760})
    assert bounds.json()["policy"] == {
        "keep_last": 1000,
        "keep_hours": 8760,
        "effective_default_keep": 50,
    }
    cleared = client.put(url, json={})  # a missing field is "no limit": the default applies again
    assert cleared.json()["policy"]["keep_last"] is None


def test_the_application_default_applies_when_no_policy_is_set(
    migrated_settings: Settings,
) -> None:
    settings = migrated_settings.model_copy(update={"execution_history_default_keep": 2})
    with TestClient(_create_app(settings)) as client:
        pipeline = build_pipeline(client, stages=1)
        task = make_task(client)
        for _ in range(4):
            _run(client, pipeline, task, "done")
        listed = _executions(client, task)
        assert [e["number"] for e in listed["items"]] == [4, 3]
        assert listed["policy"]["effective_default_keep"] == 2


def test_a_default_of_zero_keeps_everything(migrated_settings: Settings) -> None:
    settings = migrated_settings.model_copy(update={"execution_history_default_keep": 0})
    with TestClient(_create_app(settings)) as client:
        pipeline = build_pipeline(client, stages=1)
        task = make_task(client)
        for _ in range(3):
            _run(client, pipeline, task, "done")
        assert _executions(client, task)["total"] == 3


# ── retention as a truth table ───────────────────────────────────────

# (name, keep_last, keep_hours, default, [(age in hours, status)] oldest first, kept numbers)
DONE = "done"
CASES = [
    (
        "last only",
        2,
        None,
        50,
        [(100, DONE), (50, DONE), (10, DONE), (2, DONE), (0.5, DONE)],
        [4, 5],
    ),
    (
        "hours only",
        None,
        24,
        50,
        [(100, DONE), (50, DONE), (10, DONE), (2, DONE), (0.5, DONE)],
        [3, 4, 5],
    ),
    (
        "both, last is stricter",
        2,
        1000,
        50,
        [(100, DONE), (50, DONE), (10, DONE), (2, DONE), (0.5, DONE)],
        [4, 5],
    ),
    (
        "both, hours is stricter",
        4,
        24,
        50,
        [(100, DONE), (50, DONE), (10, DONE), (2, DONE), (0.5, DONE)],
        [3, 4, 5],
    ),
    (
        "both, both inside",
        10,
        1000,
        50,
        [(100, DONE), (50, DONE), (10, DONE)],
        [1, 2, 3],
    ),
    (
        "none, default acts as last",
        None,
        None,
        3,
        [(100, DONE), (50, DONE), (10, DONE), (2, DONE), (0.5, DONE)],
        [3, 4, 5],
    ),
    (
        "none, default 0 is unlimited",
        None,
        None,
        0,
        [(1000, DONE), (500, DONE), (10, DONE)],
        [1, 2, 3],
    ),
    (
        "a set policy wins over the default",
        4,
        None,
        1,
        [(100, DONE), (50, DONE), (10, DONE), (2, DONE), (0.5, DONE)],
        [2, 3, 4, 5],
    ),
    (
        "exactly on the age limit is kept",
        None,
        10,
        50,
        [(100, DONE), (10, DONE), (2, DONE)],
        [2, 3],
    ),
    (
        "running is never removed but counts toward last",
        2,
        None,
        50,
        [(100, "running"), (50, DONE), (10, DONE), (2, "running"), (0.5, DONE)],
        [1, 4, 5],
    ),
    (
        "running is never removed by age",
        None,
        1,
        50,
        [(100, "running"), (50, DONE), (0.2, DONE)],
        [1, 3],
    ),
    (
        "the newest survives a policy that would drop it",
        None,
        1,
        50,
        [(100, DONE), (50, DONE), (3, "failed")],
        [3],
    ),
]


@pytest.mark.parametrize(
    ("name", "keep_last", "keep_hours", "default", "executions", "kept"),
    CASES,
    ids=[c[0] for c in CASES],
)
async def test_retention_truth_table(
    migrated_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    keep_last: int | None,
    keep_hours: int | None,
    default: int,
    executions: list[tuple[float, str]],
    kept: list[int],
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(history_module, "utcnow", lambda: now)
    changes = Changes()
    async with db_session_context(migrated_settings) as session:
        task = Task(
            id=str(uuid.uuid4()),
            title="T",
            number=1,
            status="backlog",
            history_keep_last=keep_last,
            history_keep_hours=keep_hours,
        )
        session.add(task)
        await session.flush()
        for number, (age, status) in enumerate(executions, start=1):
            started = now - timedelta(hours=age)
            session.add(
                Execution(
                    id=str(uuid.uuid4()),
                    task_id=task.id,
                    number=number,
                    status=status,
                    started_by="user",
                    started_at=started,
                    created_at=started,
                    finished_at=None if status == "running" else started,
                )
            )
        await session.flush()
        deleted = await ExecutionHistory(EventBus(), default).prune(session, task, changes)
        await session.commit()
        left = (
            await session.scalars(
                select(Execution.number)
                .where(Execution.task_id == task.id)
                .order_by(Execution.number)
            )
        ).all()
    assert list(left) == kept
    assert deleted == len(executions) - len(kept)
    assert sum(len(ids) for ids in changes.deleted.values()) == deleted


# ── secrets in the history ───────────────────────────────────────────


@pytest.fixture
def secured(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def test_a_secret_never_reaches_the_history(secured: TestClient) -> None:
    value = "hunter2-Value-9137"
    assert secured.put("/api/secrets/PASSWORD", json={"value": value}).status_code == 201
    pipeline, task = build_pipeline(secured, stages=1), make_task(secured)
    definition = _definition(
        secured, "code", language="sh", secrets="PASSWORD", code='echo "the password is $PASSWORD"'
    )
    _use(secured, pipeline, definition)
    _start(secured, pipeline, task)
    wait_for_run(secured, task, "done")
    listed = secured.get(f"/api/tasks/{task['id']}/executions")
    detail = secured.get(f"/api/tasks/{task['id']}/executions/{listed.json()['items'][0]['id']}")
    assert value not in listed.text and value not in detail.text
    assert "***" in detail.text
    assert "the password is" in detail.text
    state = secured.app.state  # type: ignore[attr-defined]
    path = state.settings.data_dir / state.settings.database_filename
    with sqlite3.connect(path) as conn:
        assert value not in "".join(r[0] for r in conn.execute("SELECT snapshot FROM executions"))
        assert value not in "".join(
            r[0] for r in conn.execute("SELECT output FROM run_node_results")
        )


# ── integration API and MCP ──────────────────────────────────────────


def _mcp_tool(api: TestClient, name: str, **arguments: Any) -> dict[str, Any]:
    response = api.post(
        "/mcp",
        headers=MCP_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]  # type: ignore[no-any-return]


def test_the_integration_api_mirrors_the_history(secured: TestClient) -> None:
    pipeline, task = build_pipeline(secured, stages=1), make_task(secured)
    for _ in range(3):
        _run(secured, pipeline, task, "done")
    ref = task["number"]
    listed = secured.get(f"/api/v1/artifacts/{ref}/executions?limit=2").json()
    assert [e["number"] for e in listed["items"]] == [3, 2] and listed["total"] == 3
    first = listed["items"][0]
    detail = secured.get(f"/api/v1/artifacts/{ref}/executions/{first['id']}").json()
    assert detail["id"] == first["id"] and "steps" in detail
    assert secured.delete(f"/api/v1/artifacts/{ref}/executions/{first['id']}").status_code == 204
    assert secured.delete(f"/api/v1/artifacts/{ref}/executions/{first['id']}").status_code == 404
    saved = secured.put(f"/api/v1/artifacts/{ref}/history-policy", json={"keep_last": 1})
    assert saved.json()["deleted"] == 1
    assert (
        secured.put(f"/api/v1/artifacts/{ref}/history-policy", json={"keep_last": 0}).status_code
        == 422
    )
    assert secured.get(f"/api/v1/artifacts/{ref}/executions?limit=501").status_code == 422
    # the token is required
    bare = TestClient(secured.app)
    assert bare.get(f"/api/v1/artifacts/{ref}/executions").status_code == 401
    assert bare.get(f"/api/tasks/{task['id']}/executions").status_code == 401


def test_mcp_reads_the_history_and_cannot_delete(secured: TestClient) -> None:
    pipeline, task = build_pipeline(secured, stages=1), make_task(secured)
    _run(secured, pipeline, task, "done")
    _run(secured, pipeline, task, "done")
    tools = secured.post(
        "/mcp",
        headers=MCP_HEADERS,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    ).json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"list_executions", "get_execution"} <= names
    assert not {n for n in names if "delete" in n or "clear" in n or "policy" in n}
    listed = _mcp_tool(secured, "list_executions", artifact=f"#{task['number']}")
    data = listed.get("structuredContent") or json.loads(listed["content"][0]["text"])
    assert [e["number"] for e in data["items"]] == [2, 1] and data["total"] == 2
    one = _mcp_tool(
        secured, "get_execution", artifact=str(task["number"]), execution=data["items"][1]["id"]
    )
    detail = one.get("structuredContent") or json.loads(one["content"][0]["text"])
    assert detail["number"] == 1 and "steps" in detail
    assert _mcp_tool(secured, "list_executions", artifact=task["id"], limit=0)["isError"] is True
    assert (
        _mcp_tool(secured, "get_execution", artifact=task["id"], execution="nope")["isError"]
        is True
    )


# ── migration 0023 ───────────────────────────────────────────────────

SNAPSHOT = json.dumps(
    {
        "name": "Old flow",
        "nodes": [
            {"id": "s1", "label": "Build", "kind": "stage"},
            {"id": "a1", "label": "Compile", "kind": "action"},
        ],
        "edges": [],
        "pipelines": {},
        "definitions": {},
    }
)


def _seed_old_runs(path: Any) -> None:
    with sqlite3.connect(path) as conn:
        for number, status in ((1, "done"), (2, "running")):
            conn.execute(
                "INSERT INTO tasks (id, title, status, number, position, created_by, created_at, updated_at) "
                "VALUES (?, 'T', 'backlog', ?, 0, 'user', '2026-01-01', '2026-01-01')",
                (f"t{number}", number),
            )
            conn.execute(
                "INSERT INTO pipeline_runs (id, task_id, pipeline_id, status, started_by, stage_id, "
                "action_id, note, snapshot, created_at, updated_at) VALUES (?, ?, NULL, ?, 'user', "
                "'s1', 'a1', ?, ?, '2026-02-01 10:00:00', '2026-02-01 10:05:00')",
                (
                    f"r{number}",
                    f"t{number}",
                    status,
                    "boom" if status == "done" else None,
                    SNAPSHOT,
                ),
            )
        for seq in (1, 2):
            conn.execute(
                "INSERT INTO run_node_results (id, run_id, seq, depth, node_id, node_name, kind, "
                "outcome, output, started_at, finished_at) VALUES (?, 'r1', ?, 0, 'n', 'N', 'code', "
                "'pass', 'out', '2026-02-01 10:00:00', '2026-02-01 10:00:01')",
                (f"res{seq}", seq),
            )


def test_migration_0023_backfills_goes_down_and_up(
    unmigrated_settings: Settings,
) -> None:
    path = unmigrated_settings.data_dir / unmigrated_settings.database_filename
    cfg = alembic_config()
    command.upgrade(cfg, "0022")
    _seed_old_runs(path)
    command.upgrade(cfg, "head")
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT task_id, number, status, note, pipeline_name, started_stage_name, "
            "final_stage_name, final_action_name, step_count, started_at, finished_at "
            "FROM executions ORDER BY task_id"
        ).fetchall()
        assert rows == [
            ("t1", 1, "done", "boom", "Old flow", None, "Build", "Compile", 2,
             "2026-02-01 10:00:00", "2026-02-01 10:05:00"),
            ("t2", 1, "running", None, "Old flow", None, "Build", "Compile", 0,
             "2026-02-01 10:00:00", None),
        ]  # fmt: skip
        assert conn.execute(
            "SELECT r.id FROM run_node_results r JOIN executions e ON e.id = r.execution_id "
            "WHERE e.task_id = 't1'"
        ).fetchall() == [("res1",), ("res2",)]
        assert conn.execute(
            "SELECT count(*) FROM pipeline_runs p JOIN executions e ON e.id = p.execution_id "
            "AND e.task_id = p.task_id"
        ).fetchone() == (2,)
        assert conn.execute("SELECT id, execution_seq FROM tasks ORDER BY id").fetchall() == [
            ("t1", 1),
            ("t2", 1),
        ]
        assert conn.execute(
            "SELECT history_keep_last, history_keep_hours FROM tasks WHERE id = 't1'"
        ).fetchone() == (None, None)
        # a second execution of t1 has its own steps with seq starting at 1
        conn.execute(
            "INSERT INTO executions (id, task_id, number, status, started_by, created_at, "
            "started_at) VALUES ('x2', 't1', 2, 'done', 'user', '2026-03-01', '2026-03-01')"
        )
        conn.execute(
            "INSERT INTO run_node_results (id, run_id, execution_id, seq, node_id, kind, outcome, "
            "started_at, finished_at) VALUES ('new1', 'r1', 'x2', 1, 'n', 'code', 'pass', "
            "'2026-03-01', '2026-03-01')"
        )
        with pytest.raises(sqlite3.IntegrityError):  # unique per execution
            conn.execute(
                "INSERT INTO run_node_results (id, run_id, execution_id, seq, node_id, kind, "
                "outcome, started_at, finished_at) VALUES ('dup', 'r1', 'x2', 1, 'n', 'code', "
                "'pass', '2026-03-01', '2026-03-01')"
            )
        with pytest.raises(sqlite3.IntegrityError):  # the number is unique per artifact
            conn.execute(
                "INSERT INTO executions (id, task_id, number, status, started_by, created_at, "
                "started_at) VALUES ('x3', 't1', 2, 'done', 'user', '2026-03-01', '2026-03-01')"
            )
    command.downgrade(cfg, "0022")
    with sqlite3.connect(path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "executions" not in tables
        assert "execution_id" not in {
            r[1] for r in conn.execute("PRAGMA table_info(run_node_results)")
        }
        assert "execution_id" not in {
            r[1] for r in conn.execute("PRAGMA table_info(pipeline_runs)")
        }
        assert not {"history_keep_last", "execution_seq"} & {
            r[1] for r in conn.execute("PRAGMA table_info(tasks)")
        }
        # only the newest execution's steps are left: the old key (run, seq) holds again
        assert conn.execute("SELECT id FROM run_node_results").fetchall() == [("new1",)]
        assert conn.execute("SELECT id, status FROM pipeline_runs ORDER BY id").fetchall() == [
            ("r1", "done"),
            ("r2", "running"),
        ]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO run_node_results (id, run_id, seq, node_id, kind, outcome, "
                "started_at, finished_at) VALUES ('d', 'r1', 1, 'n', 'code', 'pass', '2026', '2026')"
            )
    command.upgrade(cfg, "head")
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM executions").fetchone() == (2,)
    command.check(cfg)


def test_a_migrated_database_shows_the_old_run_as_execution_one(
    unmigrated_settings: Settings,
) -> None:
    command.upgrade(alembic_config(), "0022")
    _seed_old_runs(unmigrated_settings.data_dir / unmigrated_settings.database_filename)
    command.upgrade(alembic_config(), "head")
    with TestClient(_create_app(unmigrated_settings)) as client:
        listed = client.get("/api/tasks/t1/executions").json()
        assert [(e["number"], e["status"], e["started_stage_name"]) for e in listed["items"]] == [
            (1, "done", None)
        ]
        detail = client.get(f"/api/tasks/t1/executions/{listed['items'][0]['id']}").json()
        assert [s["id"] for s in detail["steps"]] == ["res1", "res2"]
        # the run that was running when the old version stopped is closed by the recovery
        assert client.get("/api/tasks/t2/executions").json()["items"][0]["status"] == "stopped"
        run = next(r for r in client.get("/api/runs").json() if r["task_id"] == "t1")
        assert (run["execution_number"], len(run["node_results"])) == (1, 2)
