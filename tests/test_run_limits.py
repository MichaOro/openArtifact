"""Settings > Run limits: the step limit and the time limit of an execution, frozen when it starts."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.engine.limits import RunLimits
from tests.helpers import (
    alembic_config,
    build_definition,
    build_pipeline,
    link,
    make_task,
    post,
    slow_pipeline,
    wait_for_run,
)

URL = "/api/settings/run-limits"


def test_the_defaults_are_the_limits_of_before(client: TestClient) -> None:
    limits = client.get(URL).json()
    assert (limits["max_steps"], limits["time_limit_minutes"], limits["updated_at"]) == (
        1000,
        0,
        None,
    )
    assert limits["max_steps_bounds"] == [10, 100000] and limits["time_limit_bounds"] == [0, 10080]
    assert limits["max_concurrent_runs"] == client.app.state.settings.max_concurrent_runs  # type: ignore[attr-defined]


def test_limits_are_changed_field_by_field_within_their_bounds(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    changed = client.put(URL, json={"time_limit_minutes": 30}).json()
    assert (changed["max_steps"], changed["time_limit_minutes"]) == (1000, 30) and changed[
        "updated_at"
    ]
    assert (
        client.put(URL, json={"max_steps": 50}).json()["time_limit_minutes"] == 30
    )  # left out: kept
    assert ("settings.changed", {"run_limits": client.get(URL).json()}) in published
    for body in (
        {"max_steps": 9},
        {"max_steps": 100001},
        {"time_limit_minutes": -1},
        {"time_limit_minutes": 10081},
        {"other": 1},
        {"max_steps": "many"},
    ):
        assert client.put(URL, json=body).status_code == 422, body
    assert client.get(URL).json()["max_steps"] == 50


def test_the_integration_api_has_them_too(migrated_settings: Settings) -> None:
    token = "limits-token-" + "x" * 24
    settings = migrated_settings.model_copy(update={"api_token": token, "secret_key": "k" * 40})
    with TestClient(_create_app(settings)) as client:
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/settings/run-limits").status_code == 401
        changed = client.put("/api/v1/settings/run-limits", json={"max_steps": 20}, headers=headers)
        assert changed.json()["max_steps"] == 20
        assert client.get("/api/v1/settings/run-limits", headers=headers).json()["max_steps"] == 20


def test_a_run_fails_when_its_time_limit_is_up_and_the_running_node_is_stopped(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import openartifact.engine.runner as runner

    monkeypatch.setattr(
        runner, "SECONDS_PER_MINUTE", 0.5
    )  # one minute is the smallest limit a user sets
    client.put(URL, json={"time_limit_minutes": 1})
    pipeline = slow_pipeline(client, seconds=600)
    task = make_task(client)
    started = time.monotonic()
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = wait_for_run(client, task, "failed", timeout=15)
    assert run["note"] == (
        "The execution took longer than its time limit of 1 minutes (Settings > Run limits)"
    )
    assert time.monotonic() - started < 10  # the 600 s timer did not run out
    execution = client.get(f"/api/tasks/{task['id']}/executions").json()["items"][0]
    assert (execution["status"], execution["note"]) == ("failed", run["note"])


def test_an_execution_keeps_the_limits_it_started_with(client: TestClient) -> None:
    client.put(URL, json={"max_steps": 500, "time_limit_minutes": 0})
    pipeline = slow_pipeline(client, seconds=30)
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(client, task, "running")
    client.put(URL, json={"max_steps": 10, "time_limit_minutes": 5})
    settings = client.app.state.settings  # type: ignore[attr-defined]
    with sqlite3.connect(settings.data_dir / settings.database_filename) as db:
        (text,) = db.execute("SELECT snapshot FROM pipeline_runs").fetchone()
    assert json.loads(text)["limits"] == {"max_steps": 500, "time_limit_minutes": 0}
    client.post(f"/api/tasks/{task['id']}/run/stop")


def test_a_snapshot_of_before_the_limits_has_the_old_defaults() -> None:
    assert RunLimits.of_snapshot({}) == RunLimits(1000, 0)
    assert RunLimits.of_snapshot({"limits": "broken"}) == RunLimits(1000, 0)
    assert RunLimits.of_snapshot({"limits": {"max_steps": 20}}) == RunLimits(20, 0)


def test_a_pipeline_within_the_limit_finishes(client: TestClient) -> None:
    client.put(URL, json={"max_steps": 10})
    pipeline = build_pipeline(client, stages=2)
    for _, action in pipeline["stages"]:
        link(client, pipeline, action, build_definition(client, f"D {action['id'][:4]}"))
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    assert wait_for_run(client, task, "done")["status"] == "done"


def test_migration_0034_adds_the_settings_and_the_kind_and_goes_back(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0033")
    insert = "INSERT INTO graph_nodes (id, graph_id, kind, name) VALUES (?, 'g', ?, ?)"
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO graphs (id, name, slug, kind) VALUES ('g', 'G', 'g', 'action')")
        with pytest.raises(
            sqlite3.IntegrityError, match="CHECK constraint failed: ck_graph_nodes_kind"
        ):
            conn.execute(insert, ("s", "set", "Set"))
    command.upgrade(alembic_config(), "0034")
    with sqlite3.connect(db) as conn:
        conn.execute(insert, ("s", "set", "Set"))
        conn.execute(insert, ("c", "code", "Code"))
        conn.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES ('run.max_steps', '50', '2026-01-01')"
        )
        with pytest.raises(
            sqlite3.IntegrityError, match=r"UNIQUE constraint failed: app_settings\.key"
        ):
            conn.execute(
                "INSERT INTO app_settings (key, value, updated_at) VALUES ('run.max_steps', '60', '2026-01-01')"
            )
    command.downgrade(alembic_config(), "0033")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id FROM graph_nodes").fetchall() == [("c",)]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "app_settings" not in tables
    command.upgrade(alembic_config(), "head")
