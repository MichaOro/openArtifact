"""Draft and published versions of guard definitions (ADR-081): a new guard watches nothing until it is published, a saved change is a
draft, an execution keeps the version it started with, switching an attachment on or off stays immediate, the version endpoints and
their refusals, the templates, MCP, and migration 0065 with real rows."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import alembic_config, build_pipeline, make_task, post, wait_for_run
from tests.test_guards import (
    ATTACHMENTS,
    GUARDS,
    _activity,
    _at_least,
    _attach,
    _definition,
    _group,
    _tool,
)
from tests.test_history import HEADERS, TOKEN


@pytest.fixture
def client(migrated_settings: Settings) -> Generator[TestClient, None, None]:
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


def _aborting(**extra: Any) -> dict[str, Any]:
    """A guard that aborts the run when its scope is entered the first time: an unmistakable sign that it watches."""
    return _definition(
        name="Gate",
        when=_group(_at_least("runs", 1)),
        consequence="abort",
        **extra,
    )


def _one_stage(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    pipeline = build_pipeline(client, stages=1, name="Short")
    stage, _action = pipeline["stages"][0]
    return pipeline, stage


def _run(client: TestClient, pipeline: dict[str, Any], status: str) -> dict[str, Any]:
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = wait_for_run(client, task, status, timeout=20)
    run["task"] = task
    return run


def _publish(client: TestClient, guard_id: str) -> dict[str, Any]:
    response = client.post(f"{GUARDS}/{guard_id}/publish")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# ── draft and published ──────────────────────────────────────────────


def test_a_new_guard_is_a_draft_that_watches_nothing_until_it_is_published(
    client: TestClient,
) -> None:
    pipeline, stage = _one_stage(client)
    guard = post(client, GUARDS, **_aborting())
    assert (guard["published_version"], guard["draft_changed"]) == (None, False)
    place = _attach(client, guard, pipeline, "stage", stage["id"])
    assert place["guard_published"] is False  # attached, but inactive: the UI says so
    assert client.get(ATTACHMENTS).json()[0]["guard_published"] is False

    _run(client, pipeline, "done")  # the draft watches nothing: the run is not aborted

    published = _publish(client, guard["id"])
    assert published["version"]["number"] == 1 and published["version"]["current"] is True
    assert published["guard"]["published_version"] == 1
    assert client.get(ATTACHMENTS).json()[0]["guard_published"] is True
    run = _run(client, pipeline, "failed")
    assert run["note"].startswith("Aborted by guard Gate fired at Stage 1")


def test_a_saved_change_is_a_draft_until_it_is_published_and_a_run_names_its_version(
    client: TestClient,
) -> None:
    pipeline, stage = _one_stage(client)
    guard = post(client, GUARDS, **_aborting())
    _attach(client, guard, pipeline, "stage", stage["id"])
    _publish(client, guard["id"])

    changed = client.patch(f"{GUARDS}/{guard['id']}", json={"consequence": "continue"}).json()
    assert (changed["consequence"], changed["published_version"], changed["draft_changed"]) == (
        "continue",
        1,
        True,
    )
    first = _run(client, pipeline, "failed")  # the published version 1 still aborts
    assert first["note"].startswith("Aborted by guard Gate")

    again = _publish(client, guard["id"])
    assert again["version"]["number"] == 2 and again["guard"]["draft_changed"] is False
    _run(client, pipeline, "done")  # version 2 only records

    versions = {e["data"]["guard_version"] for e in _activity(client, first["task"])}
    assert versions == {1}, "the firing names the version the run froze"
    latest = _activity(client, _run(client, pipeline, "done")["task"])
    assert {e["data"]["guard_version"] for e in latest} == {2}


def test_switching_an_attachment_on_or_off_is_immediate_and_makes_no_version(
    client: TestClient,
) -> None:
    pipeline, stage = _one_stage(client)
    guard = post(client, GUARDS, **_aborting())
    place = _attach(client, guard, pipeline, "stage", stage["id"])
    _publish(client, guard["id"])
    off = client.put(f"{ATTACHMENTS}/{place['id']}/enabled", json={"enabled": False}).json()
    assert off["enabled"] is False
    _run(client, pipeline, "done")  # switched off at once, nothing published
    client.put(f"{ATTACHMENTS}/{place['id']}/enabled", json={"enabled": True})
    _run(client, pipeline, "failed")
    assert [v["number"] for v in client.get(f"{GUARDS}/{guard['id']}/versions").json()] == [1]
    assert client.get(f"{GUARDS}/{guard['id']}").json()["draft_changed"] is False


# ── the version endpoints ────────────────────────────────────────────


def test_versions_are_listed_shown_published_again_and_a_draft_is_discarded(
    client: TestClient,
) -> None:
    guard = post(client, GUARDS, **_aborting(description="first"))
    _publish(client, guard["id"])
    client.patch(f"{GUARDS}/{guard['id']}", json={"description": "second", "name": "Gate 2"})
    _publish(client, guard["id"])
    listed = client.get(f"{GUARDS}/{guard['id']}/versions").json()
    assert [(v["number"], v["current"], v["name"]) for v in listed] == [
        (2, True, "Gate 2"),
        (1, False, "Gate"),
    ]
    shown = client.get(f"{GUARDS}/{guard['id']}/versions/1").json()
    assert (shown["guard"]["description"], shown["guard"]["consequence"]) == ("first", "abort")

    client.patch(f"{GUARDS}/{guard['id']}", json={"description": "draft only"})
    again = client.post(f"{GUARDS}/{guard['id']}/versions/1/republish").json()
    assert again["version"]["number"] == 3 and again["version"]["source_number"] == 1
    assert again["guard"]["description"] == "draft only"  # the draft is not touched
    assert again["guard"]["draft_changed"] is True

    discarded = client.post(f"{GUARDS}/{guard['id']}/draft/discard").json()
    assert (discarded["description"], discarded["name"], discarded["draft_changed"]) == (
        "first",
        "Gate",
        False,
    )


@pytest.mark.parametrize(
    ("call", "status", "text"),
    [
        ("discard-unpublished", 409, "Nothing is published yet"),
        ("publish-twice", 409, "Nothing changed since version 1"),
        ("discard-equal", 409, "The draft equals version 1"),
        ("republish-current", 409, "Version 1 is the published one already"),
        ("unknown-version", 404, "Version 9 does not exist"),
        ("republish-unknown", 404, "Version 9 does not exist"),
        ("publish-action-less", 422, "needs that action"),
    ],
)
def test_the_refusals_of_the_version_endpoints_say_why(
    client: TestClient, migrated_settings: Settings, call: str, status: int, text: str
) -> None:
    guard = post(client, GUARDS, **_aborting())
    if call != "discard-unpublished" and call != "publish-action-less":
        _publish(client, guard["id"])
    base = f"{GUARDS}/{guard['id']}"
    if call == "publish-action-less":
        # a guard that runs an action whose action was deleted behind its back has none: publishing it is refused
        client.patch(base, json={"consequence": "run_action"})
        draft = client.get(base).json()
        with sqlite3.connect(migrated_settings.database_url.split("///", 1)[1]) as conn:
            conn.execute(
                "UPDATE guard_definitions SET action_id = NULL WHERE id = ?", (draft["id"],)
            )
    response = {
        "discard-unpublished": lambda: client.post(f"{base}/draft/discard"),
        "publish-twice": lambda: client.post(f"{base}/publish"),
        "discard-equal": lambda: client.post(f"{base}/draft/discard"),
        "republish-current": lambda: client.post(f"{base}/versions/1/republish"),
        "unknown-version": lambda: client.get(f"{base}/versions/9"),
        "republish-unknown": lambda: client.post(f"{base}/versions/9/republish"),
        "publish-action-less": lambda: client.post(f"{base}/publish"),
    }[call]()
    assert response.status_code == status, response.text
    assert text in response.text


def test_the_integration_api_publishes_as_api_and_a_template_is_published_version_1(
    client: TestClient,
) -> None:
    made = client.post("/api/v1/guards", json=_aborting()).json()
    published = client.post(f"/api/v1/guards/{made['id']}/publish").json()
    assert published["version"]["published_via"] == "api"
    assert client.get(f"{GUARDS}/{made['id']}/versions").json()[0]["published_via"] == "api"
    stall = post(client, f"{GUARDS}/from-template", template="stall")
    assert (stall["published_version"], stall["draft_changed"]) == (1, False)


def test_a_deleted_guard_takes_its_versions_with_it(
    client: TestClient, migrated_settings: Settings
) -> None:
    guard = post(client, GUARDS, **_aborting())
    _publish(client, guard["id"])
    assert client.delete(f"{GUARDS}/{guard['id']}").status_code == 204
    assert client.get(f"{GUARDS}/{guard['id']}/versions").status_code == 404
    path = migrated_settings.database_url.split("///", 1)[1]
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM guard_versions").fetchone() == (0,)


def test_mcp_lists_the_published_version_and_the_draft_flag_and_has_no_publish_tool(
    client: TestClient,
) -> None:
    guard = post(client, GUARDS, **_aborting())
    _publish(client, guard["id"])
    client.patch(f"{GUARDS}/{guard['id']}", json={"description": "changed"})
    error, listed = _tool(client, "list_guards")
    assert not error
    [entry] = [g for g in listed if g["id"] == guard["id"]]
    assert (entry["published_version"], entry["draft_changed"]) == (1, True)
    tools = client.post(
        "/mcp",
        headers={**HEADERS, "Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ).json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "set_guard_enabled" in names
    assert not [
        n for n in names if "guard" in n and ("publish" in n or "update" in n or "create" in n)
    ]


# ── migration 0065 ───────────────────────────────────────────────────


def test_0065_makes_every_guard_published_version_1_with_its_content_and_goes_down(
    at_revision: Callable[[str], Path],
) -> None:
    previous = ScriptDirectory.from_config(alembic_config()).get_revision("0065").down_revision
    assert isinstance(previous, str)
    db = at_revision(previous)
    rows = [
        (
            "g1",
            "Round guard",
            "watch",
            '["stage"]',
            '{"type": "event", "events": ["enter"]}',
            "pause",
        ),
        (
            "g2",
            "Quiet",
            "",
            '["pipeline", "stage"]',
            '{"type": "interval", "every_seconds": 60}',
            "abort",
        ),
    ]
    with sqlite3.connect(db) as conn:
        for ident, name, description, scopes, trigger, consequence in rows:
            conn.execute(
                "INSERT INTO guard_definitions (id, name, description, scope_types, trigger, condition, consequence, "
                'fallback, escalation, created_at, updated_at) VALUES (?, ?, ?, ?, ?, \'{"type": "group"}\', ?, '
                "'pause', '[{\"from_firing\": 1, \"every_runs\": 3}]', '2026-11-01', '2026-11-02')",
                (ident, name, description, scopes, trigger, consequence),
            )
    command.upgrade(alembic_config(), "0065")
    with sqlite3.connect(db) as conn:
        published = dict(conn.execute("SELECT id, published_number FROM guard_definitions"))
        versions = conn.execute(
            "SELECT guard_id, number, content, fingerprint, source_number, published_via FROM guard_versions "
            "ORDER BY guard_id"
        ).fetchall()
    assert published == {"g1": 1, "g2": 1}
    assert [(v[0], v[1], v[4], v[5]) for v in versions] == [
        ("g1", 1, None, "user"),
        ("g2", 1, None, "user"),
    ]
    first = json.loads(versions[0][2])
    assert first == {
        "name": "Round guard",
        "description": "watch",
        "scope_types": ["stage"],
        "trigger": {"type": "event", "events": ["enter"]},
        "when": {"type": "group"},
        "consequence": "pause",
        "fallback": "pause",
        "escalation": [{"from_firing": 1, "every_runs": 3}],
        "action_id": None,
    }
    assert versions[0][3] == hashlib.sha256(versions[0][2].encode()).hexdigest()
    command.downgrade(alembic_config(), previous)
    with sqlite3.connect(db) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(guard_definitions)")}
        kept = [r[0] for r in conn.execute("SELECT id FROM guard_definitions ORDER BY id")]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "published_number" not in columns and "guard_versions" not in tables
    assert kept == ["g1", "g2"]  # the definitions stay: what was the draft is what they hold
    command.upgrade(alembic_config(), "head")
