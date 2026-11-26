"""Data storage (ADR-084): the limits of the user, what a pass hits (the preview is the pass), what it never touches, cutting long text when it
is stored, the write-ahead log, shrinking, the status the page shows, and MCP (read only)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.database import Base
from openartifact.engine import storage
from openartifact.engine.storage import (
    TECHNICAL_TABLES,
    VISIBLE_TABLES,
    Cleaner,
    StorageLimits,
    StoragePolicy,
    cut_detail,
)
from openartifact.exceptions import ArtifactError
from openartifact.models import *  # noqa: F403 - registers every table on Base.metadata
from tests.helpers import make_task, wait_for_run
from tests.test_guards import _tool
from tests.test_history import HEADERS, TOKEN
from tests.test_history_global import Seed, _db, _stamp
from tests.test_run_context import _code, _detail, _start, _use_chain

PERSONAL = "/api/settings/personal"
STORAGE = "/api/settings/storage"
NOW = datetime.now(UTC)


def _set(client: TestClient, **values: Any) -> None:
    response = client.put(PERSONAL, json=values)
    assert response.status_code == 200, response.text


def _steps(
    path: Path,
    execution_id: str,
    *,
    outputs: list[str],
    detail: dict[str, Any] | None = None,
    context: str = "{}",
    at: datetime = NOW,
) -> None:
    """Steps with outputs (and a detail on the first) inserted straight into the database."""
    with sqlite3.connect(path) as conn:
        for i, output in enumerate(outputs, start=1):
            conn.execute(
                "INSERT INTO run_node_results (id, run_id, execution_id, seq, node_id, node_name, kind, outcome, output, data, "
                "detail, started_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"{execution_id}-{i}",
                    "run",
                    execution_id,
                    i,
                    f"n{i}",
                    f"Node {i}",
                    "agent",
                    "pass",
                    output,
                    json.dumps({"model": "m"}),
                    json.dumps(detail) if detail and i == 1 else None,
                    _stamp(at),
                    _stamp(at),
                ),
            )
        conn.execute(
            "UPDATE executions SET step_count = ?, context = ? WHERE id = ?",
            (len(outputs), context, execution_id),
        )


def _count(path: Path, table: str, where: str = "1") -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0])


def _plan(client: TestClient) -> dict[str, Any]:
    response = client.post(f"{STORAGE}/preview")
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def _entries(plan: dict[str, Any]) -> dict[str, int]:
    return {c["key"]: c["entries"] for c in plan["categories"]}


# ── what is classified ────────────────────────────────────────────────


def test_every_table_is_classified_as_visible_or_technical_and_none_as_both() -> None:
    tables = set(Base.metadata.tables) | {"alembic_version"}
    assert tables == VISIBLE_TABLES | TECHNICAL_TABLES, (
        "a new table must be classified in engine/storage.py (ADR-084)"
    )
    assert not VISIBLE_TABLES & TECHNICAL_TABLES


# ── the policy ────────────────────────────────────────────────────────


def test_empty_settings_are_today_s_limits_and_the_operator_s_default() -> None:
    policy = StoragePolicy.of({})
    assert policy.limits() == StorageLimits() == StorageLimits(256 * 1024, 1024 * 1024)
    assert policy.keep(50) == 50 and policy.run_data_bytes is None and policy.step_data_days is None
    assert policy.clean_interval_hours is None and policy.warn_bytes is None


def test_the_user_s_numbers_become_limits_and_never_exceed_today_s() -> None:
    policy = StoragePolicy.of(
        {
            "storage_keep_executions": 0,
            "storage_step_output_kib": 8,
            "storage_run_output_kib": 100,
            "storage_run_data_mib": 5,
            "storage_warn_mib": 2,
        }
    )
    assert policy.keep(50) == 0  # 0 keeps all, whatever the operator set
    assert policy.limits() == StorageLimits(8 * 1024, 100 * 1024)
    assert (policy.run_data_bytes, policy.warn_bytes) == (5 * 1024 * 1024, 2 * 1024 * 1024)
    assert StoragePolicy.of({"storage_step_output_kib": 9999}).step_output_chars == 256 * 1024


def test_a_snapshot_without_the_limits_has_today_s() -> None:
    assert StorageLimits.of_snapshot({}) == StorageLimits()
    assert StorageLimits.of_snapshot(
        {"storage": {"step_output_chars": 100, "run_output_chars": 200}}
    ) == StorageLimits(100, 200)
    assert StorageLimits.of_snapshot({"storage": {"step_output_chars": 10**9}}) == StorageLimits()


# ── cutting long text when it is stored ───────────────────────────────


def test_cut_detail_cuts_every_long_text_in_a_nested_detail_and_counts_them() -> None:
    detail = {"prompt": "p" * 50, "turns": [{"result": "r" * 30, "short": "ok"}], "n": 3}
    cut, count = cut_detail(detail, 20)
    assert count == 2
    assert cut["prompt"].startswith("p" * 20) and cut["prompt"].endswith(
        "[truncated: 30 characters left out]"
    )
    assert cut["turns"][0]["short"] == "ok" and cut["n"] == 3
    assert cut_detail(detail, 1000) == (detail, 0)


def test_a_step_output_over_the_users_limit_is_cut_and_marked_and_without_it_is_whole(
    client: TestClient,
) -> None:
    pipeline, task, _ = _use_chain(
        client, ("code", "Long", _code("head -c 3000 /dev/zero | tr '\\0' x"))
    )
    _start(client, pipeline, task)
    wait_for_run(client, task, "done")
    step = next(s for s in _detail(client, task)["steps"] if s["kind"] == "code")
    assert step["output"] == "x" * 3000 and "output_truncated" not in (
        step["data"] or {}
    )  # no limit set: nothing changes
    _set(client, storage_step_output_kib=1)
    pipeline2, task2, _ = _use_chain(
        client, ("code", "Long", _code("head -c 3000 /dev/zero | tr '\\0' x"))
    )
    _start(client, pipeline2, task2)
    wait_for_run(client, task2, "done")
    step = next(s for s in _detail(client, task2)["steps"] if s["kind"] == "code")
    assert len(step["output"]) == 1024 and step["output"].endswith("\n[output truncated]")
    assert step["data"]["output_truncated"] is True
    assert step["reason"] == "Note: the output was cut at 1 Ki characters"


# ── a pass: the preview is the pass, defaults change nothing ──────────


def test_with_the_defaults_a_pass_deletes_and_empties_nothing(client: TestClient) -> None:
    task = make_task(client, "Alpha")
    seed = Seed(client)
    ids = [seed.add(task, at=NOW - timedelta(days=400 - i)) for i in range(3)]
    for execution_id in ids:
        _steps(seed.path, execution_id, outputs=["x" * 5000], detail={"p": "d" * 5000})
    before = (_count(seed.path, "executions"), _count(seed.path, "run_node_results"))
    assert _plan(client)["entries"] == 0
    report = client.post(f"{STORAGE}/clean").json()
    assert report["plan"]["entries"] == 0
    assert (_count(seed.path, "executions"), _count(seed.path, "run_node_results")) == before
    assert _count(seed.path, "run_node_results", "output = ''") == 0


def test_the_number_kept_per_artifact_deletes_the_older_ones_but_never_the_newest_or_a_running_one(
    client: TestClient,
) -> None:
    task = make_task(client, "Alpha")
    seed = Seed(client)
    ids = [seed.add(task, at=NOW - timedelta(days=10 - i)) for i in range(5)]  # numbers 1 .. 5
    running = seed.add(
        task, at=NOW - timedelta(days=20), status="running"
    )  # number 6, the newest by number
    _set(client, storage_keep_executions=2)
    plan = _plan(client)
    assert (
        _entries(plan)["executions_keep"] == 4
    )  # numbers 1 to 4; 6 (running) and 5 are the two newest and stay
    client.post(f"{STORAGE}/clean")
    left = set(_numbers(seed.path))
    assert left == {5, 6} and running in _ids(seed.path) and ids[-1] in _ids(seed.path)


def _numbers(path: Path) -> list[int]:
    with sqlite3.connect(path) as conn:
        return [r[0] for r in conn.execute("SELECT number FROM executions")]


def _ids(path: Path) -> set[str]:
    with sqlite3.connect(path) as conn:
        return {r[0] for r in conn.execute("SELECT id FROM executions")}


def test_step_data_of_executions_older_than_the_set_days_is_emptied_and_marked_the_execution_stays(
    client: TestClient,
) -> None:
    task = make_task(client, "Alpha")
    seed = Seed(client)
    old = seed.add(task, at=NOW - timedelta(days=10))
    recent = seed.add(task, at=NOW - timedelta(days=2))
    for execution_id in (old, recent):
        _steps(
            seed.path,
            execution_id,
            outputs=["x" * 4000, "y" * 3000],
            detail={"p": "d" * 2000},
            context='{"vars": {"k": "' + "c" * 500 + '"}}',
        )
    _set(client, storage_step_data_days=5)
    plan = _plan(client)
    assert _entries(plan)["step_data_age"] == 1
    assert plan["bytes"] >= 4000 + 3000 + 2000
    client.post(f"{STORAGE}/clean")
    with sqlite3.connect(seed.path) as conn:
        rows = conn.execute(
            "SELECT execution_id, output, detail, data FROM run_node_results ORDER BY execution_id, seq"
        ).fetchall()
        steps = {
            (e, o, d is None, json.loads(data).get("data_pruned"))
            for e, o, d, data in rows
            if e == old
        }
        assert steps == {
            (old, "", True, True)
        }  # both steps emptied, each marked, the result data kept
        assert all(json.loads(data)["model"] == "m" for *_, data in rows)
        assert [o for e, o, _d, _x in rows if e == recent] == [
            "x" * 4000,
            "y" * 3000,
        ]  # the recent one is whole
        assert conn.execute(
            "SELECT step_count FROM executions WHERE id = ?", (old,)
        ).fetchone() == (2,)
        assert conn.execute("SELECT context FROM executions WHERE id = ?", (old,)).fetchone() == (
            "{}",
        )


def test_the_size_limit_empties_the_oldest_finished_executions_until_it_fits_and_never_a_running_one(
    client: TestClient,
) -> None:
    task = make_task(client, "Alpha")
    seed = Seed(client)
    big = "z" * 600_000
    finished = [seed.add(task, at=NOW - timedelta(days=9 - i)) for i in range(3)]
    running = seed.add(task, at=NOW - timedelta(days=30), status="running")
    for execution_id in [*finished, running]:
        _steps(seed.path, execution_id, outputs=[big])
    _set(client, storage_run_data_mib=1)
    plan = _plan(client)
    assert (
        _entries(plan)["step_data_size"] == 3
    )  # 2.4 MB in all, only finished ones may go: all three
    client.post(f"{STORAGE}/clean")
    assert (
        _count(seed.path, "run_node_results", f"output = '{big}'") == 1
    )  # only the running one keeps its output
    with sqlite3.connect(seed.path) as conn:
        assert conn.execute(
            "SELECT output FROM run_node_results WHERE execution_id = ?", (running,)
        ).fetchone() == (big,)


def test_the_size_limit_stops_as_soon_as_the_data_fits(client: TestClient) -> None:
    task = make_task(client, "Alpha")
    seed = Seed(client)
    ids = [seed.add(task, at=NOW - timedelta(days=9 - i)) for i in range(3)]
    for execution_id in ids:
        _steps(seed.path, execution_id, outputs=["z" * 600_000])
    _set(client, storage_run_data_mib=1)
    assert _entries(_plan(client))["step_data_size"] == 2  # 1.8 MB -> 1.2 MB -> 0.6 MB
    client.post(f"{STORAGE}/clean")
    with sqlite3.connect(seed.path) as conn:
        kept = conn.execute(
            "SELECT execution_id FROM run_node_results WHERE output != ''"
        ).fetchall()
    assert kept == [(ids[-1],)]  # the newest keeps its output


def test_the_preview_is_what_the_pass_does_and_cards_comments_and_history_stay(
    client: TestClient,
) -> None:
    task = make_task(client, "Alpha")
    client.post(f"/api/tasks/{task['id']}/comments", json={"body": "a comment", "author": "me"})
    seed = Seed(client)
    ids = [seed.add(task, at=NOW - timedelta(days=30 - i)) for i in range(4)]
    for execution_id in ids:
        _steps(seed.path, execution_id, outputs=["q" * 20_000])
    _set(client, storage_keep_executions=3, storage_step_data_days=7)
    preview = _plan(client)
    comments = _count(seed.path, "task_comments")
    cards = _count(seed.path, "tasks")
    report = client.post(f"{STORAGE}/clean").json()
    assert report["plan"]["categories"] == preview["categories"]  # the same numbers and kinds
    assert _count(seed.path, "tasks") == cards and _count(seed.path, "task_comments") == comments
    assert _count(seed.path, "executions") == 4 - _entries(preview)["executions_keep"]


def test_a_running_execution_is_untouched_even_when_old_and_heavy(client: TestClient) -> None:
    task = make_task(client, "Alpha")
    seed = Seed(client)
    running = seed.add(task, at=NOW - timedelta(days=100), status="running")
    _steps(
        seed.path, running, outputs=["x" * 10_000], context='{"vars": {"a": "' + "b" * 400 + '"}}'
    )
    _set(client, storage_keep_executions=1, storage_step_data_days=1, storage_run_data_mib=1)
    assert _plan(client)["entries"] == 0
    client.post(f"{STORAGE}/clean")
    assert _count(seed.path, "run_node_results", "output != ''") == 1


def test_the_retention_rules_the_user_set_are_part_of_the_pass(client: TestClient) -> None:
    task = make_task(client, "Alpha")
    seed = Seed(client)
    failed = seed.add(task, at=NOW - timedelta(days=3), status="failed")
    seed.add(task, at=NOW - timedelta(days=2), status="done")
    rule = {
        "when": {
            "type": "group",
            "mode": "all",
            "items": [{"type": "condition", "field": "status", "op": "is", "value": ["failed"]}],
        },
        "action": "delete",
    }
    saved = client.put("/api/settings/retention", json={"rules": [rule]})
    assert saved.status_code == 200, saved.text
    # saving the rules already applied them: the pass has nothing left of that kind, and the failed one is gone
    assert failed not in _ids(seed.path)
    assert _entries(_plan(client))["executions_rules"] == 0


# ── the log, shrinking, the numbers ───────────────────────────────────


def test_a_pass_truncates_the_write_ahead_log(client: TestClient) -> None:
    seed = Seed(client)
    task = make_task(client, "Alpha")
    seed.add(task)
    report = client.post(f"{STORAGE}/clean").json()
    assert report["wal"]["truncated"] is True
    assert report["after"]["wal_bytes"] == 0


def test_shrink_is_refused_with_too_little_free_space_and_nothing_is_rewritten(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Usage:
        free = 0

    monkeypatch.setattr("openartifact.engine.storage.shutil.disk_usage", lambda _path: Usage())
    response = client.post(f"{STORAGE}/shrink")
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "not_enough_space"
    assert "Shrinking needs about" in str(body) and "MiB are free" in str(body)


def test_shrink_rewrites_the_file_and_leaves_the_log_empty(client: TestClient) -> None:
    seed = Seed(client)
    task = make_task(client, "Alpha")
    execution_id = seed.add(task)
    _steps(seed.path, execution_id, outputs=["x" * 200_000])
    with sqlite3.connect(seed.path) as conn:
        conn.execute("DELETE FROM run_node_results")
    result = client.post(f"{STORAGE}/shrink")
    assert result.status_code == 200, result.text
    body = result.json()
    assert (
        body["after"]["file_bytes"] <= body["before"]["file_bytes"]
        and body["after"]["wal_bytes"] == 0
    )
    assert body["wal"]["truncated"] is True


def test_the_status_shows_the_file_the_pages_the_biggest_tables_and_the_warning(
    client: TestClient,
) -> None:
    status = client.get(STORAGE).json()
    db = status["db"]
    assert (
        db["file_bytes"] > 0 and db["pages"] > 0 and db["page_size"] > 0 and db["free_pages"] >= 0
    )
    assert (
        db["tables"]
        and db["tables_by"] in ("dbstat", "rows")
        and db["warn_bytes"] is None
        and db["over_warning"] is False
    )
    assert status["last_clean"] is None and status["interval_hours"] is None
    client.post(f"{STORAGE}/clean")
    assert client.get(STORAGE).json()["last_clean"]["entries"] == 0
    _set(client, storage_clean_interval_hours=6, storage_warn_mib=1)
    status = client.get(STORAGE).json()
    assert status["interval_hours"] == 6 and status["db"]["warn_bytes"] == 1024 * 1024


def test_the_warning_shows_when_the_file_is_larger_than_the_threshold(client: TestClient) -> None:
    assert storage.info(_db(client), 1)["over_warning"] is True
    assert storage.info(_db(client), 10**12)["over_warning"] is False


def test_the_cleaner_is_due_only_after_the_interval_the_user_set(client: TestClient) -> None:
    cleaner: Cleaner = client.app.state.storage  # type: ignore[attr-defined]
    assert _due(client, cleaner, NOW + timedelta(days=30)) is False  # no interval: never
    _set(client, storage_clean_interval_hours=2)
    assert _due(client, cleaner, NOW + timedelta(hours=1)) is False
    assert _due(client, cleaner, NOW + timedelta(hours=3)) is True
    client.post(f"{STORAGE}/clean")  # a pass resets the clock
    assert _due(client, cleaner, utc_now_plus(minutes=30)) is False


def _due(client: TestClient, cleaner: Cleaner, now: datetime) -> bool:
    assert client.portal is not None  # the client runs the application in its own event loop
    return bool(client.portal.call(cleaner.due, now))


def utc_now_plus(**delta: float) -> datetime:
    return datetime.now(UTC) + timedelta(**delta)


def test_a_second_pass_while_one_runs_is_refused() -> None:
    async def go() -> None:
        cleaner = Cleaner(lambda: None, None, Path("none.db"))  # type: ignore[arg-type]
        async with cleaner._lock:
            with pytest.raises(ArtifactError, match="already running") as busy:
                await cleaner.clean()
            assert busy.value.code == "busy"
            with pytest.raises(ArtifactError, match="already running"):
                await cleaner.shrink()

    asyncio.run(go())


# ── MCP: the preview is read only and nothing deletes ─────────────────


@pytest.fixture
def secured(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def test_mcp_shows_the_status_and_the_preview_and_has_no_tool_that_cleans_or_deletes(
    secured: TestClient,
) -> None:
    client = secured
    error, status = _tool(client, "get_storage_status")
    assert not error and status["db"]["file_bytes"] > 0
    error, preview = _tool(client, "preview_storage_cleanup")
    assert not error and preview["entries"] == 0
    names = {
        t["name"]
        for t in client.post(
            "/mcp",
            headers={**HEADERS, "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ).json()["result"]["tools"]
    }
    assert {"get_storage_status", "preview_storage_cleanup"} <= names
    assert not [
        n
        for n in names
        if "storage" in n and any(w in n for w in ("clean_", "shrink", "delete", "run_"))
    ]


def test_the_number_kept_is_applied_when_an_execution_starts_and_ends(client: TestClient) -> None:
    pipeline, task, _ = _use_chain(client, ("code", "Quick", _code("echo hi")))
    seed = Seed(client)
    for i in range(4):
        seed.add(task, at=NOW - timedelta(days=10 - i))
    with sqlite3.connect(
        seed.path
    ) as conn:  # the artifact's counter follows the four seeded executions
        conn.execute("UPDATE tasks SET execution_seq = 4 WHERE id = ?", (task["id"],))
    _set(client, storage_keep_executions=2)
    _start(client, pipeline, task)
    wait_for_run(client, task, "done")
    assert sorted(_numbers(seed.path)) == [
        4,
        5,
    ]  # the new one (5) and the one before it (4); 1 to 3 went
