"""A lane has an id (uuid) and a name (its title); the key it was made from says nothing after a rename (ADR-090).

The owner's board: the lane that was made as ``in_progress`` is called *Must have*, ``done`` is *MVP*, a later lane called *DONE* got the key
``done_2``. An agent that took the keys for the meaning found 0 cards in *Must have* and *DONE*. Every interface now takes the name (or the id),
shows names, and an unknown lane is an error that lists the lanes, never an empty answer.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.engine import guard_views
from tests.helpers import alembic_config
from tests.test_integration import HEADERS, TOKEN
from tests.test_mcp import _call


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def _rename(api: TestClient, key: str, title: str) -> None:
    response = api.put(f"/api/lanes/{key}", json={"title": title})
    assert response.status_code == 200, response.text


def _board(api: TestClient) -> dict[str, dict[str, Any]]:
    """The owner's lanes, with a card or more in each: title -> {lane, cards}."""
    _rename(api, "backlog", "Optional")
    _rename(api, "in_progress", "Must have")
    _rename(api, "done", "MVP")
    assert api.post("/api/lanes", json={"title": "DONE"}).status_code == 201
    lanes = {lane["title"]: lane for lane in api.get("/api/lanes").json()}
    assert lanes["DONE"]["status"] == "done_2" and lanes["Must have"]["status"] == "in_progress"
    for title, how_many in (("Optional", 2), ("Must have", 3), ("MVP", 4), ("DONE", 1)):
        for n in range(how_many):
            created = api.post("/api/tasks", json={"title": f"{title} {n}", "status": title})
            assert created.status_code == 201, created.text
    return lanes


def _names(cards: list[dict[str, Any]]) -> list[str]:
    return sorted(c["title"] for c in cards)


def test_every_lane_has_a_uuid_and_a_rename_keeps_it(api: TestClient) -> None:
    before = {lane["status"]: lane["id"] for lane in api.get("/api/lanes").json()}
    assert len(set(before.values())) == 3 and all(len(i) == 36 for i in before.values())
    _rename(api, "in_progress", "Must have")
    after = {lane["status"]: lane["id"] for lane in api.get("/api/lanes").json()}
    assert after == before, "the id survives a rename, and so does the key"
    added = api.post("/api/lanes", json={"title": "Later"}).json()
    new = next(lane for lane in added if lane["title"] == "Later")
    assert len(new["id"]) == 36 and new["id"] not in before.values()


def test_the_owners_lanes_are_found_by_name_and_by_id_not_as_empty(api: TestClient) -> None:
    lanes = _board(api)
    for lane, expected in (("Must have", 3), ("MVP", 4), ("DONE", 1), ("Optional", 2)):
        failed, cards = _call(api, "list_artifacts", lane=lane, brief=True)
        assert not failed, cards
        assert len(cards) == expected, (lane, cards)
        failed, counted = _call(api, "count_artifacts", lane=lane)
        assert not failed and counted["total"] == expected and counted["lane"] == lane
        failed, by_id = _call(api, "list_artifacts", lane=lanes[lane]["id"], brief=True)
        assert not failed and _names(by_id) == _names(cards)
    failed, spaced = _call(api, "list_artifacts", lane="  must HAVE ", brief=True)
    assert not failed and len(spaced) == 3, "case and the spaces at the ends do not matter"
    failed, found = _call(api, "search_artifacts", query="Must have", lane="Must have")
    assert not failed and len(found) == 3
    failed, moved = _call(api, "count_artifacts", lane="MVP")
    assert not failed and moved["total"] == 4


def test_an_unknown_lane_is_an_error_that_lists_the_lanes_never_an_empty_answer(
    api: TestClient,
) -> None:
    _board(api)
    for tool, extra in (
        ("list_artifacts", {}),
        ("count_artifacts", {}),
        ("search_artifacts", {"query": "card"}),
        ("move_artifacts", {"artifacts": ["1"]}),
        ("create_artifact", {"title": "x"}),
        ("update_artifact", {"artifact": "1"}),
    ):
        failed, text = _call(api, tool, lane="in-progress", **extra)
        assert failed, (tool, text)
        assert "Unknown lane 'in-progress'" in text, (tool, text)
        assert "Lanes: Optional, Must have, MVP, DONE" in text, (tool, text)
    response = api.post("/api/tasks", json={"title": "x", "status": "nowhere"})
    assert response.status_code == 422
    assert "Unknown lane 'nowhere'. Lanes: Optional, Must have, MVP, DONE" in response.text


