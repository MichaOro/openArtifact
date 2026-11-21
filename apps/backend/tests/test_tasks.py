"""Tests for task creation: migration, validation, persistence, API."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from tests.conftest import alembic_config


@pytest.fixture
def published(client: TestClient) -> list[tuple[str, dict[str, Any]]]:
    """Record everything the app publishes on its event bus."""
    events: list[tuple[str, dict[str, Any]]] = []
    bus = client.app.state.event_bus  # type: ignore[attr-defined]
    original = bus.publish

    def spy(event_type: str, data: dict[str, Any]) -> Any:
        events.append((event_type, data))
        return original(event_type, data)

    bus.publish = spy
    return events


# ── Migration ─────────────────────────────────────────────────────────


def test_migration_creates_tasks_table_and_enforces_status(migrated_settings: Settings) -> None:
    db_path = migrated_settings.data_dir / migrated_settings.database_filename
    with sqlite3.connect(db_path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        assert cols == {
            "id",
            "number",
            "title",
            "body",
            "status",
            "position",
            "parent_id",
            "created_at",
            "updated_at",
        }
        conn.execute("INSERT INTO tasks (id, title, status) VALUES ('a', 'T', 'done')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tasks (id, title, status) VALUES ('b', 'T', 'BACKLOG')")


def test_migration_downgrade_removes_tasks(migrated_settings: Settings) -> None:
    command.downgrade(alembic_config(), "0002")
    db_path = migrated_settings.data_dir / migrated_settings.database_filename
    with sqlite3.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "tasks" not in tables
    assert "work_items" in tables


# ── API ───────────────────────────────────────────────────────────────


def test_list_is_empty_initially(client: TestClient) -> None:
    response = client.get("/api/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_create_task_returns_201_with_all_fields(client: TestClient) -> None:
    response = client.post(
        "/api/tasks", json={"title": "Write docs", "body": "Details", "status": "in_progress"}
    )
    assert response.status_code == 201
    data = response.json()
    assert set(data) == {
        "id",
        "number",
        "title",
        "body",
        "status",
        "position",
        "parent_id",
        "created_at",
        "updated_at",
    }
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


def test_changes_are_published_as_events(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    task = _create(client, title="evt")
    client.patch(f"/api/tasks/{task['id']}", json={"status": "in_progress"})
    client.delete(f"/api/tasks/{task['id']}")

    assert [t for t, _ in published] == ["task.created", "task.moved", "task.deleted"]
    assert published[0][1]["id"] == task["id"]
    assert published[0][1]["status"] == "backlog"
    assert published[1][1]["status"] == "in_progress"
    assert published[2][1] == {"id": task["id"]}


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
    assert [t for t, _ in published] == ["task.updated", "task.moved", "task.updated"]
    assert published[0][1]["title"] == "renamed"
    assert published[2][1]["status"] == "backlog"


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
    assert [t for t, _ in published] == ["task.updated"]
    assert _titles(client)[0] == "A!"


def test_migration_0004_backfills_positions_in_the_old_order(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    command.upgrade(alembic_config(), "0003")
    db_path = settings.data_dir / settings.database_filename
    with sqlite3.connect(db_path) as conn:
        for tid, status, created in (
            ("t1", "backlog", "2026-01-01 10:00:00"),
            ("t2", "backlog", "2026-01-01 11:00:00"),
            ("t3", "backlog", "2026-01-01 12:00:00"),
            ("t4", "done", "2026-01-01 09:00:00"),
        ):
            conn.execute(
                "INSERT INTO tasks (id, title, status, created_at) VALUES (?, ?, ?, ?)",
                (tid, tid, status, created),
            )
    command.upgrade(alembic_config(), "head")
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT id, position FROM tasks ORDER BY status, position").fetchall()
    assert rows == [("t3", 0.0), ("t2", 1.0), ("t1", 2.0), ("t4", 0.0)]  # newest first, per lane
    command.downgrade(alembic_config(), "0003")
    with sqlite3.connect(db_path) as conn:
        assert "position" not in {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}


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
    assert [t for t, _ in published] == ["task.updated"]
    assert published[0][1]["parent_id"] == parent["id"]
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


def test_migration_0005_adds_nullable_parent_id(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    command.upgrade(alembic_config(), "0004")
    db_path = settings.data_dir / settings.database_filename
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO tasks (id, title) VALUES ('old', 'existing row')")
    command.upgrade(alembic_config(), "head")
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT parent_id FROM tasks WHERE id='old'").fetchone() == (None,)
        # the CHECK constraint on status survives the schema change
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tasks (id, title, status) VALUES ('bad', 'x', 'BACKLOG')")
    command.downgrade(alembic_config(), "0004")
    with sqlite3.connect(db_path) as conn:
        assert "parent_id" not in {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        assert conn.execute("SELECT title FROM tasks WHERE id='old'").fetchone() == (
            "existing row",
        )


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


def test_migration_0006_numbers_existing_tasks_oldest_first(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    command.upgrade(alembic_config(), "0005")
    db_path = settings.data_dir / settings.database_filename
    with sqlite3.connect(db_path) as conn:
        for tid, created in (("t2", "2026-01-02 10:00:00"), ("t1", "2026-01-01 10:00:00")):
            conn.execute(
                "INSERT INTO tasks (id, title, status, created_at) VALUES (?, ?, 'backlog', ?)",
                (tid, tid, created),
            )
    command.upgrade(alembic_config(), "head")
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT id, number FROM tasks ORDER BY number").fetchall() == [
            ("t1", 1),
            ("t2", 2),
        ]
        assert conn.execute("SELECT last FROM task_number_seq").fetchone() == (2,)


# ── Foreign key on parent_id ──────────────────────────────────────────


def test_database_rejects_a_dangling_parent(migrated_settings: Settings) -> None:
    db_path = migrated_settings.data_dir / migrated_settings.database_filename
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tasks (id, title, parent_id) VALUES ('a', 'A', 'missing')")


def test_deleting_a_parent_row_nulls_the_children_in_the_database(
    migrated_settings: Settings,
) -> None:
    db_path = migrated_settings.data_dir / migrated_settings.database_filename
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("INSERT INTO tasks (id, title) VALUES ('p', 'P')")
        conn.execute("INSERT INTO tasks (id, title, parent_id) VALUES ('c', 'C', 'p')")
        conn.execute("DELETE FROM tasks WHERE id = 'p'")
        assert conn.execute("SELECT parent_id FROM tasks WHERE id = 'c'").fetchone() == (None,)


def test_migration_0007_clears_dangling_parents_and_keeps_the_rest(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    command.upgrade(alembic_config(), "0006")
    db_path = settings.data_dir / settings.database_filename
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO tasks (id, title, number) VALUES ('p', 'P', 1)")
        conn.execute("INSERT INTO tasks (id, title, number, parent_id) VALUES ('c', 'C', 2, 'p')")
        conn.execute(
            "INSERT INTO tasks (id, title, number, parent_id) VALUES ('o', 'O', 3, 'gone')"
        )
    command.upgrade(alembic_config(), "head")
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT id, number, parent_id FROM tasks ORDER BY number").fetchall()
        assert rows == [("p", 1, None), ("c", 2, "p"), ("o", 3, None)]
        indexes = {r[1] for r in conn.execute("PRAGMA index_list(tasks)")}
        assert {"ux_tasks_number", "ix_tasks_parent_id"} <= indexes
        with pytest.raises(sqlite3.IntegrityError):  # the status CHECK survived the rebuild
            conn.execute("INSERT INTO tasks (id, title, status) VALUES ('x', 'X', 'BACKLOG')")
    command.downgrade(alembic_config(), "0006")
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "INSERT INTO tasks (id, title, parent_id) VALUES ('z', 'Z', 'nowhere')"
        )  # no FK anymore
