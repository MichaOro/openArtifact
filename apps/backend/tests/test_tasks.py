"""Tests for task creation: migration, validation, persistence, API."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient

import openartifact.database as db_mod
from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings


def _alembic_config() -> Config:
    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_settings(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings pointing at a temp database with all migrations applied."""
    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    command.upgrade(_alembic_config(), "head")
    return settings


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


@pytest.fixture
def client(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    """Test client with the real lifespan (shared engine) on a migrated database."""
    with TestClient(_create_app(migrated_settings)) as c:
        yield c
    assert db_mod._engine is None


# ── Migration ─────────────────────────────────────────────────────────


def test_migration_creates_tasks_table_and_enforces_status(migrated_settings: Settings) -> None:
    db_path = migrated_settings.data_dir / migrated_settings.database_filename
    with sqlite3.connect(db_path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        assert cols == {"id", "title", "body", "status", "created_at", "updated_at"}
        conn.execute("INSERT INTO tasks (id, title, status) VALUES ('a', 'T', 'done')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tasks (id, title, status) VALUES ('b', 'T', 'BACKLOG')")


def test_migration_downgrade_removes_tasks(migrated_settings: Settings) -> None:
    command.downgrade(_alembic_config(), "0002")
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
    assert set(data) == {"id", "title", "body", "status", "created_at", "updated_at"}
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


def test_move_keeps_creation_order_in_target_lane(client: TestClient) -> None:
    first = _create(client, title="first")
    second = _create(client, title="second", status="done")
    client.patch(f"/api/tasks/{first['id']}", json={"status": "done"})
    done = [t["title"] for t in client.get("/api/tasks").json() if t["status"] == "done"]
    assert done == ["second", "first"]  # newest first, independent of move time
    assert second["id"]


def test_move_unknown_task_is_404(client: TestClient) -> None:
    assert client.patch("/api/tasks/nope", json={"status": "done"}).status_code == 404


@pytest.mark.parametrize("payload", [{}, {"status": "review"}, {"status": "DONE"}, {"title": "x"}])
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