def test_the_tools_show_names_and_ids_and_nothing_of_the_old_keys(api: TestClient) -> None:
    lanes = _board(api)
    failed, listed = _call(api, "list_lanes")
    assert not failed
    assert [lane["name"] for lane in listed] == ["Optional", "Must have", "MVP", "DONE"]
    for lane in listed:
        assert set(lane) == {"name", "id", "style", "artifact_count", "position", "deletable"}, lane
        assert lane["id"] == lanes[lane["name"]]["id"]
    failed, brief = _call(api, "list_artifacts", lane="Must have", brief=True)
    assert not failed
    assert {c["lane"] for c in brief} == {"Must have"}
    assert {c["lane_id"] for c in brief} == {lanes["Must have"]["id"]}
    failed, full = _call(api, "get_artifact", artifact=str(brief[0]["number"]))
    assert not failed
    assert full["lane"] == "Must have" and full["lane_id"] == lanes["Must have"]["id"]
    assert "status" not in full and "lane_name" not in full
    assert "in_progress" not in str(brief) and "in_progress" not in str(full)
    failed, created = _call(api, "create_artifact", title="By id", lane=lanes["DONE"]["id"])
    assert not failed and created["lane"] == "DONE"
    failed, updated = _call(api, "update_artifact", artifact=str(created["number"]), lane="MVP")
    assert not failed and updated["lane"] == "MVP"


def test_move_artifacts_takes_a_name_or_an_id_and_says_where_to(api: TestClient) -> None:
    lanes = _board(api)
    failed, answer = _call(api, "move_artifacts", artifacts=["1", "2"], lane="Must have")
    assert not failed, answer
    assert [r["to"] for r in answer["results"]] == ["Must have", "Must have"]
    failed, counted = _call(api, "count_artifacts", lane="Must have")
    assert counted["total"] == 5
    failed, answer = _call(api, "move_artifacts", artifacts=["1"], lane=lanes["DONE"]["id"])
    assert not failed and answer["results"][0]["to"] == "DONE"


def test_the_rest_interface_keeps_its_fields_and_takes_the_new_forms(api: TestClient) -> None:
    lanes = _board(api)
    card = api.get("/api/tasks").json()[0]
    assert {"status", "lane_name", "lane_id"} <= set(card)
    assert card["status"] == "backlog" and card["lane_name"] == "Optional"
    assert card["lane_id"] == lanes["Optional"]["id"]
    by_key = api.post("/api/tasks", json={"title": "by key", "status": "in_progress"})
    by_id = api.post("/api/tasks", json={"title": "by id", "status": lanes["MVP"]["id"]})
    by_name = api.post("/api/tasks", json={"title": "by name", "status": "must HAVE"})
    assert [r.status_code for r in (by_key, by_id, by_name)] == [201, 201, 201]
    assert by_key.json()["status"] == "in_progress" and by_id.json()["status"] == "done"
    assert by_name.json()["status"] == "in_progress", "the name was turned into the storage key"
    moved = api.patch(f"/api/tasks/{by_key.json()['id']}", json={"status": "DONE"})
    assert moved.status_code == 200 and moved.json()["status"] == "done_2"
    assert moved.json()["lane_name"] == "DONE"
    bad = api.patch(f"/api/tasks/{by_key.json()['id']}", json={"status": "in-progress"})
    assert bad.status_code == 422 and "Lanes: Optional, Must have, MVP, DONE" in bad.text
    integration = api.get("/api/v1/artifacts").json()
    assert all("lane_name" in c and "lane_id" in c for c in integration)


def test_a_lane_in_a_path_is_taken_by_name_id_or_key(api: TestClient) -> None:
    lanes = _board(api)
    renamed = api.put(f"/api/lanes/{lanes['MVP']['id']}", json={"title": "Shipped"})
    assert renamed.status_code == 200, renamed.text
    assert "Shipped" in [lane["title"] for lane in renamed.json()]
    again = api.put("/api/lanes/Shipped", json={"title": "MVP"})
    assert again.status_code == 200, again.text
    unknown = api.put("/api/lanes/nowhere", json={"title": "x"})
    assert unknown.status_code == 404


