"""The activity of artifacts (ADR-058): one entry per real change, who did it, the cap, the trace of a deleted
execution, the read-only API, the MCP tool, the cascade and the migration."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.activity import recorder
from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import (
    alembic_config,
    build_pipeline,
    make_task,
    post,
    wait_for_run,
)

TOKEN = "activity-admin-token-" + "x" * 20
ADMIN = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=ADMIN) as c:
        yield c


def _activity(client: TestClient, task: dict[str, Any], base: str = "/api/tasks") -> list[Any]:
    response = client.get(f"{base}/{task['id']}/activity")
    assert response.status_code == 200, response.text
    return response.json()["items"]  # type: ignore[no-any-return]


def _kinds(client: TestClient, task: dict[str, Any]) -> list[str]:
    """The kinds recorded so far, oldest first."""
    return [e["kind"] for e in reversed(_activity(client, task))]


def _run(client: TestClient, pipeline: dict[str, Any], task: dict[str, Any]) -> None:
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(client, task, "done")


# ── what is recorded ─────────────────────────────────────────────────


def test_creating_an_artifact_records_who_created_it_and_in_which_lane(client: TestClient) -> None:
    task = make_task(client)
    [entry] = _activity(client, task)
    assert (entry["kind"], entry["actor_kind"], entry["actor_name"]) == ("created", "user", "You")
    assert entry["data"] == {"lane": "Backlog"}
    assert entry["task_id"] == task["id"]


def test_a_lane_change_records_the_titles_and_a_move_inside_the_lane_records_nothing(
    client: TestClient,
) -> None:
    first = make_task(client, "First")
    other = make_task(client, "Other")
    client.patch(f"/api/tasks/{first['id']}", json={"status": "done"})
    entry = _activity(client, first)[0]
    assert (entry["kind"], entry["data"]) == ("lane", {"from": "Backlog", "to": "Done"})
    # the same lane again, and only a new place in the lane: no new entry
    client.patch(f"/api/tasks/{first['id']}", json={"status": "done"})
    client.patch(f"/api/tasks/{other['id']}", json={"before_id": None})
    assert _kinds(client, first) == ["created", "lane"]
    assert _kinds(client, other) == ["created"]


def test_title_description_parent_and_a_field_are_each_recorded_once(client: TestClient) -> None:
    parent = make_task(client, "Parent")
    task = make_task(client, "Child")
    client.put(
        "/api/artifact-fields",
        json={"fields": [{"name": "priority", "label": "Priority", "kind": "text"}]},
    )
    response = client.patch(
        f"/api/tasks/{task['id']}",
        json={
            "title": "Child, renamed",
            "body": "a long description that must never be copied into the activity",
            "parent_id": parent["id"],
            "fields": {"priority": "high"},
        },
    )
    assert response.status_code == 200, response.text
    entries = {e["kind"]: e for e in _activity(client, task) if e["kind"] != "created"}
    assert set(entries) == {"title", "description", "parent", "field"}
    assert entries["title"]["data"] == {"from": "Child", "to": "Child, renamed"}
    assert entries["description"]["data"] == {}  # the text is never copied
    assert entries["parent"]["data"] == {"from": None, "to": "Parent"}
    assert entries["field"]["data"] == {
        "field": "priority",
        "label": "Priority",
        "from": None,
        "to": "high",
    }
    # the same values again change nothing
    client.patch(
        f"/api/tasks/{task['id']}", json={"title": "Child, renamed", "parent_id": parent["id"]}
    )
    assert len(_activity(client, task)) == 5
    client.patch(f"/api/tasks/{task['id']}", json={"parent_id": None})
    assert _activity(client, task)[0]["data"] == {"from": "Parent", "to": None}


def test_a_long_field_value_is_cut(client: TestClient) -> None:
    task = make_task(client)
    client.put(
        "/api/artifact-fields",
        json={"fields": [{"name": "notes", "label": "Notes", "kind": "text", "max_length": 500}]},
    )
    client.patch(f"/api/tasks/{task['id']}", json={"fields": {"notes": "n" * 300}})
    shown = _activity(client, task)[0]["data"]["to"]
    assert len(shown) == recorder.SHORT and shown.endswith("…")


def test_assigning_a_pipeline_a_stage_and_an_action_records_the_names(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=2)
    task = make_task(client)
    client.patch(f"/api/tasks/{task['id']}", json={"pipeline_id": pipeline["id"]})
    entry = _activity(client, task)[0]
    assert entry["kind"] == "pipeline" and entry["data"]["to"] == pipeline["name"]
    second_stage = pipeline["stages"][1][0]
    changed = client.patch(f"/api/tasks/{task['id']}", json={"stage_id": second_stage["id"]})
    assert changed.status_code == 200, changed.text
    entry = _activity(client, task)[0]
    assert entry["kind"] == "stage" and entry["data"]["pipeline"] == pipeline["name"]
    assert entry["data"]["to"] == "Stage 2"


# ── who did it ───────────────────────────────────────────────────────


def test_a_managed_token_acts_under_its_own_name_and_the_admin_token_under_the_channel(
    api: TestClient,
) -> None:
    response = api.post(
        "/api/credentials/internal", json={"type": "api_access_token", "name": "opencode"}
    )
    assert response.status_code == 201, response.text
    managed = {"Authorization": f"Bearer {response.json()['token']}"}
    created = api.post("/api/v1/artifacts", json={"title": "From outside"}, headers=managed).json()
    api.patch(f"/api/v1/artifacts/{created['id']}", json={"status": "done"}, headers=managed)
    api.patch(
        f"/api/v1/artifacts/{created['id']}", json={"title": "Admin edit"}
    )  # the environment token
    by = [
        (e["kind"], e["actor_kind"], e["actor_name"])
        for e in _activity(api, created, "/api/v1/artifacts")
    ]
    assert by == [
        ("title", "api", "api"),
        ("lane", "api", "opencode"),
        ("created", "api", "opencode"),
    ]


def test_mcp_changes_are_recorded_as_mcp_and_the_tool_lists_them(api: TestClient) -> None:
    task = api.post("/api/tasks", json={"title": "Via MCP"}).json()

    def call(name: str, **arguments: Any) -> dict[str, Any]:
        response = api.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        )
        assert response.status_code == 200, response.text
        return response.json()["result"]  # type: ignore[no-any-return]

    call("update_artifact", artifact=task["id"], title="Renamed over MCP")
    result = call("list_activity", artifact=task["id"], limit=1)
    page = result["structuredContent"]
    assert [(e["kind"], e["actor_kind"]) for e in page["items"]] == [("title", "mcp")]
    assert page["next"]
    older = call("list_activity", artifact=task["id"], before=page["next"])["structuredContent"]
    assert [e["kind"] for e in older["items"]] == ["created"]
    refused = call("list_activity", artifact=task["id"], limit=0)
    assert refused["isError"] is True


def test_an_activity_event_is_published_after_the_commit(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    task = make_task(client)
    published.clear()
    client.patch(f"/api/tasks/{task['id']}", json={"status": "done"})
    events = [data for kind, data in published if kind == "activity.created"]
    assert [(e["task_id"], e["kind"], e["data"]["to"]) for e in events] == [
        (task["id"], "lane", "Done")
    ]


# ── the cap, the cascade, the API ────────────────────────────────────


def test_the_oldest_entries_beyond_the_cap_are_removed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recorder, "MAX_PER_TASK", 5)
    task = make_task(client, "Title 0")
    for number in range(1, 9):
        client.patch(f"/api/tasks/{task['id']}", json={"title": f"Title {number}"})
    titles = [e["data"]["to"] for e in _activity(client, task)]
    assert titles == [
        f"Title {n}" for n in range(8, 3, -1)
    ]  # the newest five; "created" and the first ones are gone


def test_deleting_an_artifact_deletes_its_activity(
    client: TestClient, migrated_settings: Settings
) -> None:
    task = make_task(client)
    client.patch(f"/api/tasks/{task['id']}", json={"title": "Changed"})
    client.delete(f"/api/tasks/{task['id']}")
    with sqlite3.connect(migrated_settings.database_url.split("///", 1)[1]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM task_activity").fetchone()[0] == 0


def test_the_activity_pages_newest_first_is_read_only_and_checks_its_input(
    client: TestClient,
) -> None:
    task = make_task(client, "T0")
    for number in range(1, 6):
        client.patch(f"/api/tasks/{task['id']}", json={"title": f"T{number}"})
    url = f"/api/tasks/{task['id']}/activity"
    first = client.get(url, params={"limit": 4}).json()
    assert [e["data"].get("to") for e in first["items"]] == ["T5", "T4", "T3", "T2"]
    second = client.get(url, params={"limit": 4, "before": first["next"]}).json()
    assert [e["data"].get("to") for e in second["items"]] == ["T1", None]  # None: "created"
    assert second["next"] is None
    assert client.get(url, params={"limit": 0}).status_code == 422
    assert client.get(url, params={"limit": 201}).status_code == 422
    assert client.get(url, params={"before": "nonsense"}).status_code == 422
    assert client.get("/api/tasks/nope/activity").status_code == 404
    assert client.get(f"/api/tasks/{task['number']}/activity").status_code == 200
    for method in (client.post, client.patch, client.delete):
        assert method(url).status_code == 405


# ── the trace a deleted execution leaves ─────────────────────────────


def test_a_deleted_execution_leaves_one_slim_trace_naming_who_deleted_it_and_when(
    client: TestClient,
) -> None:
    pipeline = build_pipeline(client, stages=1)
    task = make_task(client)
    _run(client, pipeline, task)
    assert "run" not in _kinds(client, task)  # it still exists: the executions list shows it
    execution = client.get(f"/api/tasks/{task['id']}/executions").json()["items"][0]
    assert client.delete(f"/api/tasks/{task['id']}/executions/{execution['id']}").status_code == 204
    [trace] = [e for e in _activity(client, task) if e["kind"] == "run"]
    assert trace["execution_id"] == execution["id"]
    # nothing of the run is kept but its number and when it ran: it cannot be opened any more
    assert trace["data"] == {
        "number": execution["number"],
        "started_at": trace["data"]["started_at"],
    }
    assert trace["data"]["started_at"].startswith(execution["started_at"][:19])
    assert (trace["actor_kind"], trace["actor_name"]) == ("user", "You")  # who DELETED it
    assert trace["created_at"] > execution["started_at"]  # the deletion time, not the run time


def test_the_trace_names_the_token_that_deleted_through_the_integration_api(
    api: TestClient,
) -> None:
    pipeline = build_pipeline(api, stages=1)
    task = make_task(api)
    _run(api, pipeline, task)
    execution = api.get(f"/api/tasks/{task['id']}/executions").json()["items"][0]
    assert (
        api.delete(f"/api/v1/artifacts/{task['id']}/executions/{execution['id']}").status_code
        == 204
    )
    [trace] = [e for e in _activity(api, task) if e["kind"] == "run"]
    assert (trace["actor_kind"], trace["actor_name"]) == ("api", "api")  # not who started the run


def test_clearing_and_bulk_deleting_leave_one_trace_per_action_with_the_numbers(
    client: TestClient,
) -> None:
    pipeline = build_pipeline(client, stages=1)
    task = make_task(client)
    for _ in range(4):
        _run(client, pipeline, task)
    items = client.get(f"/api/tasks/{task['id']}/executions").json()["items"]
    bulk = client.post("/api/executions/delete", json={"ids": [items[0]["id"]]})
    assert bulk.status_code == 200, bulk.text
    assert client.delete(f"/api/tasks/{task['id']}/executions").json() == {"deleted": 3}
    traces = sorted(
        (e for e in _activity(client, task) if e["kind"] == "run"), key=lambda e: e["created_at"]
    )
    assert len(traces) == 2  # one per delete action, not one per execution
    assert traces[0]["data"]["number"] == 4  # the bulk delete of the newest one
    assert traces[1]["data"] == {"numbers": [1, 2, 3], "count": 3}  # clear finished
    assert traces[1]["execution_id"] is None
    assert client.get(f"/api/tasks/{task['id']}/executions").json()["total"] == 0


def test_a_trace_names_at_most_fifty_numbers_and_counts_the_rest(client: TestClient) -> None:
    from openartifact.engine.history import TRACE_NUMBERS

    assert TRACE_NUMBERS == 50  # the documented bound


def test_the_operators_guard_leaves_one_trace_naming_itself(migrated_settings: Settings) -> None:
    settings = migrated_settings.model_copy(update={"execution_history_default_keep": 1})
    with TestClient(_create_app(settings)) as client:
        pipeline = build_pipeline(client, stages=1)
        task = make_task(client)
        for _ in range(3):
            _run(client, pipeline, task)
        traces = [e for e in _activity(client, task) if e["kind"] == "run"]
        assert [(t["actor_kind"], t["actor_name"]) for t in traces] == [
            ("system", "operator guard")
        ] * len(traces)
        removed = [n for t in traces for n in (t["data"].get("numbers") or [t["data"]["number"]])]
        assert sorted(removed) == [1, 2]
        assert client.get(f"/api/tasks/{task['id']}/executions").json()["total"] == 1


def test_retention_rules_leave_one_trace_per_artifact_naming_the_rules(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1)
    task = make_task(client)
    for _ in range(3):
        _run(client, pipeline, task)
    when = {
        "type": "group",
        "mode": "all",
        "items": [{"type": "condition", "field": "status", "op": "is", "value": ["done"]}],
    }
    saved = client.put(
        "/api/settings/retention", json={"rules": [{"when": when, "action": "delete"}]}
    )
    assert saved.status_code == 200, saved.text
    traces = [e for e in _activity(client, task) if e["kind"] == "run"]
    assert len(traces) == 1
    assert (traces[0]["actor_kind"], traces[0]["actor_name"]) == ("system", "retention rule")
    assert traces[0]["data"]["count"] == saved.json()["deleted"] == 3


# ── comments in the activity ─────────────────────────────────────────


def test_a_comment_is_an_entry_with_its_id_and_never_its_text(client: TestClient) -> None:
    task = make_task(client)
    made = client.post(f"/api/tasks/{task['id']}/comments", json={"body": "a secret remark"})
    assert made.status_code == 201, made.text
    [entry] = [e for e in _activity(client, task) if e["kind"] == "comment"]
    assert entry["data"] == {"comment_id": made.json()["id"]}
    assert "secret" not in str(entry)
    assert (entry["actor_kind"], entry["actor_name"]) == ("user", "You")
    assert entry["created_at"] == made.json()["created_at"]


def test_editing_a_comment_adds_no_entry(client: TestClient) -> None:
    task = make_task(client)
    made = client.post(f"/api/tasks/{task['id']}/comments", json={"body": "one"}).json()
    before = len(_activity(client, task))
    assert (
        client.patch(
            f"/api/tasks/{task['id']}/comments/{made['id']}", json={"body": "two"}
        ).status_code
        == 200
    )
    assert len(_activity(client, task)) == before


def test_deleting_a_comment_replaces_its_entry_by_one_slim_row_of_who_deleted_it(
    api: TestClient,
) -> None:
    task = make_task(api)
    made = api.post(
        f"/api/v1/artifacts/{task['id']}/comments",
        json={"body": "to be gone", "author": "opencode"},
    ).json()
    assert [e["data"] for e in _activity(api, task) if e["kind"] == "comment"] == [
        {"comment_id": made["id"]}
    ]
    assert api.delete(f"/api/v1/artifacts/{task['id']}/comments/{made['id']}").status_code == 204
    kinds = _kinds(api, task)
    assert "comment" not in kinds  # the old entry is gone
    [gone] = [e for e in _activity(api, task) if e["kind"] == "comment_deleted"]
    assert gone["data"] == {}  # no text, no id: there is nothing left to point at
    assert (gone["actor_kind"], gone["actor_name"]) == (
        "api",
        "api",
    )  # who deleted, here the admin token
    assert "to be gone" not in str(_activity(api, task))


def test_other_comments_keep_their_entries_when_one_is_deleted(client: TestClient) -> None:
    task = make_task(client)
    keep = client.post(f"/api/tasks/{task['id']}/comments", json={"body": "keep"}).json()
    drop = client.post(f"/api/tasks/{task['id']}/comments", json={"body": "drop"}).json()
    client.delete(f"/api/tasks/{task['id']}/comments/{drop['id']}")
    assert [e["data"] for e in _activity(client, task) if e["kind"] == "comment"] == [
        {"comment_id": keep["id"]}
    ]


# ── the migration ────────────────────────────────────────────────────


def test_migration_0044_backfills_a_created_entry_per_artifact_and_downgrade_drops_the_table(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0043")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, status, number, created_by, created_at) "
            "VALUES ('t1', 'Old', 'backlog', 1, 'mcp', '2026-01-02 03:04:05.000000')"
        )
        conn.execute(
            "INSERT INTO tasks (id, title, status, number, created_by, created_at) "
            "VALUES ('t2', 'Newer', 'done', 2, 'user', '2026-02-03 04:05:06.000000')"
        )
    command.upgrade(alembic_config(), "0044")
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT task_id, kind, actor_kind, actor_name, data, created_at "
            "FROM task_activity ORDER BY task_id"
        ).fetchall()
        assert rows == [
            ("t1", "created", "mcp", "mcp", '{"lane": "Backlog"}', "2026-01-02 03:04:05.000000"),
            ("t2", "created", "user", "You", '{"lane": "Done"}', "2026-02-03 04:05:06.000000"),
        ]
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM tasks WHERE id = 't1'")
        assert conn.execute("SELECT COUNT(*) FROM task_activity").fetchone()[0] == 1  # the cascade
    command.downgrade(alembic_config(), "0043")
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "task_activity" not in tables


def test_migration_0045_backfills_comments_and_slims_the_old_traces(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0044")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, status, number, created_by, created_at) "
            "VALUES ('t1', 'Old', 'backlog', 1, 'user', '2026-01-02 03:04:05.000000')"
        )
        conn.execute(
            "INSERT INTO task_comments (id, task_id, body, author_kind, author, created_at, updated_at) "
            "VALUES ('c1', 't1', 'hello', 'mcp', 'opencode', '2026-01-03 00:00:00.000000', '2026-01-03 00:00:00.000000')"
        )
        conn.execute(
            "INSERT INTO task_activity (id, task_id, kind, actor_kind, actor_name, execution_id, data, created_at) "
            "VALUES ('a1', 't1', 'run', 'user', 'You', 'e1', "
            '\'{"number": 7, "pipeline": "P", "status": "done", "started_at": "2026-01-04T05:06:07+00:00", "duration_ms": 5}\', '
            "'2026-01-04 05:06:07.000000')"
        )
    command.upgrade(alembic_config(), "0045")
    with sqlite3.connect(db) as conn:
        comment = conn.execute(
            "SELECT actor_kind, actor_name, data, created_at FROM task_activity WHERE kind = 'comment'"
        ).fetchall()
        assert comment == [
            ("mcp", "opencode", '{"comment_id": "c1"}', "2026-01-03 00:00:00")
        ] or comment == [("mcp", "opencode", '{"comment_id": "c1"}', "2026-01-03 00:00:00.000000")]
        run = conn.execute(
            "SELECT actor_kind, actor_name, data FROM task_activity WHERE id = 'a1'"
        ).fetchone()
        assert run[:2] == ("system", "unknown")
        assert json.loads(run[2]) == {"number": 7, "started_at": "2026-01-04T05:06:07+00:00"}
    command.downgrade(alembic_config(), "0044")
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM task_activity WHERE kind = 'comment'").fetchone()[0]
            == 0
        )
