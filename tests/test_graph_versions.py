"""Versions of actions and pipelines (ADR-070): publishing, the chip, what an execution runs and what a published version keeps in use."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from alembic import command
from fastapi.testclient import TestClient

from tests.helpers import (
    alembic_config,
    build_pipeline,
    graph_url,
    make_task,
    node,
    post,
    wait_for_run,
)
from tests.test_execution_nodes import _definition, _start, _use, _work


def _versions(client: TestClient, graph: dict[str, Any]) -> list[dict[str, Any]]:
    return client.get(f"{graph_url(graph)}/versions").json()  # type: ignore[no-any-return]


def _publish(client: TestClient, graph: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"{graph_url(graph)}/publish")
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def _read(client: TestClient, graph: dict[str, Any]) -> dict[str, Any]:
    return client.get(graph_url(graph)).json()["graph"]  # type: ignore[no-any-return]


def _set_code(client: TestClient, action: dict[str, Any], code: str) -> None:
    response = client.patch(
        f"{graph_url(action)}/nodes/{action['node']['id']}", json={"config": {"code": code}}
    )
    assert response.status_code == 200, response.text


# ── publishing and the chip ──────────────────────────────────────────


def test_a_new_definition_has_no_version_and_publishing_makes_version_one(
    client: TestClient,
) -> None:
    action = post(client, "/api/actions", name="Gap")
    assert _versions(client, action) == []
    assert (_read(client, action)["published_version"], _read(client, action)["draft_changed"]) == (
        None,
        False,
    )
    done = _publish(client, action)
    assert (
        done["version"]["number"],
        done["version"]["current"],
        done["version"]["source_number"],
    ) == (1, True, None)
    assert done["version"]["node_count"] == 2, "the trigger and the output of a new action"
    assert (done["graph"]["published_version"], done["graph"]["draft_changed"]) == (1, False)
    assert [v["number"] for v in _versions(client, action)] == [1]


def test_the_draft_is_changed_by_what_runs_and_not_by_where_a_node_sits(client: TestClient) -> None:
    action = _definition(client, "code", code="echo one")
    _publish(client, action)
    mover = action["node"]
    client.patch(f"{graph_url(action)}/nodes/{mover['id']}", json={"x": 500.0, "y": 300.0})
    assert _read(client, action)["draft_changed"] is False, (
        "moving a node changes nothing that runs"
    )
    _set_code(client, action, "echo two")
    assert _read(client, action)["draft_changed"] is True
    listed = {g["id"]: g for g in client.get("/api/actions").json()}
    assert (
        listed[action["id"]]["draft_changed"] is True
        and listed[action["id"]]["published_version"] == 1
    )


def test_publishing_an_unchanged_draft_is_refused_and_a_change_makes_the_next_number(
    client: TestClient,
) -> None:
    action = _definition(client, "code", code="echo one")
    _publish(client, action)
    again = client.post(f"{graph_url(action)}/publish")
    assert again.status_code == 409 and "Nothing changed since version 1" in again.json()["detail"]
    _set_code(client, action, "echo two")
    second = _publish(client, action)
    assert second["version"]["number"] == 2 and second["graph"]["draft_changed"] is False
    assert [(v["number"], v["current"]) for v in _versions(client, action)] == [
        (2, True),
        (1, False),
    ]


def test_publishing_again_makes_a_new_version_with_the_old_content_and_leaves_the_draft(
    client: TestClient,
) -> None:
    action = _definition(client, "code", code="echo one")
    _publish(client, action)
    _set_code(client, action, "echo two")
    _publish(client, action)
    back = client.post(f"{graph_url(action)}/versions/1/republish")
    assert back.status_code == 200, back.text
    made = back.json()
    assert (
        made["version"]["number"],
        made["version"]["source_number"],
        made["version"]["current"],
    ) == (3, 1, True)
    assert made["graph"]["published_version"] == 3
    assert made["graph"]["draft_changed"] is True, (
        "the draft says echo two, the published version says echo one"
    )
    assert [v["number"] for v in _versions(client, action)] == [3, 2, 1], "the history stays"
    assert client.post(f"{graph_url(action)}/versions/3/republish").status_code == 409
    assert client.post(f"{graph_url(action)}/versions/9/republish").status_code == 404


def test_a_version_is_read_with_its_frozen_graph(client: TestClient) -> None:
    action = _definition(client, "code", code="echo one")
    _publish(client, action)
    _set_code(client, action, "echo two")
    got = client.get(f"{graph_url(action)}/versions/1").json()
    code = next(n for n in got["nodes"] if n["kind"] == "code")
    assert code["config"]["code"] == "echo one", "what was published, not the draft"
    assert len(got["edges"]) >= 2 and got["name"] == action["name"]
    assert client.get(f"{graph_url(action)}/versions/7").status_code == 404
    assert client.post(f"/api/pipelines/{action['id']}/publish").status_code == 404, (
        "an action is not a pipeline"
    )


def test_deleting_a_definition_deletes_its_versions(client: TestClient) -> None:
    action = post(client, "/api/actions", name="Gone")
    _publish(client, action)
    assert client.delete(graph_url(action)).status_code == 204
    assert client.get(f"{graph_url(action)}/versions").status_code == 404


# ── what an execution runs ───────────────────────────────────────────


def _run_output(client: TestClient, pipeline: dict[str, Any]) -> str:
    task = make_task(client)
    _start(client, pipeline, task)
    run = wait_for_run(client, task, "done")
    (result,) = _work(run)
    return str(result["output"]).strip()


def test_without_a_published_version_the_draft_runs_as_it_always_did(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1)
    action = _definition(client, "code", code="echo draft")
    _use(client, pipeline, action)
    assert _run_output(client, pipeline) == "draft"
    _set_code(client, action, "echo draft two")
    assert _run_output(client, pipeline) == "draft two"


def test_an_execution_runs_the_published_version_and_an_edit_reaches_it_only_when_published(
    client: TestClient,
) -> None:
    pipeline = build_pipeline(client, stages=1)
    action = _definition(client, "code", code="echo one")
    _use(client, pipeline, action)
    _publish(client, action)
    _set_code(client, action, "echo two")
    assert _run_output(client, pipeline) == "one", "the draft is not what runs"
    _publish(client, action)
    assert _run_output(client, pipeline) == "two"
    client.post(f"{graph_url(action)}/versions/1/republish").raise_for_status()
    assert _run_output(client, pipeline) == "one", (
        "publishing an old version again is a rollback for the next run"
    )


def test_a_pipeline_runs_its_published_version(client: TestClient) -> None:
    pipeline = build_pipeline(client, stages=1)
    action = _definition(client, "code", code="echo kept")
    _use(client, pipeline, action)
    _publish(client, pipeline)
    # the draft of the pipeline gets a second stage that would run a code node: it is not published, so it does not run
    extra = _definition(client, "code", code="echo extra")
    stage = node(client, pipeline, "stage", name="Later")
    shell = node(client, pipeline, "action", stage_id=stage["id"], name="More")
    client.patch(f"{graph_url(pipeline)}/nodes/{shell['id']}", json={"definition_id": extra["id"]})
    assert _read(client, pipeline)["draft_changed"] is True
    task = make_task(client)
    _start(client, pipeline, task)
    run = wait_for_run(client, task, "done")
    assert [str(r["output"]).strip() for r in _work(run)] == ["kept"]


# ── purpose and usage look at the published version too ──────────────


def test_a_pipeline_whose_published_version_still_uses_an_action_keeps_it_in_use(
    client: TestClient,
) -> None:
    pipeline = build_pipeline(client, stages=1)
    action = _definition(client, "code", code="echo x")
    shell = _use(client, pipeline, action)
    _publish(client, pipeline)
    client.patch(f"{graph_url(pipeline)}/nodes/{shell['id']}", json={"definition_id": None})
    uses = client.get(f"{graph_url(action)}/uses").json()["uses"]
    assert [(u["kind"], u["name"], u["detail"]) for u in uses] == [
        ("stage", pipeline["name"], "v1 published")
    ]
    changed = client.patch(graph_url(action), json={"purpose": "guard"})
    assert changed.status_code == 409 and pipeline["name"] in changed.json()["detail"]


# ── the migration ─────────────────────────────────────────────────────


def test_migration_0057_keeps_the_graphs_and_the_downgrade_drops_the_versions(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0056")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO graphs (id, name, slug, kind) VALUES ('g', 'G', 'g', 'action')")
    command.upgrade(alembic_config(), "0057")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, published_number FROM graphs").fetchall() == [
            ("g", None)
        ], "nothing published: the draft runs"
        conn.execute(
            "INSERT INTO graph_versions (id, graph_id, number, content, fingerprint, published_via, published_at) "
            "VALUES ('v', 'g', 1, '{}', 'f', 'user', '2026-11-25 00:00:00')"
        )
    command.downgrade(alembic_config(), "0056")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id FROM graphs").fetchall() == [("g",)]
        columns = [row[1] for row in conn.execute("PRAGMA table_info(graphs)")]
        assert "published_number" not in columns
        tables = [
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        assert "graph_versions" not in tables
    command.upgrade(alembic_config(), "head")
