"""An action definition is for pipelines or for guards (ADR-067): the type is set when it is made, the two never mix, the type
changes only where nothing on the other side uses the action, and a kind of node can be for one of them."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from tests.helpers import alembic_config, build_pipeline, graph_url, link, node, post

GUARDS = "/api/guards"


def _guard(client: TestClient, action: dict[str, Any] | None = None, name: str = "Watch") -> Any:
    body: dict[str, Any] = {
        "name": name,
        "trigger": {"type": "event", "events": ["enter"]},
        "when": {"type": "group", "mode": "all", "items": []},
        "consequence": "run_action" if action else "continue",
    }
    if action:
        body["action_id"] = action["id"]
    return client.post(GUARDS, json=body)


def test_an_action_is_for_pipelines_unless_it_is_made_for_guards(client: TestClient) -> None:
    plain = post(client, "/api/actions", name="Plain")
    judge = post(client, "/api/actions", name="Judge", purpose="guard")
    assert (plain["purpose"], judge["purpose"]) == ("pipeline", "guard")
    assert client.get(graph_url(judge)).json()["graph"]["purpose"] == "guard"
    pipelines = client.get("/api/actions", params={"purpose": "pipeline"}).json()
    guards = client.get("/api/actions", params={"purpose": "guard"}).json()
    assert [a["name"] for a in pipelines] == ["Plain"] and [a["name"] for a in guards] == ["Judge"]
    assert {a["name"] for a in client.get("/api/actions").json()} == {"Plain", "Judge"}, (
        "no filter: both"
    )
    assert client.get("/api/actions", params={"purpose": "other"}).status_code == 422


def test_a_pipeline_has_no_other_purpose_than_pipeline(client: TestClient) -> None:
    refused = client.post("/api/pipelines", json={"name": "P", "purpose": "guard"})
    assert refused.status_code == 422 and "Only an action can be for guards" in refused.text
    pipeline = post(client, "/api/pipelines", name="P")
    assert pipeline["purpose"] == "pipeline"
    changed = client.patch(graph_url(pipeline), json={"purpose": "guard"})
    assert changed.status_code == 422 and "Only an action has a purpose" in changed.text


def test_a_stage_takes_only_a_pipeline_action_and_a_guard_runs_only_a_guard_action(
    client: TestClient,
) -> None:
    pipeline = build_pipeline(client, stages=1)
    stage_action = pipeline["stages"][0][1]
    judge = post(client, "/api/actions", name="Judge", purpose="guard")
    refused = client.patch(
        f"{graph_url(pipeline)}/nodes/{stage_action['id']}", json={"definition_id": judge["id"]}
    )
    assert refused.status_code == 422 and "is a guard action" in refused.text
    plain = post(client, "/api/actions", name="Plain")
    link(client, pipeline, stage_action, plain)  # a pipeline action is fine there
    refused = _guard(client, plain)
    assert refused.status_code == 422 and "is an action for pipelines" in refused.text
    assert _guard(client, judge).status_code in (200, 201)


def test_the_action_a_guard_makes_for_itself_is_a_guard_action(client: TestClient) -> None:
    made = _guard(client, name="Own").json()
    own = client.get("/api/actions", params={"purpose": "guard"}).json()
    # a guard of the library without an action has none; the one that runs an action gets an empty guard action from the editor
    assert made["action_id"] is None and own == []
    run = client.post(
        GUARDS,
        json={
            "name": "Runs",
            "trigger": {"type": "event", "events": ["enter"]},
            "when": {"type": "group", "mode": "all", "items": []},
            "consequence": "run_action",
        },
    )
    assert run.status_code in (200, 201), run.text
    assert [a["id"] for a in client.get("/api/actions", params={"purpose": "guard"}).json()] == [
        run.json()["action_id"]
    ]


def test_the_purpose_changes_where_nothing_on_the_other_side_uses_the_action(
    client: TestClient,
) -> None:
    plain = post(client, "/api/actions", name="Plain")
    assert client.patch(graph_url(plain), json={"purpose": "guard"}).json()["purpose"] == "guard", (
        "unused: it changes"
    )
    assert client.patch(graph_url(plain), json={"purpose": "pipeline"}).json()["purpose"] == (
        "pipeline"
    )
    pipeline = build_pipeline(client, name="Uses it", stages=1)
    link(client, pipeline, pipeline["stages"][0][1], plain)
    blocked = client.patch(graph_url(plain), json={"purpose": "guard"})
    assert blocked.status_code == 409
    assert "used by the stages of 'Uses it'" in blocked.json()["detail"]
    assert client.get(graph_url(plain)).json()["graph"]["purpose"] == "pipeline"
    judge = post(client, "/api/actions", name="Judge", purpose="guard")
    assert _guard(client, judge, name="Watcher").status_code in (200, 201)
    blocked = client.patch(graph_url(judge), json={"purpose": "pipeline"})
    assert blocked.status_code == 409 and "run by the guard 'Watcher'" in blocked.json()["detail"]
    nothing = client.patch(graph_url(judge), json={})
    assert nothing.status_code == 422, "a change names a name or a purpose"
    both = client.patch(graph_url(plain), json={"name": "Renamed"})
    assert both.json()["name"] == "Renamed" and both.json()["purpose"] == "pipeline"


def test_the_node_manifests_say_where_a_kind_may_be_used(client: TestClient) -> None:
    kinds = {t["kind"]: t for t in client.get("/api/node-types").json()}
    assert all(
        set(t["purposes"]) <= {"pipeline", "guard"} and t["purposes"] for t in kinds.values()
    )
    assert kinds["github"]["purposes"] == ["guard", "pipeline"], "a kind is in both by default"
    assert kinds["github"]["requires"] is None, "a hook for the permissions of card #99"


def test_a_pipeline_action_and_a_guard_action_hold_what_their_kinds_allow(
    client: TestClient,
) -> None:
    judge = post(client, "/api/actions", name="Judge", purpose="guard")
    assert node(client, judge, "code")["kind"] == "code"
    plain = post(client, "/api/actions", name="Plain")
    assert node(client, plain, "code")["kind"] == "code"


def _guard_row(conn: sqlite3.Connection, guard_id: str, action_id: str | None) -> None:
    conn.execute(
        "INSERT INTO guard_definitions (id, name, action_id, created_at, updated_at) VALUES (?, ?, ?, '2026-01-01', '2026-01-01')",
        (guard_id, guard_id, action_id),
    )


def test_migration_0054_makes_the_actions_of_guards_guard_actions_unless_a_stage_uses_them(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0053")
    with sqlite3.connect(db) as conn:
        for graph_id, kind in (
            ("pipe", "pipeline"),
            ("free", "action"),
            ("judge", "action"),
            ("both", "action"),
        ):
            conn.execute(
                "INSERT INTO graphs (id, name, slug, kind) VALUES (?, ?, ?, ?)",
                (graph_id, graph_id, graph_id, kind),
            )
        conn.execute(
            "INSERT INTO graph_nodes (id, graph_id, kind, name, definition_id) VALUES ('u', 'pipe', 'action', 'Use', 'both')"
        )
        _guard_row(conn, "g1", "judge")
        _guard_row(conn, "g2", "both")
    command.upgrade(alembic_config(), "0054")
    with sqlite3.connect(db) as conn:
        purposes = dict(conn.execute("SELECT id, purpose FROM graphs").fetchall())
    assert purposes == {
        "pipe": "pipeline",
        "free": "pipeline",
        "judge": "guard",
        "both": "pipeline",
    }
    command.downgrade(alembic_config(), "0053")
    with sqlite3.connect(db) as conn:
        assert "purpose" not in [r[1] for r in conn.execute("PRAGMA table_info(graphs)")]
    command.upgrade(alembic_config(), "head")


@pytest.mark.parametrize("purpose", ["pipeline", "guard"])
def test_a_new_action_in_the_api_needs_no_purpose_to_work_as_before(
    client: TestClient, purpose: str
) -> None:
    made = post(client, "/api/actions", name=f"A {purpose}", purpose=purpose)
    assert made["purpose"] == purpose