def test_a_name_beats_an_id_beats_an_old_key(api: TestClient) -> None:
    """A lane can be called what another lane's old key is: the name wins (the order is name, id, key)."""
    _rename(api, "done", "Shipped")  # the lane with the key ``done`` is called Shipped now
    _rename(
        api, "backlog", "done"
    )  # the lane made as backlog is called ``done``: the key of another lane
    lanes = {lane["status"]: lane for lane in api.get("/api/lanes").json()}
    assert lanes["backlog"]["title"] == "done" and lanes["done"]["title"] == "Shipped"
    created = api.post("/api/tasks", json={"title": "x", "status": "done"})
    assert created.status_code == 201
    assert created.json()["status"] == "backlog", "the name won over the old key of the other lane"
    by_id = api.post("/api/tasks", json={"title": "y", "status": lanes["done"]["id"]})
    assert by_id.json()["status"] == "done", "its id still reaches that other lane"


def test_the_web_page_never_shows_a_lane_id(api: TestClient) -> None:
    lanes = _board(api)
    page = api.get("/", headers={"Accept": "text/html"})
    assert page.status_code == 200
    for lane in lanes.values():
        assert lane["id"] not in page.text


# ── the migration ────────────────────────────────────────────────────


def test_migration_0069_gives_every_lane_a_uuid_and_loses_nothing(
    at_revision: Callable[[str], Any],
) -> None:
    path = at_revision("0068")
    guard_views.install(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, status, position, number) VALUES ('t1', 'T', 'done', 1, 1)"
        )
        before = conn.execute("SELECT key, title FROM lanes ORDER BY position").fetchall()
    command.upgrade(alembic_config(), "0069")
    guard_views.install(path)
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT key, title, uuid FROM lanes ORDER BY position").fetchall()
        assert [(k, t) for k, t, _ in rows] == before, "no lane was lost or changed"
        ids = [u for _, _, u in rows]
        assert all(len(u) == 36 for u in ids) and len(set(ids)) == len(ids)
        assert conn.execute("SELECT id FROM tasks").fetchall() == [("t1",)], (
            "the card is still there"
        )
        assert conn.execute("SELECT COUNT(*) FROM v_guard_lanes").fetchall() == [(len(rows),)]
        assert conn.execute("SELECT COUNT(*) FROM v_guard_artifacts").fetchall() == [(1,)]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE lanes SET uuid = ?", (ids[0],))
    command.downgrade(alembic_config(), "0068")
    with sqlite3.connect(path) as conn:
        assert "uuid" not in [r[1] for r in conn.execute("PRAGMA table_info(lanes)")]
        assert conn.execute("SELECT key, title FROM lanes ORDER BY position").fetchall() == before
        assert conn.execute("SELECT id FROM tasks").fetchall() == [("t1",)]
    command.upgrade(alembic_config(), "head")


def test_migration_0069_is_not_disturbed_by_the_empty_copy_a_failed_start_left_behind(
    at_revision: Callable[[str], Any],
) -> None:
    path = at_revision("0068")
    guard_views.install(path)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE _alembic_tmp_lanes (key VARCHAR(32) PRIMARY KEY)")
    command.upgrade(alembic_config(), "0069")
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM lanes WHERE uuid != ''").fetchone()[0] == 3


def test_a_key_the_web_page_sends_is_not_taken_for_another_lanes_title(api: TestClient) -> None:
    """The web page sends the old key of the lane a card is dropped on. The lane made as ``done`` is titled MVP and another lane is titled
    DONE (key ``done_2``): dropping a card on MVP must put it in MVP, not in the lane whose title only looks like the key."""
    lanes = _board(api)
    card = api.post("/api/tasks", json={"title": "Dropped", "status": "Optional"}).json()
    moved = api.patch(f"/api/tasks/{card['id']}", json={"status": "done"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == lanes["MVP"]["status"] == "done"
    by_title = api.patch(f"/api/tasks/{card['id']}", json={"status": "DONE"})
    assert by_title.json()["status"] == lanes["DONE"]["status"] == "done_2", (
        "the title as typed still works"
    )
    lowercase_title = api.patch(f"/api/tasks/{card['id']}", json={"status": "must have"})
    assert lowercase_title.json()["status"] == "in_progress", (
        "a title with another case still works"
    )
