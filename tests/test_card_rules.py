"""Card rules (ADR-071): the rule model, the time facts, the marks, conflicts, archive and delete with their safeguards, the API,
and migration 0058 (including the lanes that drew their cards as finished)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.tasks.card_rules import Rule
from tests.helpers import alembic_config

TOKEN = "cards-token-" + "x" * 30
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}
DAY = 86400


def when(field: str, op: str, value: Any) -> dict[str, Any]:
    return {
        "type": "group",
        "mode": "all",
        "items": [{"type": "condition", "field": field, "op": op, "value": value}],
    }


def rule(action: str, condition: dict[str, Any] | None = None, **params: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"action": action, "params": params}
    if condition is not None:
        body["when"] = condition
    return body


@pytest.fixture
def db(migrated_settings: Settings) -> Path:
    return migrated_settings.data_dir / migrated_settings.database_filename


@pytest.fixture
def client(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(
        update={"api_token": TOKEN, "secret_key": "k" * 40, "card_sweep_interval_seconds": 0}
    )
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def card(client: TestClient, title: str, lane: str = "backlog", **extra: Any) -> dict[str, Any]:
    reply = client.post("/api/tasks", json={"title": title, "status": lane, **extra})
    assert reply.status_code == 201, reply.text
    return cast(dict[str, Any], reply.json())


def age(db: Path, task_id: str, days: float, *, moved: float | None = None) -> None:
    """Make a card ``days`` old; its last move (activity of kind lane/created) is ``moved`` days ago (default: as old)."""
    then: Callable[[float], str] = lambda d: (datetime.now(UTC) - timedelta(days=d)).strftime(  # noqa: E731
        "%Y-%m-%d %H:%M:%S.%f"
    )
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE tasks SET created_at = ?, updated_at = ? WHERE id = ?",
            (then(days), then(days), task_id),
        )
        conn.execute("DELETE FROM task_activity WHERE task_id = ?", (task_id,))
        if moved is not None:
            conn.execute(
                "INSERT INTO task_activity (id, task_id, kind, actor_kind, actor_name, data, created_at) "
                "VALUES (?, ?, 'lane', 'user', 'You', '{}', ?)",
                (f"a-{task_id}", task_id, then(moved)),
            )


def put_lane(client: TestClient, lane: str, *rules: dict[str, Any]) -> Any:
    return client.put(f"/api/lanes/{lane}/rules", json={"rules": list(rules)})


def put_board(client: TestClient, *rules: dict[str, Any]) -> Any:
    return client.put("/api/board/rules", json={"rules": list(rules)})


def visible(client: TestClient, **query: Any) -> dict[str, dict[str, Any]]:
    return {t["title"]: t for t in client.get("/api/tasks", params=query).json()}


# ── the rule model ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"action": "explode"}, "unknown action"),
        ({"action": "label", "params": {"tone": "red"}}, "label: give a text"),
        ({"action": "label", "params": {"text": "x" * 25, "tone": "red"}}, "label: give a text"),
        ({"action": "label", "params": {"text": "Old", "tone": "pink"}}, "tone is one of"),
        ({"action": "colour", "params": {"tone": "#ff0000"}}, "tone is one of"),
        ({"action": "colour", "params": {"tone": "red", "mode": "glow"}}, "mode is one of"),
        ({"action": "archive", "params": {"days": 3}}, "unknown parameter 'days'"),
        ({"action": "delete"}, "give at least one condition"),
    ],
)
def test_a_rule_that_does_not_fit_is_refused_with_its_reason(
    body: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Rule.model_validate(body)


def test_a_condition_names_a_known_field_and_a_fitting_operator() -> None:
    with pytest.raises(ValidationError, match="unknown field"):
        Rule.model_validate({"action": "archive", "when": when("colour", "is", "red")})
    with pytest.raises(ValidationError, match="does not fit"):
        Rule.model_validate({"action": "archive", "when": when("in_lane", "contains", "x")})


def test_delete_is_off_until_it_is_switched_on_and_the_others_are_on() -> None:
    assert (
        Rule.model_validate(
            {"action": "delete", "when": when("archived_for", "at_least", DAY)}
        ).enabled
        is False
    )
    assert Rule.model_validate({"action": "archive"}).enabled is True


def test_the_schemas_endpoint_describes_lane_and_board_rules(client: TestClient) -> None:
    schemas = {s["purpose"]: s for s in client.get("/api/rules/schemas").json()}
    lane = {c["key"] for c in schemas["lane"]["consequences"]}
    board = {c["key"] for c in schemas["board"]["consequences"]}
    assert lane == {"set_done", "archive", "label", "colour"}
    assert board == {"archive", "delete", "label", "colour"}  # set_done only on a lane
    assert not schemas["lane"]["planned"]
    fields = {f["key"] for f in schemas["board"]["fields"]}
    assert {
        "lane",
        "in_lane",
        "idle",
        "age",
        "archived_for",
        "title",
        "body",
        "has_parent",
        "field.",
    } <= fields


def test_a_lane_does_not_offer_delete_and_the_board_does_not_offer_set_done(
    client: TestClient,
) -> None:
    refused = put_lane(client, "done", rule("delete", when("title", "contains", "x")))
    assert refused.status_code == 422 and "not 'delete'" in refused.text
    refused = put_board(client, rule("set_done"))
    assert refused.status_code == 422 and "not 'set_done'" in refused.text
    assert put_lane(client, "nowhere").status_code == 404
    assert client.get("/api/lanes/nowhere/rules").status_code == 404


# ── marks ─────────────────────────────────────────────────────────────


def test_set_as_done_without_a_condition_marks_every_card_of_the_lane_and_the_style_follows(
    client: TestClient,
) -> None:
    inside, outside = card(client, "In", "done"), card(client, "Out", "backlog")
    assert put_lane(client, "done", rule("set_done")).status_code == 200
    cards = visible(client)
    assert cards["In"]["marks"]["done"] is True
    assert cards["Out"]["marks"] is None
    assert client.get(f"/api/tasks/{inside['id']}").json()["marks"]["done"] is True
    styles = {lane["status"]: lane["style"] for lane in client.get("/api/lanes").json()}
    assert styles["done"] == "finished" and styles["backlog"] == "normal"
    assert outside["id"]
    put_lane(client, "done")  # no rules
    assert visible(client)["In"]["marks"] is None
    assert {x["status"]: x["style"] for x in client.get("/api/lanes").json()}["done"] == "normal"


def test_the_old_style_switch_is_the_rule_set_as_done(client: TestClient) -> None:
    client.put("/api/lanes/backlog", json={"style": "finished"}).raise_for_status()
    stored = client.get("/api/lanes/backlog/rules").json()["rules"]
    assert [(r["action"], r["when"]["items"]) for r in stored] == [("set_done", [])]
    client.put("/api/lanes/backlog", json={"style": "normal"}).raise_for_status()
    assert client.get("/api/lanes/backlog/rules").json()["rules"] == []


def test_a_rule_with_a_condition_set_as_done_only_holds_while_it_does(
    client: TestClient, db: Path
) -> None:
    old, new = card(client, "Old"), card(client, "New")
    age(db, old["id"], 10, moved=10)
    put_lane(client, "backlog", rule("set_done", when("in_lane", "at_least", 7 * DAY)))
    cards = visible(client)
    assert cards["Old"]["marks"]["done"] is True
    assert cards["New"]["marks"] is None
    assert new["id"]


def test_time_in_the_lane_counts_from_the_last_move_not_from_the_creation(
    client: TestClient, db: Path
) -> None:
    moved = card(client, "Moved")
    age(db, moved["id"], 30, moved=1)  # created a month ago, in this lane since yesterday
    put_lane(
        client,
        "backlog",
        rule("label", when("in_lane", "at_least", 7 * DAY), text="Stuck", tone="red"),
    )
    assert visible(client)["Moved"]["marks"] is None
    age(db, moved["id"], 30, moved=8)
    assert visible(client)["Moved"]["marks"]["labels"] == [{"text": "Stuck", "tone": "red"}]


def test_a_move_through_the_api_restarts_the_time_in_the_lane(client: TestClient, db: Path) -> None:
    c = card(client, "Walker")
    age(db, c["id"], 20)
    put_board(
        client, rule("label", when("in_lane", "at_least", 7 * DAY), text="Long", tone="yellow")
    )
    assert visible(client)["Walker"]["marks"]["labels"]
    client.patch(f"/api/tasks/{c['id']}", json={"status": "in_progress"}).raise_for_status()
    assert visible(client)["Walker"]["marks"] is None


def test_the_last_activity_counts_comments_and_changes(client: TestClient, db: Path) -> None:
    quiet, chatty = card(client, "Quiet"), card(client, "Chatty")
    for c in (quiet, chatty):
        age(db, c["id"], 20, moved=20)
    client.post(
        f"/api/tasks/{chatty['id']}/comments", json={"body": "still here"}
    ).raise_for_status()
    put_board(client, rule("colour", when("idle", "at_least", 14 * DAY), tone="red", mode="border"))
    cards = visible(client)
    assert cards["Quiet"]["marks"]["colour"] == {"tone": "red", "mode": "border"}
    assert cards["Chatty"]["marks"] is None


def test_age_title_text_parent_and_artifact_fields_are_conditions(
    client: TestClient, db: Path
) -> None:
    client.put(
        "/api/artifact-fields", json={"fields": [{"name": "prio", "label": "Prio", "kind": "text"}]}
    ).raise_for_status()
    parent = card(client, "Epic")
    child = card(
        client, "Fix the bug", parent_id=parent["id"], body="urgent!", fields={"prio": "high"}
    )
    age(db, child["id"], 40)
    for field, op, value in [
        ("age", "at_least", 30 * DAY),
        ("title", "contains", "bug"),
        ("body", "contains", "URGENT"),
        ("has_parent", "is", "yes"),
        ("field.prio", "is", "high"),
        ("lane", "is", "backlog"),
    ]:
        put_board(client, rule("label", when(field, op, value), text="Hit", tone="blue"))
        cards = visible(client)
        assert cards["Fix the bug"]["marks"], field
        assert not cards["Epic"]["marks"] or field in ("lane",), field


def test_conflicts_labels_add_up_the_first_colour_wins_and_the_lane_comes_before_the_board(
    client: TestClient,
) -> None:
    card(client, "Plain")
    put_board(
        client,
        rule("colour", None, tone="green"),
        rule("label", None, text="Board", tone="blue"),
        rule("label", None, text="Dup", tone="neutral"),
    )
    put_lane(
        client,
        "backlog",
        rule("label", None, text="Dup", tone="neutral"),
        rule("colour", None, tone="red", mode="border"),
        rule("colour", None, tone="yellow"),
        rule("set_done"),
    )
    marks = visible(client)["Plain"]["marks"]
    assert marks["done"] is True
    assert marks["colour"] == {
        "tone": "red",
        "mode": "border",
    }  # the lane's first, not the board's green
    assert marks["labels"] == [
        {"text": "Dup", "tone": "neutral"},
        {"text": "Board", "tone": "blue"},
    ]  # the same label once


def test_a_rule_that_is_off_says_nothing(client: TestClient) -> None:
    card(client, "Plain")
    put_lane(client, "backlog", {**rule("label", None, text="No", tone="red"), "enabled": False})
    assert visible(client)["Plain"]["marks"] is None


def test_the_marks_of_many_cards_take_a_few_grouped_queries(client: TestClient) -> None:
    from sqlalchemy import event

    from openartifact import database

    for n in range(60):
        card(client, f"C{n}")
    put_board(client, rule("label", when("idle", "at_least", 3600), text="Old", tone="red"))
    statements: list[str] = []
    sync = database._engine.sync_engine  # type: ignore[union-attr]

    def count(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        statements.append(statement)

    event.listen(sync, "before_cursor_execute", count)
    try:
        assert len(visible(client)) == 60
    finally:
        event.remove(sync, "before_cursor_execute", count)
    assert len(statements) < 15, "not one set of queries per card"


# ── archive ───────────────────────────────────────────────────────────


def test_a_lane_rule_archives_cards_that_have_been_there_too_long_and_a_move_makes_them_visible(
    client: TestClient, db: Path
) -> None:
    old, fresh = card(client, "Old"), card(client, "Fresh")
    age(db, old["id"], 30, moved=30)
    answer = put_lane(client, "backlog", rule("archive", when("in_lane", "at_least", 14 * DAY)))
    assert answer.status_code == 200
    assert set(visible(client)) == {"Fresh"}
    assert set(visible(client, archived="include")) == {"Old", "Fresh"}
    one = client.get(f"/api/tasks/{old['id']}").json()  # a single card stays readable
    assert one["archived_at"] is not None
    assert client.get(f"/api/tasks/%23{old['number']}").json()["title"] == "Old"
    assert fresh["id"]
    assert (
        client.patch(f"/api/tasks/{old['id']}", json={"status": "in_progress"}).status_code == 409
    )  # read-only
    client.post(f"/api/tasks/{old['id']}/unarchive").raise_for_status()  # the way back
    back = visible(client)["Old"]
    assert back["archived_at"] is None
    kinds = [a["kind"] for a in client.get(f"/api/tasks/{old['id']}/activity").json()["items"]]
    assert "archived" in kinds


def test_archiving_is_not_a_sign_of_life(client: TestClient, db: Path) -> None:
    c = card(client, "Dusty")
    age(db, c["id"], 30, moved=30)
    put_board(client, rule("archive", when("idle", "at_least", 14 * DAY)))
    got = client.get(f"/api/tasks/{c['id']}").json()
    assert got["archived_at"] is not None
    assert datetime.fromisoformat(got["updated_at"]) < datetime.now(UTC) - timedelta(days=29)


def test_the_integration_api_and_mcp_leave_archived_cards_out_by_default(
    client: TestClient, db: Path
) -> None:
    c = card(client, "Gone")
    card(client, "Here")
    age(db, c["id"], 30, moved=30)
    put_lane(client, "backlog", rule("archive", when("title", "is", "Gone")))
    assert [a["title"] for a in client.get("/api/v1/artifacts").json()] == ["Here"]
    both = client.get("/api/v1/artifacts", params={"archived": "include"}).json()
    assert {a["title"] for a in both} == {"Here", "Gone"}


def test_the_rules_are_applied_by_the_sweeper_too(client: TestClient, db: Path) -> None:
    c = card(client, "Later")
    put_lane(client, "backlog", rule("archive", when("in_lane", "at_least", 14 * DAY)))
    assert "Later" in visible(client)
    age(db, c["id"], 20, moved=20)  # time passes, nothing is saved
    assert "Later" in visible(client)
    assert (
        client.post("/api/board/rules/sweep").json()["archive"] == 1
    )  # what the sweeper does every few minutes
    assert "Later" not in visible(client)


# ── delete ────────────────────────────────────────────────────────────


def archived(client: TestClient, db: Path, title: str, days: float, **extra: Any) -> dict[str, Any]:
    c = card(client, title, **extra)
    age(db, c["id"], days + 1, moved=days + 1)
    with sqlite3.connect(db) as conn:
        then = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S.%f")
        conn.execute("UPDATE tasks SET archived_at = ? WHERE id = ?", (then, c["id"]))
    return c


DELETE = {**rule("delete", when("archived_for", "at_least", 14 * DAY)), "enabled": True}


def test_delete_needs_a_condition_and_is_off_when_not_said_otherwise(
    client: TestClient, db: Path
) -> None:
    refused = put_board(client, rule("delete"))
    assert refused.status_code == 422 and "give at least one condition" in refused.text
    stored = put_board(client, rule("delete", when("archived_for", "at_least", DAY))).json()[
        "rules"
    ][0]
    assert stored["enabled"] is False
    archived(client, db, "Old news", 30)
    assert client.post("/api/board/rules/sweep").json()["delete"] == 0


def test_delete_removes_only_archived_cards_that_have_been_archived_long_enough_and_logs_it(
    client: TestClient, db: Path
) -> None:
    long_ago, recent = archived(client, db, "Long ago", 30), archived(client, db, "Recent", 3)
    visible_card = card(client, "Visible")
    age(db, visible_card["id"], 90, moved=90)  # old, but not archived: never deleted
    put_board(client, DELETE)
    titles = {t["title"] for t in client.get("/api/tasks", params={"archived": "include"}).json()}
    assert titles == {"Recent", "Visible"}
    assert client.get(f"/api/tasks/{long_ago['id']}").status_code == 404
    assert recent["id"]
    log = client.get("/api/board/rules/deletions").json()
    assert [(e["number"], e["title"]) for e in log] == [(long_ago["number"], "Long ago")]


def test_delete_spares_cards_with_children_and_a_running_run_and_says_why(
    client: TestClient, db: Path
) -> None:
    parent = archived(client, db, "Parent", 30)
    archived(client, db, "Child", 30, parent_id=parent["id"])
    busy = archived(client, db, "Busy", 30)
    with sqlite3.connect(db) as conn:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(pipeline_runs)")]
        assert "task_id" in columns
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO pipeline_runs (id, task_id, status, started_by, snapshot, created_at, updated_at) VALUES ('run1', ?, 'running', 'user', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (busy["id"],),
        )
    preview = client.post("/api/board/rules/preview", json={"rule": DELETE}).json()
    assert preview["count"] == 1  # the child
    assert {s["title"]: s["why"] for s in preview["spared"]} == {
        "Parent": "it has child cards",
        "Busy": "it is being processed",
    }
    put_board(client, DELETE)
    left = {t["title"] for t in client.get("/api/tasks", params={"archived": "include"}).json()}
    assert left == {"Parent", "Busy"}


def test_a_dry_run_changes_nothing_and_says_what_it_would_do(client: TestClient, db: Path) -> None:
    archived(client, db, "Old news", 30)
    put_board(client, {**DELETE, "enabled": False})
    client.put("/api/board/rules", json={"rules": [DELETE]}).raise_for_status()
    # the save already swept; make another one to look at
    archived(client, db, "More news", 30)
    dry = client.post("/api/board/rules/sweep", params={"dry_run": "true"}).json()
    assert dry == {"archive": 0, "delete": 1, "spared": 0, "dry_run": True}
    assert "More news" in {
        t["title"] for t in client.get("/api/tasks", params={"archived": "include"}).json()
    }


def test_a_preview_counts_what_a_rule_of_a_lane_would_hit(client: TestClient, db: Path) -> None:
    old = card(client, "Old")
    card(client, "New")
    other = card(client, "Elsewhere", "in_progress")
    for c in (old, other):
        age(db, c["id"], 20, moved=20)
    body = {"rule": rule("archive", when("in_lane", "at_least", 7 * DAY))}
    found = client.post("/api/lanes/backlog/rules/preview", json=body).json()
    assert found["count"] == 1 and [c["title"] for c in found["cards"]] == ["Old"]
    assert client.post("/api/board/rules/preview", json=body).json()["count"] == 2
    assert visible(client).keys() == {"Old", "New", "Elsewhere"}  # a preview changes nothing


def test_events_tell_the_page_that_rules_and_cards_changed(client: TestClient, db: Path) -> None:
    seen: list[str] = []
    bus = client.app.state.event_bus  # type: ignore[attr-defined]
    original = bus.publish
    bus.publish = lambda name, data=None: (seen.append(name), original(name, data))[1]  # type: ignore[func-returns-value]
    c = card(client, "Old")
    age(db, c["id"], 30, moved=30)
    put_lane(client, "backlog", rule("archive", when("in_lane", "at_least", DAY)))
    assert {"cards.rules.changed", "board.updated", "board.resync", "board.lanes"} <= set(seen)


# ── migration 0058 ────────────────────────────────────────────────────


def test_migration_0058_gives_finished_lanes_their_rule_and_goes_down_again(
    at_revision: Callable[[str], Path],
) -> None:
    path = at_revision("0057")
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE lanes SET style = 'finished' WHERE key = 'done'")
        conn.execute(
            "INSERT INTO tasks (id, title, status, position, number) VALUES ('t1', 'T', 'done', 0, 1)"
        )
    command.upgrade(alembic_config(), "0058")
    with sqlite3.connect(path) as conn:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(tasks)")]
        assert "archived_at" in columns
        assert conn.execute("SELECT archived_at FROM tasks WHERE id = 't1'").fetchone() == (None,)
        stored = json.loads(
            conn.execute("SELECT value FROM app_settings WHERE key = 'cards.rules'").fetchone()[0]
        )
    assert list(stored["lanes"]) == ["done"]
    [only] = stored["lanes"]["done"]
    assert only["action"] == "set_done" and only["when"]["items"] == [] and only["enabled"] is True
    assert stored["board"] == []
    command.downgrade(alembic_config(), "0057")
    with sqlite3.connect(path) as conn:
        assert "archived_at" not in [r[1] for r in conn.execute("PRAGMA table_info(tasks)")]
        assert conn.execute("SELECT title FROM tasks WHERE id = 't1'").fetchone() == ("T",)
    command.upgrade(alembic_config(), "0058")  # up again with data


def test_migration_0058_without_a_finished_lane_stores_no_rules(
    at_revision: Callable[[str], Path],
) -> None:
    path = at_revision("0057")
    command.upgrade(alembic_config(), "0058")
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute("SELECT value FROM app_settings WHERE key = 'cards.rules'").fetchone()
            is None
        )


# ── the archive: by hand, back again, read-only (ADR-071) ─────────────


def test_archiving_by_hand_remembers_the_lane_and_unarchiving_puts_the_card_on_top(
    client: TestClient,
) -> None:
    first, second = card(client, "First", "in_progress"), card(client, "Second", "in_progress")
    gone = client.post(f"/api/tasks/{second['id']}/archive")
    assert gone.status_code == 200
    body = gone.json()
    assert body["archived_at"] and body["archived_from_status"] == "in_progress"
    assert body["archived_from_lane"] == "In Progress"
    assert set(visible(client)) == {"First"}
    # the card meanwhile lost its place: put another one on top, then take it back
    back = client.post(f"/api/tasks/{second['id']}/unarchive").json()
    assert (
        back["status"] == "in_progress"
        and back["archived_at"] is None
        and back["archived_from_status"] is None
    )
    order = [t["title"] for t in client.get("/api/tasks").json() if t["status"] == "in_progress"]
    assert order == ["Second", "First"]  # the very top: the smallest position
    assert (
        back["position"] < first["position"]
        or back["position"] < visible(client)["First"]["position"]
    )
    assert (
        client.post(f"/api/tasks/{second['id']}/unarchive").status_code == 409
    )  # not archived any more


def test_a_card_comes_back_to_the_first_lane_when_its_lane_is_gone(
    client: TestClient, db: Path
) -> None:
    c = card(client, "Wanderer", "in_progress")
    client.post(f"/api/tasks/{c['id']}/archive").raise_for_status()
    assert (
        client.delete("/api/lanes/in_progress").status_code == 409
    )  # a lane that holds an archived card stays
    with sqlite3.connect(db) as conn:  # the lane is gone anyway (an older backup, an edit by hand)
        conn.execute("UPDATE tasks SET archived_from_status = 'vanished' WHERE id = ?", (c["id"],))
    shown = client.get(f"/api/tasks/{c['id']}").json()
    assert shown["archived_from_status"] == "vanished" and shown["archived_from_lane"] is None
    back = client.post(f"/api/tasks/{c['id']}/unarchive").json()
    assert back["status"] == client.get("/api/lanes").json()[0]["status"]


def test_an_archived_card_is_read_only_and_says_archived(client: TestClient) -> None:
    c = card(client, "Frozen")
    child = card(client, "Child", parent_id=c["id"])
    client.post(f"/api/tasks/{c['id']}/archive").raise_for_status()
    refused = [
        client.patch(f"/api/tasks/{c['id']}", json={"title": "New"}),
        client.patch(f"/api/tasks/{c['id']}", json={"status": "done"}),
        client.patch(f"/api/tasks/{c['id']}", json={"fields": {}}),
        client.post(f"/api/tasks/{c['id']}/comments", json={"body": "hi"}),
        client.delete(f"/api/tasks/{c['id']}"),
        client.post(f"/api/tasks/{c['id']}/archive"),
        client.post(f"/api/v1/artifacts/{c['id']}/run"),
        client.delete(f"/api/v1/artifacts/{c['id']}"),
    ]
    assert [r.status_code for r in refused] == [409] * len(refused), [r.text for r in refused]
    assert all("archived" in r.text for r in refused)
    assert (
        client.get(f"/api/tasks/{c['id']}").json()["title"] == "Frozen"
    )  # read, and its comments and history too
    assert client.get(f"/api/tasks/{c['id']}/comments").status_code == 200
    assert client.get(f"/api/tasks/{c['id']}/activity").status_code == 200
    # an archived parent: the child stays on the board and keeps the link to it
    shown = visible(client)
    assert set(shown) == {"Child"} and shown["Child"]["parent_id"] == c["id"]
    assert child["id"]


def test_a_card_that_is_being_processed_cannot_be_archived(client: TestClient, db: Path) -> None:
    busy = card(client, "Busy")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO pipeline_runs (id, task_id, status, started_by, snapshot, created_at, updated_at) "
            "VALUES ('r1', ?, 'running', 'user', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (busy["id"],),
        )
    assert client.post(f"/api/tasks/{busy['id']}/archive").status_code == 409
    put_board(client, rule("archive", when("title", "is", "Busy")))  # a rule leaves it alone too
    assert visible(client)["Busy"]["archived_at"] is None


def test_a_rule_remembers_the_lane_too(client: TestClient, db: Path) -> None:
    c = card(client, "Old", "in_progress")
    age(db, c["id"], 30, moved=30)
    put_lane(client, "in_progress", rule("archive", when("in_lane", "at_least", 14 * DAY)))
    got = client.get(f"/api/tasks/{c['id']}").json()
    assert got["archived_from_status"] == "in_progress"
    assert client.post(f"/api/tasks/{c['id']}/unarchive").json()["status"] == "in_progress"
    # back in the lane it counts from now, so the rule does not take it away again at once
    assert "Old" in visible(client)
    assert client.post("/api/board/rules/sweep").json()["archive"] == 0


def test_the_archive_list_filters_sorts_and_pages(client: TestClient, db: Path) -> None:
    for title in ("Bravo", "alpha", "Charlie"):
        c = card(client, title)
        client.post(f"/api/tasks/{c['id']}/archive").raise_for_status()
        with sqlite3.connect(db) as conn:  # a distinct, known order of archiving
            at = datetime.now(UTC) - timedelta(days={"Bravo": 3, "alpha": 2, "Charlie": 1}[title])
            conn.execute(
                "UPDATE tasks SET archived_at = ? WHERE id = ?",
                (at.strftime("%Y-%m-%d %H:%M:%S.%f"), c["id"]),
            )
    card(client, "On the board")
    titles: Callable[..., list[str]] = lambda **q: [  # noqa: E731
        t["title"] for t in client.get("/api/tasks", params=q).json()
    ]
    assert titles() == ["On the board"]
    assert titles(archived="only") == ["Charlie", "alpha", "Bravo"]  # newest archived first
    assert titles(archived="only", sort="archived_at", order="asc") == ["Bravo", "alpha", "Charlie"]
    assert titles(archived="only", sort="title") == ["alpha", "Bravo", "Charlie"]
    assert titles(archived="only", sort="title", order="desc") == ["Charlie", "Bravo", "alpha"]
    assert set(titles(archived="include")) == {"On the board", "alpha", "Bravo", "Charlie"}
    page = client.get("/api/tasks", params={"archived": "only", "limit": 2, "offset": 2})
    assert [t["title"] for t in page.json()] == ["Bravo"] and page.headers["X-Total-Count"] == "3"
    assert client.get("/api/tasks", params={"archived": "sometimes"}).status_code == 422
    assert {
        a["title"] for a in client.get("/api/v1/artifacts", params={"archived": "only"}).json()
    } == {"alpha", "Bravo", "Charlie"}


def test_a_board_rule_may_delete_an_archived_card_although_the_user_may_not(
    client: TestClient, db: Path
) -> None:
    old = archived(client, db, "Archived long ago", 30)
    assert client.delete(f"/api/tasks/{old['id']}").status_code == 409
    put_board(client, DELETE)
    assert client.get(f"/api/tasks/{old['id']}").status_code == 404


def test_migration_0058_adds_the_lane_it_was_archived_from(
    at_revision: Callable[[str], Path],
) -> None:
    path = at_revision("0057")
    command.upgrade(alembic_config(), "0058")
    with sqlite3.connect(path) as conn:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(tasks)")]
        assert {"archived_at", "archived_from_status"} <= set(columns)
    command.downgrade(alembic_config(), "0057")
    with sqlite3.connect(path) as conn:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(tasks)")]
        assert not {"archived_at", "archived_from_status"} & set(columns)


# ── archived children (ADR-095 add.1) ─────────────────────────────────


def test_a_card_counts_its_archived_direct_children_and_archiving_or_restoring_changes_it(
    client: TestClient,
) -> None:
    epic = card(client, "Epic")
    work = card(client, "Work package", parent_id=epic["id"])
    task = card(client, "Task", parent_id=work["id"])  # a grandchild of the epic
    other = card(client, "Other", parent_id=epic["id"])
    assert visible(client)["Epic"]["archived_children"] == 0
    client.post(f"/api/tasks/{other['id']}/archive").raise_for_status()
    client.post(f"/api/tasks/{task['id']}/archive").raise_for_status()
    board = visible(client)
    assert board["Epic"]["archived_children"] == 1  # the direct child only, not the grandchild
    assert board["Work package"]["archived_children"] == 1
    assert client.get(f"/api/tasks/{epic['id']}").json()["archived_children"] == 1
    assert client.get(f"/api/tasks/{epic['number']}").json()["archived_children"] == 1
    back = client.post(f"/api/tasks/{other['id']}/unarchive")
    assert back.json()["archived_children"] == 0  # the card read after a save carries it as well
    assert visible(client)["Epic"]["archived_children"] == 0
    assert client.get(f"/api/tasks/{work['id']}").json()["archived_children"] == 1


def test_the_archive_list_can_be_asked_for_the_children_of_one_card(client: TestClient) -> None:
    epic, other_epic = card(client, "Epic"), card(client, "Other epic")
    first = card(client, "First", parent_id=epic["id"])
    second = card(client, "Second", parent_id=epic["id"])
    stranger = card(client, "Stranger", parent_id=other_epic["id"])
    live = card(client, "Live", parent_id=epic["id"])  # on the board: not an archived child
    for archived in (first, second, stranger):
        client.post(f"/api/tasks/{archived['id']}/archive").raise_for_status()
    for ref in (
        epic["id"],
        str(epic["number"]),
        f"#{epic['number']}",
    ):  # by id, by number, with the hash
        answer = client.get("/api/tasks", params={"archived": "only", "parent": ref})
        assert [t["title"] for t in answer.json()] == ["Second", "First"], (
            ref
        )  # the newest archived first
        assert answer.headers["X-Total-Count"] == "2", ref  # the header counts the filtered list
    listed = client.get("/api/tasks", params={"archived": "only", "parent": epic["id"]}).json()
    assert live["id"] not in {t["id"] for t in listed}
    nobody = client.get("/api/tasks", params={"archived": "only", "parent": "999999"})
    assert (
        nobody.json() == [] and nobody.headers["X-Total-Count"] == "0"
    )  # no such card: no children
    v1 = client.get("/api/v1/artifacts", params={"archived": "only", "parent": epic["id"]})
    assert [t["title"] for t in v1.json()] == ["Second", "First"]
