"""Tests for task creation: migration, validation, persistence, API."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings

# ── Migration ─────────────────────────────────────────────────────────


# ── API ───────────────────────────────────────────────────────────────


def test_list_is_empty_initially(client: TestClient) -> None:
    response = client.get("/api/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_one_task_is_read_by_id_or_by_number(client: TestClient) -> None:
    created = client.post("/api/tasks", json={"title": "Read me"}).json()
    by_id = client.get(f"/api/tasks/{created['id']}")
    assert by_id.status_code == 200 and by_id.json() == created
    assert client.get(f"/api/tasks/{created['number']}").json()["id"] == created["id"]
    assert client.get(f"/api/tasks/%23{created['number']}").json()["id"] == created["id"]
    assert client.get("/api/tasks/nope").status_code == 404
    assert client.get("/api/tasks/99").status_code == 404


def test_a_task_with_an_unknown_parent_is_not_created(client: TestClient) -> None:
    response = client.post("/api/tasks", json={"title": "Orphan", "parent_id": "nope"})
    assert response.status_code == 422
    assert client.get("/api/tasks").json() == []


def test_create_task_returns_201_with_all_fields(client: TestClient) -> None:
    response = client.post(
        "/api/tasks", json={"title": "Write docs", "body": "Details", "status": "in_progress"}
    )
    assert response.status_code == 201
    data = response.json()
    assert (
        set(data)
        == {
            "id",
            "number",
            "title",
            "body",
            "status",
            "position",
            "parent_id",
            "pipeline_id",
            "stage_id",
            "action_id",
            "created_by",
            "created_at",
            "updated_at",
            "fields",
            "body_resolved",
            "preview",
            "body_resolved_segments",  # the marked text, only filled while the personal setting marks resolved references
            "preview_segments",
            "warnings",
        }
    )
    # a body without a reference has nothing filled in; the three are the references' part of the contract (ADR-064)
    assert (data["body_resolved"], data["preview"], data["warnings"]) == (None, None, [])
    assert (data["body_resolved_segments"], data["preview_segments"]) == (
        None,
        None,
    )  # the setting is off
    assert data["fields"] == {}  # no artifact fields are defined yet
    assert data["title"] == "Write docs"
    assert data["body"] == "Details"
    assert data["status"] == "in_progress"
    assert data["created_at"].endswith("Z")
    assert len(data["id"]) == 36


def test_create_task_defaults_to_backlog_and_null_body(client: TestClient) -> None:
    data = client.post("/api/tasks", json={"title": "Only title"}).json()
    assert data["status"] == "backlog"
    assert data["body"] is None


def test_title_is_trimmed_and_blank_body_becomes_null(client: TestClient) -> None:
    data = client.post("/api/tasks", json={"title": "  Hi  ", "body": "   "}).json()
    assert data["title"] == "Hi"
    assert data["body"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 256},
        {"title": "ok", "status": "BACKLOG"},
        {"title": "ok", "status": "review"},
        {"title": "ok", "body": "x" * 10_001},
        {"title": "ok", "unexpected": 1},
    ],
)
def test_invalid_payload_is_rejected(client: TestClient, payload: dict[str, object]) -> None:
    assert client.post("/api/tasks", json=payload).status_code == 422
    assert client.get("/api/tasks").json() == []


def test_tasks_are_listed_newest_first(client: TestClient) -> None:
    for title in ("first", "second", "third"):
        client.post("/api/tasks", json={"title": title})
    titles = [t["title"] for t in client.get("/api/tasks").json()]
    assert titles == ["third", "second", "first"]


def test_tasks_survive_application_restart(migrated_settings: Settings) -> None:
    """Persistence: a new app instance on the same database still sees the task."""
    with TestClient(_create_app(migrated_settings)) as first:
        created = first.post("/api/tasks", json={"title": "Persist me", "status": "done"}).json()

    with TestClient(_create_app(migrated_settings)) as second:
        tasks = second.get("/api/tasks").json()

    assert [t["id"] for t in tasks] == [created["id"]]
    assert tasks[0]["status"] == "done"


# ── Move (lane switch) ────────────────────────────────────────────────


def _create(client: TestClient, **payload: object) -> dict[str, Any]:
    return client.post("/api/tasks", json={"title": "T", **payload}).json()  # type: ignore[no-any-return]


def test_move_task_changes_lane_and_persists(client: TestClient) -> None:
    task = _create(client)
    response = client.patch(f"/api/tasks/{task['id']}", json={"status": "done"})
    assert response.status_code == 200
    assert response.json()["status"] == "done"
    assert response.json()["updated_at"] >= task["updated_at"]
    assert client.get("/api/tasks").json()[0]["status"] == "done"


def test_move_to_another_lane_lands_at_the_top(client: TestClient) -> None:
    first = _create(client, title="first")
    _create(client, title="second", status="done")
    client.patch(f"/api/tasks/{first['id']}", json={"status": "done"})
    done = [t["title"] for t in client.get("/api/tasks").json() if t["status"] == "done"]
    assert done == ["first", "second"]  # no position given -> top of the target lane


def test_move_unknown_task_is_404(client: TestClient) -> None:
    assert client.patch("/api/tasks/nope", json={"status": "done"}).status_code == 404


@pytest.mark.parametrize("payload", [{}, {"status": "review"}, {"status": "DONE"}])
def test_move_rejects_invalid_payload(client: TestClient, payload: dict[str, object]) -> None:
    task = _create(client)
    assert client.patch(f"/api/tasks/{task['id']}", json=payload).status_code == 422
    assert client.get("/api/tasks").json()[0]["status"] == "backlog"


# ── Delete ────────────────────────────────────────────────────────────


def test_delete_task_removes_it_permanently(client: TestClient) -> None:
    keep, drop = _create(client, title="keep"), _create(client, title="drop")
    assert client.delete(f"/api/tasks/{drop['id']}").status_code == 204
    assert [t["id"] for t in client.get("/api/tasks").json()] == [keep["id"]]


def test_delete_unknown_or_twice_is_404(client: TestClient) -> None:
    task = _create(client)
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 404
    assert client.delete("/api/tasks/nope").status_code == 404


# ── Events published for every change ─────────────────────────────────


def _task_events(published: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, dict[str, Any]]]:
    """The task events; the activity entries that the same changes write are the subject of test_activity.py."""
    return [(name, data) for name, data in published if not name.startswith("activity.")]


def test_changes_are_published_as_events(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    task = _create(client, title="evt")
    client.patch(f"/api/tasks/{task['id']}", json={"status": "in_progress"})
    client.delete(f"/api/tasks/{task['id']}")

    events = _task_events(published)
    assert [t for t, _ in events] == ["task.created", "task.moved", "task.deleted"]
    assert events[0][1]["id"] == task["id"]
    assert events[0][1]["status"] == "backlog"
    assert events[1][1]["status"] == "in_progress"
    assert events[2][1] == {"id": task["id"]}


def test_failed_or_noop_requests_publish_nothing(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    task = _create(client)
    published.clear()
    client.post("/api/tasks", json={"title": ""})  # 422
    client.patch(f"/api/tasks/{task['id']}", json={"status": "backlog"})  # already there
    client.patch("/api/tasks/nope", json={"status": "done"})  # 404
    client.delete("/api/tasks/nope")  # 404
    assert published == []


def test_events_route_is_registered(
    client: TestClient, app_routes: Callable[[Any], list[str]]
) -> None:
    assert "/api/events" in app_routes(client.app)


# ── Edit (title / body) ───────────────────────────────────────────────


def test_edit_title_and_body_persists(client: TestClient) -> None:
    task = _create(client, title="old", body="old body")
    response = client.patch(
        f"/api/tasks/{task['id']}", json={"title": "  new  ", "body": "new body"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "new"
    assert response.json()["body"] == "new body"
    assert response.json()["status"] == "backlog"
    stored = client.get("/api/tasks").json()[0]
    assert (stored["title"], stored["body"]) == ("new", "new body")


def test_edit_only_sent_fields_change(client: TestClient) -> None:
    task = _create(client, title="keep", body="keep body")
    data = client.patch(f"/api/tasks/{task['id']}", json={"title": "changed"}).json()
    assert (data["title"], data["body"]) == ("changed", "keep body")


def test_edit_can_clear_body(client: TestClient) -> None:
    task = _create(client, body="to be removed")
    assert client.patch(f"/api/tasks/{task['id']}", json={"body": None}).json()["body"] is None
    assert client.patch(f"/api/tasks/{task['id']}", json={"body": "   "}).json()["body"] is None


def test_edit_and_move_in_one_request(client: TestClient) -> None:
    task = _create(client)
    data = client.patch(f"/api/tasks/{task['id']}", json={"title": "both", "status": "done"}).json()
    assert (data["title"], data["status"]) == ("both", "done")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": ""},
        {"title": "   "},
        {"title": None},
        {"status": None},
        {"title": "x" * 256},
        {"body": "x" * 10_001},
        {"unexpected": 1},
    ],
)
def test_edit_rejects_invalid_payload(client: TestClient, payload: dict[str, object]) -> None:
    task = _create(client, title="orig")
    assert client.patch(f"/api/tasks/{task['id']}", json=payload).status_code == 422
    assert client.get("/api/tasks").json()[0]["title"] == "orig"


def test_edit_unknown_task_is_404(client: TestClient) -> None:
    assert client.patch("/api/tasks/nope", json={"title": "x"}).status_code == 404


def test_edit_publishes_updated_and_move_publishes_moved(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    task = _create(client, title="t")
    published.clear()
    client.patch(f"/api/tasks/{task['id']}", json={"title": "renamed"})
    client.patch(f"/api/tasks/{task['id']}", json={"status": "done"})
    client.patch(f"/api/tasks/{task['id']}", json={"title": "again", "status": "backlog"})
    events = _task_events(published)
    assert [t for t, _ in events] == ["task.updated", "task.moved", "task.updated"]
    assert events[0][1]["title"] == "renamed"
    assert events[2][1]["status"] == "backlog"


def test_edit_without_changes_publishes_nothing_and_keeps_updated_at(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    task = _create(client, title="same", body="same body")
    published.clear()
    response = client.patch(
        f"/api/tasks/{task['id']}", json={"title": "same", "body": "same body", "status": "backlog"}
    )
    assert response.status_code == 200
    assert response.json()["updated_at"] == task["updated_at"]
    assert published == []


# ── Order inside a lane ───────────────────────────────────────────────


def _titles(client: TestClient, status: str = "backlog") -> list[str]:
    return [t["title"] for t in client.get("/api/tasks").json() if t["status"] == status]


def _three(client: TestClient) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    a, b, c = (_create(client, title=t) for t in ("a", "b", "c"))  # list order: c, b, a
    return a, b, c


def test_new_tasks_start_at_the_top(client: TestClient) -> None:
    _three(client)
    assert _titles(client) == ["c", "b", "a"]


def test_reorder_before_another_task(client: TestClient) -> None:
    a, _b, c = _three(client)
    data = client.patch(f"/api/tasks/{a['id']}", json={"before_id": c["id"]}).json()
    assert _titles(client) == ["a", "c", "b"]
    assert data["status"] == "backlog"


def test_reorder_to_the_end_with_null(client: TestClient) -> None:
    _a, _b, c = _three(client)
    client.patch(f"/api/tasks/{c['id']}", json={"before_id": None})
    assert _titles(client) == ["b", "a", "c"]


def test_reorder_into_the_middle(client: TestClient) -> None:
    a, b, c = _three(client)  # c, b, a
    client.patch(f"/api/tasks/{c['id']}", json={"before_id": a["id"]})
    assert _titles(client) == ["b", "c", "a"]
    assert b["id"]


def test_move_to_other_lane_at_a_given_position(client: TestClient) -> None:
    a, _b, _c = _three(client)
    x = _create(client, title="x", status="done")
    y = _create(client, title="y", status="done")  # done: y, x
    moved = client.patch(
        f"/api/tasks/{a['id']}", json={"status": "done", "before_id": x["id"]}
    ).json()
    assert moved["status"] == "done"
    assert _titles(client, "done") == ["y", "a", "x"]
    assert _titles(client) == ["c", "b"]
    assert y["id"]


def test_move_to_other_lane_end(client: TestClient) -> None:
    a, _b, _c = _three(client)
    _create(client, title="x", status="done")
    client.patch(f"/api/tasks/{a['id']}", json={"status": "done", "before_id": None})
    assert _titles(client, "done") == ["x", "a"]


def test_before_id_must_be_in_the_target_lane(client: TestClient) -> None:
    a, _b, _c = _three(client)
    other = _create(client, title="other", status="done")
    assert client.patch(f"/api/tasks/{a['id']}", json={"before_id": other["id"]}).status_code == 422
    assert client.patch(f"/api/tasks/{a['id']}", json={"before_id": "nope"}).status_code == 422
    assert client.patch(f"/api/tasks/{a['id']}", json={"before_id": a["id"]}).status_code == 422
    assert _titles(client) == ["c", "b", "a"]


def test_reorder_to_the_same_place_changes_nothing(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    a, b, _c = _three(client)  # c, b, a
    published.clear()
    before = client.get("/api/tasks").json()
    assert client.patch(f"/api/tasks/{b['id']}", json={"before_id": a["id"]}).status_code == 200
    assert client.get("/api/tasks").json() == before
    assert published == []


def test_reorder_is_published_as_moved(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    a, _b, c = _three(client)
    published.clear()
    client.patch(f"/api/tasks/{a['id']}", json={"before_id": c["id"]})
    assert [t for t, _ in published] == ["task.moved"]
    assert published[0][1]["id"] == a["id"]


def test_many_reorders_keep_a_consistent_order_and_resync_when_renumbered(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    """Dropping between the same two neighbours again and again exhausts float precision;
    the lane is then renumbered and clients are told to resync."""
    a, b, _c = _three(client)  # c, b, a
    ids = [a["id"], b["id"]]
    expected = ["c", "b", "a"]
    for i in range(60):
        mover = ids[i % 2]
        other = ids[(i + 1) % 2]
        client.patch(f"/api/tasks/{mover}", json={"before_id": other})
        # keep the model of the expected order
        name = {a["id"]: "a", b["id"]: "b"}
        expected.remove(name[mover])
        expected.insert(expected.index(name[other]), name[mover])
    assert _titles(client) == expected
    assert any(t == "board.resync" for t, _ in published)


def test_content_edit_together_with_reorder_is_an_update(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    a, _b, c = _three(client)
    published.clear()
    client.patch(f"/api/tasks/{a['id']}", json={"title": "A!", "before_id": c["id"]})
    assert [t for t, _ in _task_events(published)] == ["task.updated"]
    assert _titles(client)[0] == "A!"


# ── Parent / child (a tree) ───────────────────────────────────────────


def _parent(client: TestClient, child: dict[str, Any], parent: dict[str, Any] | None) -> Any:
    return client.patch(
        f"/api/tasks/{child['id']}", json={"parent_id": parent["id"] if parent else None}
    )


def test_new_tasks_have_no_parent(client: TestClient) -> None:
    assert _create(client)["parent_id"] is None


def test_set_and_clear_parent(client: TestClient) -> None:
    parent, child = _create(client, title="p"), _create(client, title="c")
    data = _parent(client, child, parent).json()
    assert data["parent_id"] == parent["id"]
    stored = {t["title"]: t["parent_id"] for t in client.get("/api/tasks").json()}
    assert stored == {"p": None, "c": parent["id"]}
    assert _parent(client, child, None).json()["parent_id"] is None


def test_one_parent_can_have_many_children_and_children_can_be_parents(client: TestClient) -> None:
    root = _create(client, title="root")
    kids = [_create(client, title=f"kid{i}") for i in range(4)]
    for kid in kids:
        assert _parent(client, kid, root).status_code == 200
    grandchild = _create(client, title="grandchild")
    assert _parent(client, grandchild, kids[0]).status_code == 200  # a child as parent
    by_title = {t["title"]: t["parent_id"] for t in client.get("/api/tasks").json()}
    assert [by_title[f"kid{i}"] for i in range(4)] == [root["id"]] * 4
    assert by_title["grandchild"] == kids[0]["id"]
    assert by_title["root"] is None


def test_parent_may_live_in_another_lane(client: TestClient) -> None:
    parent, child = _create(client, status="done"), _create(client, status="backlog")
    assert _parent(client, child, parent).status_code == 200


def test_task_cannot_be_its_own_parent(client: TestClient) -> None:
    task = _create(client)
    assert _parent(client, task, task).status_code == 422


def test_cycles_are_rejected(client: TestClient) -> None:
    a, b, c = _create(client, title="a"), _create(client, title="b"), _create(client, title="c")
    assert _parent(client, b, a).status_code == 200  # a <- b
    assert _parent(client, c, b).status_code == 200  # a <- b <- c
    assert _parent(client, a, b).status_code == 422  # direct loop
    assert _parent(client, a, c).status_code == 422  # loop through a grandchild
    by_title = {t["title"]: t["parent_id"] for t in client.get("/api/tasks").json()}
    assert by_title["a"] is None


def test_unknown_parent_is_rejected(client: TestClient) -> None:
    task = _create(client)
    response = client.patch(f"/api/tasks/{task['id']}", json={"parent_id": "nope"})
    assert response.status_code == 422
    assert client.get("/api/tasks").json()[0]["parent_id"] is None


def test_parent_change_is_an_update_event_and_noop_is_silent(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    parent, child = _create(client, title="p"), _create(client, title="c")
    published.clear()
    _parent(client, child, parent)
    events = _task_events(published)
    assert [t for t, _ in events] == ["task.updated"]
    assert events[0][1]["parent_id"] == parent["id"]
    published.clear()
    _parent(client, child, parent)  # same parent again
    assert published == []


def test_deleting_a_parent_detaches_its_children(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    parent, kid = _create(client, title="p"), _create(client, title="kid")
    grandkid = _create(client, title="grandkid")
    _parent(client, kid, parent)
    _parent(client, grandkid, kid)
    published.clear()
    assert client.delete(f"/api/tasks/{parent['id']}").status_code == 204
    by_title = {t["title"]: t["parent_id"] for t in client.get("/api/tasks").json()}
    assert by_title == {"kid": None, "grandkid": kid["id"]}  # kid detached, subtree below it intact
    assert [t for t, _ in published] == ["task.deleted", "board.resync"]


def test_deleting_a_leaf_does_not_trigger_resync(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    leaf = _create(client)
    published.clear()
    client.delete(f"/api/tasks/{leaf['id']}")
    assert [t for t, _ in published] == ["task.deleted"]


# ── Artifact numbers (#1, #2 …) ───────────────────────────────────────


def test_numbers_count_up_and_are_never_reused(client: TestClient) -> None:
    first, second = _create(client, title="a"), _create(client, title="b")
    assert (first["number"], second["number"]) == (1, 2)
    client.delete(f"/api/tasks/{second['id']}")
    assert _create(client, title="c")["number"] == 3  # 2 stays retired


def test_number_cannot_be_changed_through_the_api(client: TestClient) -> None:
    task = _create(client)
    assert client.patch(f"/api/tasks/{task['id']}", json={"number": 99}).status_code == 422
    assert client.get("/api/tasks").json()[0]["number"] == task["number"]


# ── Foreign key on parent_id ──────────────────────────────────────────

#: A task row as the database requires it (lane, number, position, origin, dates); id, number and parent vary.
_ROW = (
    "INSERT INTO tasks (id, title, status, number, position, created_by, created_at, updated_at, parent_id) "
    "VALUES (?, 'T', 'backlog', ?, 0, 'user', '2026-01-01', '2026-01-01', ?)"
)


def test_database_rejects_a_dangling_parent(migrated_settings: Settings) -> None:
    db_path = migrated_settings.data_dir / migrated_settings.database_filename
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        # every other column valid, so the only thing that can fail is the dangling parent
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            conn.execute(_ROW, ("a", 1, "missing"))


def test_deleting_a_parent_row_nulls_the_children_in_the_database(
    migrated_settings: Settings,
) -> None:
    db_path = migrated_settings.data_dir / migrated_settings.database_filename
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(_ROW, ("p", 1, None))
        conn.execute(_ROW, ("c", 2, "p"))
        conn.execute("DELETE FROM tasks WHERE id = 'p'")
        assert conn.execute("SELECT parent_id FROM tasks WHERE id = 'c'").fetchone() == (None,)


# ── runs that never happened, and data that is already broken ────────


def test_the_results_of_an_artifact_that_was_never_processed_are_404(client: TestClient) -> None:
    task = _create(client, title="Idle")
    for url in (f"/api/runs/{task['id']}/results", f"/api/runs/{task['number']}/results"):
        response = client.get(url)
        assert response.status_code == 404
        assert response.json()["detail"] == "The artifact was never processed"
    assert client.get("/api/runs/nope/results").json()["detail"] == "Artifact not found"


def test_the_service_has_no_results_for_an_artifact_that_never_ran(client: TestClient) -> None:
    task = _create(client, title="Idle")
    service = client.app.state.artifacts  # type: ignore[attr-defined]
    assert client.portal is not None
    assert client.portal.call(service.run_results, task["id"]) is None


def test_a_parent_cycle_already_in_the_data_does_not_hang_a_new_assignment(
    client: TestClient, migrated_settings: Settings
) -> None:
    """Only broken data can hold a cycle; checking a new parent must still end."""
    a, b, c = _create(client, title="a"), _create(client, title="b"), _create(client, title="c")
    path = migrated_settings.data_dir / migrated_settings.database_filename
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE tasks SET parent_id = ? WHERE id = ?", (b["id"], a["id"]))
        conn.execute("UPDATE tasks SET parent_id = ? WHERE id = ?", (a["id"], b["id"]))
    response = client.patch(f"/api/tasks/{c['id']}", json={"parent_id": a["id"]})
    assert response.status_code == 200
    assert response.json()["parent_id"] == a["id"]
