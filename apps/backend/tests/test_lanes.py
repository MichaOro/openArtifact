"""Lanes are rows: listing, adding, renaming, deleting (rules and limits), artifacts in custom lanes,
the integration API and MCP mirrors, events, the page, and migration 0030."""

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
from openartifact.tasks.lanes import MAX_LANES, key_for
from tests.helpers import alembic_config

TOKEN = "lanes-token-" + "x" * 30
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}
NOT_EMPTY = "A lane can only be deleted when it contains no artifacts."


@pytest.fixture
def secured(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def _bus(client: TestClient) -> Any:
    return client.app.state.event_bus  # type: ignore[attr-defined]


def _titles(lanes: list[dict[str, Any]]) -> list[str]:
    return [lane["title"] for lane in lanes]


def _add(client: TestClient, title: str, prefix: str = "/api/lanes") -> Any:
    return client.post(prefix, json={"title": title})


def _rename(client: TestClient, status: str, title: str, prefix: str = "/api/lanes") -> Any:
    return client.put(f"{prefix}/{status}", json={"title": title})


def _task(client: TestClient, status: str | None = None, title: str = "A") -> dict[str, Any]:
    body: dict[str, Any] = {"title": title}
    if status is not None:
        body["status"] = status
    response = client.post("/api/tasks", json=body)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def test_the_default_lanes(client: TestClient) -> None:
    assert client.get("/api/lanes").json() == [
        {
            "status": "backlog",
            "key": "backlog",
            "title": "Backlog",
            "position": 0,
            "hue": 1,
            "artifact_count": 0,
            "deletable": True,
        },
        {
            "status": "in_progress",
            "key": "in-progress",
            "title": "In Progress",
            "position": 1,
            "hue": 2,
            "artifact_count": 0,
            "deletable": True,
        },
        {
            "status": "done",
            "key": "done",
            "title": "Done",
            "position": 2,
            "hue": 3,
            "artifact_count": 0,
            "deletable": True,
        },
    ]


def test_a_lane_is_added_at_the_end_with_a_key_from_its_title(client: TestClient) -> None:
    response = _add(client, "  Code Review ")
    assert response.status_code == 201
    lanes = response.json()
    assert _titles(lanes) == ["Backlog", "In Progress", "Done", "Code Review"]
    assert lanes[3]["status"] == "code_review" and lanes[3]["key"] == "code-review"
    assert lanes[3]["position"] == 3 and lanes[3]["hue"] == 4
    assert _titles(client.get("/api/lanes").json()) == _titles(lanes)


def test_keys_are_unique_valid_and_short() -> None:
    assert key_for("Code Review", set()) == "code_review"
    assert key_for("Review", {"review"}) == "review_2"
    assert key_for("Review", {"review", "review_2"}) == "review_3"
    assert key_for("2nd pass", set()) == "lane_2nd_pass"
    assert key_for("Ärger & Co.", set()) == "arger_co"
    assert key_for("!!!", set()) == "lane"
    assert key_for("日本語", set()) == "lane"
    long = key_for("x" * 40, {"x" * 32})
    assert len(long) == 32 and long.endswith("_2")


def test_a_deleted_lanes_key_can_be_used_again_and_titles_in_other_cases_get_a_suffix(
    client: TestClient,
) -> None:
    _add(client, "Review")
    lanes = client.delete("/api/lanes/review").json()
    assert _titles(lanes) == ["Backlog", "In Progress", "Done"]
    assert _add(client, "Review").json()[3]["status"] == "review"
    # same key, different title: "Re-view" and "Re view" both start from review
    assert _add(client, "Re view").json()[4]["status"] == "re_view"
    assert _add(client, "Re_view").json()[5]["status"] == "re_view_2"


def test_the_lane_limit(client: TestClient) -> None:
    for n in range(MAX_LANES - 3):
        assert _add(client, f"Lane {n}").status_code == 201
    assert len(client.get("/api/lanes").json()) == MAX_LANES
    refused = _add(client, "One too many")
    assert refused.status_code == 422 and str(MAX_LANES) in refused.json()["detail"]
    assert len(client.get("/api/lanes").json()) == MAX_LANES


def test_title_rules_apply_to_adding_and_renaming(client: TestClient) -> None:
    for send in (_add, lambda c, t: _rename(c, "in_progress", t)):
        for taken in ("done", "DONE", "  Done ", "backlog"):
            response = send(client, taken)
            assert response.status_code == 422, taken
            assert "already called" in response.json()["detail"]
        for empty in ("", "   "):
            assert send(client, empty).status_code == 422
        too_long = send(client, "x" * 41)
        assert too_long.status_code == 422 and "40" in too_long.json()["detail"]
        for bad in ("a\nb", "a\x00b", "tab\there", "bell\x07"):
            assert send(client, bad).status_code == 422, repr(bad)
    assert client.post("/api/lanes", json={}).status_code == 422
    assert client.post("/api/lanes", json={"title": None}).status_code == 422
    assert client.put("/api/lanes/done", json={"title": 5}).status_code == 422
    assert _rename(client, "done", "x" * 40).status_code == 200
    assert _titles(client.get("/api/lanes").json()) == ["Backlog", "In Progress", "x" * 40]


def test_a_lane_is_renamed_trimmed_and_its_key_stays(client: TestClient) -> None:
    task = _task(client, "in_progress")
    lanes = _rename(client, "in_progress", "  Review  ").json()
    assert _titles(lanes) == ["Backlog", "Review", "Done"]
    assert [lane["status"] for lane in lanes] == ["backlog", "in_progress", "done"]
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "in_progress"
    # a lane may take another case of its own title
    assert _titles(_rename(client, "done", "DONE").json())[2] == "DONE"


def test_an_unknown_lane_is_404(client: TestClient) -> None:
    assert _rename(client, "review", "Review").status_code == 404
    assert client.delete("/api/lanes/review").status_code == 404


def test_counts_and_deletable_follow_the_artifacts(client: TestClient) -> None:
    _task(client, "done")
    lanes = {lane["status"]: lane for lane in client.get("/api/lanes").json()}
    assert lanes["done"]["artifact_count"] == 1 and lanes["done"]["deletable"] is False
    assert lanes["backlog"]["artifact_count"] == 0 and lanes["backlog"]["deletable"] is True


def test_a_lane_with_artifacts_cannot_be_deleted(client: TestClient) -> None:
    _task(client, "done")
    response = client.delete("/api/lanes/done")
    assert response.status_code == 409 and response.json()["detail"] == NOT_EMPTY
    assert len(client.get("/api/lanes").json()) == 3


def test_an_emptied_lane_can_be_deleted_and_the_hues_follow_the_places(
    client: TestClient,
) -> None:
    task = _task(client, "in_progress")
    assert client.delete("/api/lanes/in_progress").status_code == 409
    client.patch(f"/api/tasks/{task['id']}", json={"status": "backlog"})
    lanes = client.delete("/api/lanes/in_progress").json()
    assert [(lane["status"], lane["hue"]) for lane in lanes] == [("backlog", 1), ("done", 2)]
    assert client.delete("/api/lanes/in_progress").status_code == 404


def test_the_last_lane_cannot_be_deleted(client: TestClient) -> None:
    client.delete("/api/lanes/in_progress")
    client.delete("/api/lanes/done")
    lanes = client.get("/api/lanes").json()
    assert [lane["deletable"] for lane in lanes] == [False]
    response = client.delete("/api/lanes/backlog")
    assert response.status_code == 409 and "last lane" in response.json()["detail"]


def test_new_artifacts_without_a_lane_go_to_the_first_lane(client: TestClient) -> None:
    first = _task(client)
    assert first["status"] == "backlog"
    client.patch(f"/api/tasks/{first['id']}", json={"status": "done"})
    client.delete("/api/lanes/backlog")
    assert _task(client)["status"] == "in_progress"
    assert client.post("/api/tasks", json={"title": "x", "status": None}).json()["status"] == (
        "in_progress"
    )


def test_artifacts_can_be_created_in_and_moved_to_a_custom_lane(client: TestClient) -> None:
    _add(client, "Review")
    created = _task(client, "review")
    assert created["status"] == "review"
    other = _task(client, "backlog", "B")
    moved = client.patch(f"/api/tasks/{other['id']}", json={"status": "review"})
    assert moved.status_code == 200 and moved.json()["status"] == "review"
    counts = {lane["status"]: lane["artifact_count"] for lane in client.get("/api/lanes").json()}
    assert counts["review"] == 2


def test_an_unknown_lane_key_is_422_and_lists_the_valid_ones(client: TestClient) -> None:
    created = client.post("/api/tasks", json={"title": "x", "status": "sideways"})
    assert created.status_code == 422
    assert "Valid lanes: backlog, in_progress, done" in created.json()["detail"]
    task = _task(client)
    moved = client.patch(f"/api/tasks/{task['id']}", json={"status": "Backlog"})
    assert moved.status_code == 422 and "Valid lanes" in moved.json()["detail"]
    assert client.patch(f"/api/tasks/{task['id']}", json={"status": None}).status_code == 422


def test_the_database_refuses_an_artifact_in_a_missing_lane_and_a_deletion_under_it(
    client: TestClient, migrated_settings: Settings
) -> None:
    """The race: a lane deleted while an artifact moves in cannot leave the artifact lane-less."""
    _add(client, "Review")
    task = _task(client, "review")
    path = migrated_settings.data_dir / migrated_settings.database_filename
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM lanes WHERE key = 'review'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE tasks SET status = 'nowhere' WHERE id = ?", (task["id"],))


def test_a_lane_deleted_between_the_check_and_the_write_is_a_conflict(
    client: TestClient, migrated_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The service sees the lane, then it is gone: the foreign key turns it into a 409."""
    from openartifact.tasks import lanes as lane_rules

    _add(client, "Review")
    task = _task(client, "backlog")
    path = migrated_settings.data_dir / migrated_settings.database_filename
    real = lane_rules.require_lane

    async def deleted_right_after(session: Any, key: str) -> str:
        found = await real(session, key)
        with sqlite3.connect(path) as conn:  # another request wins the race
            conn.execute("DELETE FROM lanes WHERE key = ?", (key,))
        return found

    monkeypatch.setattr(lane_rules, "require_lane", deleted_right_after)
    moved = client.patch(f"/api/tasks/{task['id']}", json={"status": "review"})
    assert moved.status_code == 409 and "no longer exists" in moved.json()["detail"]
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "backlog"
    _add(client, "Again")
    created = client.post("/api/tasks", json={"title": "n", "status": "again"})
    assert created.status_code == 409
    assert len(client.get("/api/tasks").json()) == 1


def test_the_board_page_renders_the_lanes_from_the_database(client: TestClient) -> None:
    _rename(client, "in_progress", "Review")
    _add(client, "Code Review")
    html = client.get("/").text
    assert ">Review</span></h2>" in html and ">In Progress</span></h2>" not in html
    assert 'data-lane="code-review" data-status="code_review" data-lane-hue="4"' in html
    assert 'data-status="in_progress" data-lane-title="Review"' in html
    assert 'aria-label="Add artifact to Code Review"' in html
    assert 'aria-label="Options for lane Review"' in html
    assert html.count("data-lane-menu") == 5  # four lanes and the template
    assert 'id="lane-template"' in html and "data-add-lane" in html
    assert "<title>Board · OpenArtifact</title>" in html


def test_every_change_publishes_board_lanes(client: TestClient) -> None:
    queue = _bus(client).subscribe()
    _add(client, "Review")
    _rename(client, "done", "Shipped")
    client.delete("/api/lanes/review")
    events = [queue.get_nowait() for _ in range(3)]
    assert [event.type for event in events] == ["board.lanes"] * 3
    assert _titles(events[0].data["lanes"]) == ["Backlog", "In Progress", "Done", "Review"]
    assert _titles(events[1].data["lanes"])[2] == "Shipped"
    assert _titles(events[2].data["lanes"]) == ["Backlog", "In Progress", "Shipped"]
    assert queue.empty()  # a lane change never moves an artifact
    description = client.get("/openapi.json").json()["paths"]["/api/events"]["get"]["description"]
    assert "board.lanes" in description


def test_a_refused_change_publishes_nothing(client: TestClient) -> None:
    _task(client, "done")
    queue = _bus(client).subscribe()
    _rename(client, "done", "Backlog")
    _add(client, "")
    client.delete("/api/lanes/done")
    client.delete("/api/lanes/nope")
    assert queue.empty()


def test_the_integration_api_mirrors_the_lanes_and_needs_the_token(secured: TestClient) -> None:
    v1 = "/api/v1/lanes"
    assert _titles(secured.get(v1).json()) == ["Backlog", "In Progress", "Done"]
    added = _add(secured, "Review", v1)
    assert added.status_code == 201 and _titles(added.json())[3] == "Review"
    assert _titles(_rename(secured, "backlog", "Ideas", v1).json())[0] == "Ideas"
    assert _titles(secured.get("/api/lanes").json())[0] == "Ideas"
    assert _rename(secured, "nope", "x", v1).status_code == 404
    assert _rename(secured, "done", "Ideas", v1).status_code == 422
    assert _add(secured, "ideas", v1).status_code == 422
    artifact = secured.post("/api/v1/artifacts", json={"title": "x", "status": "review"})
    assert artifact.status_code == 201
    assert secured.delete(f"{v1}/review").status_code == 409
    assert secured.delete(f"{v1}/done").status_code == 200
    anonymous = TestClient(secured.app)
    assert anonymous.get(v1).status_code == 401
    assert _add(anonymous, "Shipped", v1).status_code == 401
    assert _rename(anonymous, "backlog", "Shipped", v1).status_code == 401
    assert anonymous.delete(f"{v1}/backlog").status_code == 401
    assert anonymous.get("/api/lanes").status_code == 401


def _mcp(client: TestClient, name: str, **arguments: Any) -> dict[str, Any]:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    return client.post("/mcp", json=body).json()["result"]  # type: ignore[no-any-return]


def test_the_mcp_tools_follow_the_current_lanes(secured: TestClient) -> None:
    _add(secured, "Review")
    _rename(secured, "in_progress", "Doing")
    result = _mcp(secured, "list_lanes")
    lanes = [json.loads(item["text"]) for item in result["content"]]
    assert [(lane["status"], lane["title"]) for lane in lanes] == [
        ("backlog", "Backlog"),
        ("in_progress", "Doing"),
        ("done", "Done"),
        ("review", "Review"),
    ]
    created = _mcp(secured, "create_artifact", title="x", lane="review")
    assert json.loads(created["content"][0]["text"])["status"] == "review"
    default = _mcp(secured, "create_artifact", title="y")
    assert json.loads(default["content"][0]["text"])["status"] == "backlog"
    bad = _mcp(secured, "update_artifact", artifact="1", lane="sideways")
    assert bad["isError"] and "Valid lanes: backlog, in_progress, done, review" in str(bad)
    listing = secured.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = {tool["name"]: tool for tool in listing.json()["result"]["tools"]}
    assert "list_lanes" in tools
    assert not any("lane" in name and name != "list_lanes" for name in tools)  # read only


def test_the_openapi_text_for_the_lane_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths["/api/lanes"]) == {"get", "post"}
    assert set(paths["/api/lanes/{status}"]) == {"put", "delete"}
    assert "409" in paths["/api/lanes/{status}"]["delete"]["responses"]
    assert NOT_EMPTY in paths["/api/lanes/{status}"]["delete"]["description"]


def _tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_migration_0030_up_down_up_with_data(at_revision: Callable[[str], Path]) -> None:
    db = at_revision("0029")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO lane_titles (status, title) VALUES ('done', 'Shipped')")
        for n, status in enumerate(("backlog", "in_progress", "done")):
            conn.execute(
                "INSERT INTO tasks (id, title, status, position, number) VALUES (?, ?, ?, 0, ?)",
                (f"t{n}", f"T{n}", status, n + 1),
            )
    command.upgrade(alembic_config(), "0030")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        lanes = conn.execute("SELECT key, title, position FROM lanes ORDER BY position").fetchall()
        assert lanes == [
            ("backlog", "Backlog", 0),
            ("in_progress", "In Progress", 1),
            ("done", "Shipped", 2),
        ]
        assert "lane_titles" not in _tables(db)
        conn.execute("INSERT INTO lanes (key, title, position) VALUES ('review', 'Review', 3)")
        conn.execute("UPDATE tasks SET status = 'review' WHERE id = 't0'")
        with pytest.raises(sqlite3.IntegrityError):  # unique ignoring case
            conn.execute("INSERT INTO lanes (key, title, position) VALUES ('r2', 'REVIEW', 4)")
        with pytest.raises(sqlite3.IntegrityError):  # the lane is in use
            conn.execute("DELETE FROM lanes WHERE key = 'review'")
        with pytest.raises(sqlite3.IntegrityError):  # no such lane
            conn.execute("UPDATE tasks SET status = 'nowhere' WHERE id = 't1'")
        # the default of the old column is gone: a lane is always given
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tasks (id, title, number) VALUES ('t9', 'T9', 9)")

    command.downgrade(alembic_config(), "0029")
    with sqlite3.connect(db) as conn:
        assert "lanes" not in _tables(db)
        assert conn.execute("SELECT status, title FROM lane_titles").fetchall() == [
            ("done", "Shipped")
        ]
        statuses = dict(conn.execute("SELECT id, status FROM tasks"))
        assert statuses == {"t0": "backlog", "t1": "in_progress", "t2": "done"}  # t0 left 'review'
        with pytest.raises(sqlite3.IntegrityError):  # ck_tasks_status is back
            conn.execute("UPDATE tasks SET status = 'review' WHERE id = 't1'")

    command.upgrade(alembic_config(), "0030")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM lanes").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 3
