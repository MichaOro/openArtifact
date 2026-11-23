"""The global execution list: filters, keyset paging, counters, the integration mirror, MCP, migration 0025."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import alembic_config, build_pipeline, make_task, post
from tests.test_history import HEADERS, MCP_HEADERS, TOKEN, _mcp_tool

BASE = datetime(2026, 11, 22, 12, 0, 0, tzinfo=UTC)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


def _db(client: TestClient) -> Path:
    settings = client.app.state.settings  # type: ignore[attr-defined]
    return Path(settings.data_dir / settings.database_filename)


class Seed:
    """Executions inserted straight into the database, so their times and numbers are exact."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.path = _db(client)
        self.numbers: dict[str, int] = {}

    def add(
        self,
        task: dict[str, Any],
        *,
        at: datetime = BASE,
        status: str = "done",
        by: str = "user",
        pipeline: str = "Flow",
        pipeline_id: str | None = None,
        note: str | None = None,
        execution_id: str | None = None,
    ) -> str:
        number = self.numbers[task["id"]] = self.numbers.get(task["id"], 0) + 1
        execution_id = execution_id or str(uuid.uuid4())
        finished = None if status == "running" else _stamp(at + timedelta(seconds=2))
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT INTO executions (id, task_id, number, pipeline_id, pipeline_name, status, note, "
                "started_by, created_at, started_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    execution_id,
                    task["id"],
                    number,
                    pipeline_id,
                    pipeline,
                    status,
                    note,
                    by,
                    _stamp(at),
                    _stamp(at),
                    finished,
                ),
            )
        return execution_id


@pytest.fixture
def seed(client: TestClient) -> Seed:
    return Seed(client)


def _list(client: TestClient, **query: Any) -> dict[str, Any]:
    response = client.get("/api/executions", params=query)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def _ids(page: dict[str, Any]) -> list[str]:
    return [item["id"] for item in page["items"]]


def _mix(client: TestClient, seed: Seed) -> dict[str, str]:
    """Two artifacts, several pipelines, statuses and origins; times one hour apart, oldest first."""
    a, b = make_task(client, "Alpha report"), make_task(client, "Beta_90% build")
    rows = {
        "a1": seed.add(a, at=BASE, status="done", by="user", pipeline="Build"),
        "a2": seed.add(
            a,
            at=BASE + timedelta(hours=1),
            status="failed",
            by="api",
            pipeline="Build",
            note="Disk full",
        ),
        "b1": seed.add(
            b, at=BASE + timedelta(hours=2), status="stopped", by="mcp", pipeline="Deploy"
        ),
        "b2": seed.add(
            b, at=BASE + timedelta(hours=3), status="running", by="system", pipeline="Deploy"
        ),
        "a3": seed.add(a, at=BASE + timedelta(hours=4), status="done", by="user", pipeline="Test"),
    }
    rows["a_number"] = a["number"]
    rows["b_number"] = b["number"]
    return rows


# ── shape ────────────────────────────────────────────────────────────


def test_the_list_is_newest_first_with_artifact_and_pipeline_exists(
    client: TestClient, seed: Seed
) -> None:
    rows = _mix(client, seed)
    page = _list(client)
    assert _ids(page) == [rows[k] for k in ("a3", "b2", "b1", "a2", "a1")]
    assert (page["total"], page["next_cursor"]) == (5, None)
    first = page["items"][0]
    assert first["task"] == {
        "id": first["task_id"],
        "number": rows["a_number"],
        "title": "Alpha report",
    }
    assert first["pipeline_exists"] is False  # seeded without a pipeline id
    assert first["started_at"].endswith("Z") and first["finished_at"].endswith("Z")
    assert first["duration_seconds"] == 2.0 and first["status"] == "done"
    assert "snapshot" not in first and "steps" not in first
    assert page["items"][1]["finished_at"] is None and page["items"][1]["duration_seconds"] is None


def test_an_empty_system_has_an_empty_list(client: TestClient) -> None:
    assert _list(client) == {
        "items": [],
        "next_cursor": None,
        "total": 0,
        "summary": {"running": 0, "failed_24h": 0, "done_24h": 0, "total": 0},
    }


# ── filters ──────────────────────────────────────────────────────────


def test_filters_one_by_one(client: TestClient, seed: Seed) -> None:
    r = _mix(client, seed)

    def ids(**q: Any) -> list[str]:
        return _ids(_list(client, **q))

    assert ids(status="failed") == [r["a2"]]
    assert ids(status="running,stopped") == [r["b2"], r["b1"]]
    assert ids(status=" Done , failed ") == [r["a3"], r["a2"], r["a1"]]
    assert ids(started_by="api,mcp") == [r["b1"], r["a2"]]
    assert ids(started_by="system") == [r["b2"]]
    assert ids(pipeline="deploy") == [r["b2"], r["b1"]]  # name substring, case-insensitive
    assert ids(pipeline="uil") == [r["a2"], r["a1"]]
    assert ids(pipeline="nothing") == []
    assert ids(q="alpha") == [r["a3"], r["a2"], r["a1"]]  # artifact title
    assert ids(q="90%") == [r["b2"], r["b1"]]  # '%' is literal
    assert ids(q="_") == [r["b2"], r["b1"]]  # '_' is literal (only Beta_100% has one)
    assert ids(q="disk") == [r["a2"]]  # note
    assert ids(q="tes") == [r["a3"]]  # pipeline name
    assert ids(q=f"#{r['b_number']}") == [r["b2"], r["b1"]]
    assert ids(q=str(r["a_number"])) == [r["a3"], r["a2"], r["a1"]]
    assert ids(q="  ") == ids()  # blank means no filter


def test_pipeline_filter_matches_the_id_exactly(client: TestClient, seed: Seed) -> None:
    task = make_task(client)
    pipeline_id = str(uuid.uuid4())
    one = seed.add(task, pipeline="Renamed later", pipeline_id=pipeline_id)
    seed.add(task, pipeline="Other", pipeline_id=str(uuid.uuid4()))
    assert _ids(_list(client, pipeline=pipeline_id)) == [one]
    assert _ids(_list(client, pipeline=pipeline_id[:8])) == []  # an id is not a substring match


def test_since_and_until_are_inclusive_and_utc(client: TestClient, seed: Seed) -> None:
    r = _mix(client, seed)
    stamp = (BASE + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    until = (BASE + timedelta(hours=3)).isoformat()
    assert _ids(_list(client, since=stamp)) == [r["a3"], r["b2"], r["b1"], r["a2"]]  # boundary kept
    assert _ids(_list(client, until=until)) == [r["b2"], r["b1"], r["a2"], r["a1"]]
    assert _ids(_list(client, since=stamp, until=until)) == [r["b2"], r["b1"], r["a2"]]
    assert _ids(_list(client, since=(BASE + timedelta(hours=1, microseconds=1)).isoformat())) == [
        r["a3"],
        r["b2"],
        r["b1"],
    ]
    # an offset is honoured, a time without one is UTC
    plus_two = (BASE + timedelta(hours=4)).astimezone(timezone_plus_two()).isoformat()
    assert _ids(_list(client, since=plus_two)) == [r["a3"]]
    assert _ids(_list(client, since="2026-11-22T16:00:00")) == [r["a3"]]


def timezone_plus_two() -> Any:
    from datetime import timezone

    return timezone(timedelta(hours=2))


def test_filters_combine_with_and(client: TestClient, seed: Seed) -> None:
    r = _mix(client, seed)
    assert _ids(_list(client, status="done", started_by="user", pipeline="build")) == [r["a1"]]
    assert _ids(
        _list(client, status="done,failed", q="alpha", since=_iso(BASE + timedelta(hours=1)))
    ) == [
        r["a3"],
        r["a2"],
    ]
    page = _list(client, status="done", limit=1)
    assert (page["total"], len(page["items"])) == (2, 1)
    assert _list(client, status="failed", started_by="user")["total"] == 0


def _iso(moment: datetime) -> str:
    return moment.isoformat()


@pytest.mark.parametrize(
    "query",
    [
        {"status": "running,bogus"},
        {"started_by": "robot"},
        {"since": "yesterday"},
        {"until": "2026-13-45"},
        {"cursor": "not-a-cursor"},
        {"limit": 0},
        {"limit": 201},
        {"limit": "many"},
    ],
)
def test_bad_values_are_422(client: TestClient, query: dict[str, Any]) -> None:
    assert client.get("/api/executions", params=query).status_code == 422


# ── paging ───────────────────────────────────────────────────────────


def test_the_cursor_walks_every_row_once_with_equal_timestamps(
    client: TestClient, seed: Seed
) -> None:
    task = make_task(client)
    for _ in range(7):
        seed.add(task, at=BASE)  # all at the same instant: only the id tells them apart
    seed.add(task, at=BASE + timedelta(minutes=1))
    seed.add(task, at=BASE - timedelta(minutes=1))
    everything = _ids(_list(client, limit=200))
    assert len(everything) == len(set(everything)) == 9
    walked: list[str] = []
    cursor = None
    while True:
        page = _list(client, limit=2, **({"cursor": cursor} if cursor else {}))
        assert page["total"] == 9
        walked += _ids(page)
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert walked == everything


def test_paging_is_stable_while_rows_are_inserted_and_deleted(
    client: TestClient, seed: Seed
) -> None:
    task = make_task(client)
    made = [seed.add(task, at=BASE + timedelta(minutes=i)) for i in range(6)]  # made[5] is newest
    first = _list(client, limit=2)
    assert _ids(first) == [made[5], made[4]]
    newest = seed.add(
        task, at=BASE + timedelta(hours=1)
    )  # lands before the cursor: not shown again
    seed.add(task, at=BASE - timedelta(hours=1))  # lands after: it appears in the end
    client.delete(f"/api/tasks/{task['id']}/executions/{made[4]}")  # the cursor's row itself
    rest: list[str] = []
    cursor = first["next_cursor"]
    while cursor:
        page = _list(client, limit=2, cursor=cursor)
        rest += _ids(page)
        cursor = page["next_cursor"]
    assert rest[:3] == [made[3], made[2], made[1]] and made[0] in rest and len(rest) == 5
    assert newest not in rest
    assert len(set(rest)) == len(rest)


def test_a_tampered_cursor_is_refused(client: TestClient, seed: Seed) -> None:
    task = make_task(client)
    for i in range(3):
        seed.add(task, at=BASE + timedelta(minutes=i))
    cursor = _list(client, limit=1)["next_cursor"]
    assert cursor
    for bad in (
        cursor[:-3],
        cursor + "AAAA",
        "!!!",
        "e30",
        "WyJ4Il0",
    ):  # cut, padded, not base64, {}, ["x"]
        assert client.get("/api/executions", params={"cursor": bad}).status_code == 422, bad
    import base64

    swapped = base64.urlsafe_b64encode(json.dumps(["not a time", "x"]).encode()).decode()
    assert client.get("/api/executions", params={"cursor": swapped}).status_code == 422
    numbers = base64.urlsafe_b64encode(json.dumps([1, 2]).encode()).decode()
    assert client.get("/api/executions", params={"cursor": numbers}).status_code == 422


# ── counters, pipelines and artifacts that go away ───────────────────


def test_total_and_summary(client: TestClient, seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    from openartifact.engine import history

    now = BASE + timedelta(hours=30)
    monkeypatch.setattr(history, "utcnow", lambda: now)
    task = make_task(client)
    seed.add(task, at=now - timedelta(hours=25), status="failed")  # too old for the 24 h counts
    seed.add(task, at=now - timedelta(hours=24), status="failed")  # exactly on the edge: counted
    seed.add(task, at=now - timedelta(hours=2), status="failed")
    seed.add(task, at=now - timedelta(hours=3), status="done")
    seed.add(task, at=now - timedelta(hours=26), status="done")
    seed.add(
        task, at=now - timedelta(hours=40), status="running"
    )  # running counts whenever it started
    seed.add(task, at=now - timedelta(hours=1), status="stopped")
    page = _list(client, status="failed", limit=1)
    assert page["total"] == 3 and len(page["items"]) == 1
    # the summary ignores the filters
    assert page["summary"] == {"running": 1, "failed_24h": 2, "done_24h": 1, "total": 7}
    assert _list(client, q="zzz")["summary"]["total"] == 7


def test_pipeline_exists_follows_the_pipeline(client: TestClient, seed: Seed) -> None:
    pipeline, task = build_pipeline(client, stages=1, name="Keeper"), make_task(client)
    seed.add(task, at=BASE, pipeline="Keeper", pipeline_id=pipeline["id"])
    assert _list(client)["items"][0]["pipeline_exists"] is True
    assert client.delete(f"/api/pipelines/{pipeline['id']}").status_code == 204
    item = _list(client)["items"][0]
    assert item["pipeline_exists"] is False and item["pipeline_name"] == "Keeper"
    assert _ids(_list(client, pipeline="keeper")) == [item["id"]]  # the name copy still finds it


def test_a_deleted_artifact_takes_its_executions_out(client: TestClient, seed: Seed) -> None:
    a, b = make_task(client, "Keep"), make_task(client, "Drop")
    seed.add(a)
    seed.add(b)
    assert _list(client)["total"] == 2
    assert client.delete(f"/api/tasks/{b['id']}").status_code == 204
    page = _list(client)
    assert (page["total"], page["summary"]["total"]) == (1, 1)
    assert page["items"][0]["task"]["title"] == "Keep"


def test_real_runs_show_up_with_their_origin(client: TestClient) -> None:
    pipeline, task = build_pipeline(client, stages=1, name="Live"), make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    from tests.helpers import wait_for_run

    wait_for_run(client, task, "done")
    item = _list(client)["items"][0]
    assert (item["status"], item["started_by"], item["pipeline_exists"]) == ("done", "user", True)
    assert item["task"]["number"] == task["number"]


# ── performance and the index ────────────────────────────────────────


def _bulk(client: TestClient, count: int) -> None:
    task = make_task(client)
    statuses = ("done", "failed", "stopped", "done")
    rows = [
        (
            str(uuid.uuid4()),
            task["id"],
            i + 1,
            f"Pipeline {i % 7}",
            statuses[i % 4],
            "user" if i % 3 else "api",
            _stamp(BASE + timedelta(seconds=i)),
            _stamp(BASE + timedelta(seconds=i)),
        )
        for i in range(count)
    ]
    with sqlite3.connect(_db(client)) as conn:
        conn.executemany(
            "INSERT INTO executions (id, task_id, number, pipeline_name, status, started_by, created_at, "
            "started_at) VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )


def test_the_default_listing_uses_the_index_and_stays_fast(client: TestClient) -> None:
    _bulk(client, 3000)
    started = time.perf_counter()
    page = _list(client, limit=50)
    pages = _list(client, limit=50, cursor=page["next_cursor"])
    status = _list(client, status="failed", limit=50)
    elapsed = time.perf_counter() - started
    assert (len(page["items"]), page["total"], page["summary"]["total"]) == (50, 3000, 3000)
    assert len(pages["items"]) == 50 and status["total"] == 750
    assert elapsed < 1.0, elapsed

    with sqlite3.connect(_db(client)) as conn:

        def plan(sql: str) -> str:
            return " | ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql))

        listing = plan(
            "SELECT * FROM executions JOIN tasks ON tasks.id = executions.task_id "
            "ORDER BY executions.started_at DESC, executions.id DESC LIMIT 51"
        )
        assert "ix_executions_started_at" in listing and "TEMP B-TREE" not in listing, listing
        paged = plan(
            "SELECT * FROM executions WHERE (started_at, id) < ('2026-11-22 12:10:00.000000', 'x') "
            "ORDER BY started_at DESC, id DESC LIMIT 51"
        )
        assert "ix_executions_started_at" in paged and "TEMP B-TREE" not in paged, paged
        by_status = plan(
            "SELECT * FROM executions WHERE status IN ('failed') "
            "ORDER BY started_at DESC, id DESC LIMIT 51"
        )
        assert "ix_executions_status_started_at" in by_status and "TEMP B-TREE" not in by_status, (
            by_status
        )


# ── integration API and MCP ──────────────────────────────────────────


@pytest.fixture
def secured(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def test_the_integration_api_mirrors_the_list_and_needs_the_token(secured: TestClient) -> None:
    seeded = Seed(secured)
    r = _mix(secured, seeded)
    v1 = secured.get("/api/v1/executions", params={"status": "done", "limit": 1}).json()
    assert v1["total"] == 2 and _ids(v1) == [r["a3"]] and v1["next_cursor"]
    assert secured.get("/api/v1/executions", params={"limit": 500}).status_code == 422
    assert secured.get("/api/v1/executions", params={"status": "x"}).status_code == 422
    assert _ids(_list(secured, status="done", limit=1)) == _ids(v1)
    bare = TestClient(secured.app)
    assert bare.get("/api/v1/executions").status_code == 401
    assert bare.get("/api/executions").status_code == 401  # the access gate


def test_mcp_lists_all_executions(secured: TestClient) -> None:
    r = _mix(secured, Seed(secured))
    result = _mcp_tool(
        secured, "list_all_executions", status="failed,running", query="beta", limit=5
    )
    data = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    assert [i["id"] for i in data["items"]] == [r["b2"]] and data["total"] == 1
    assert data["summary"]["total"] == 5
    assert _mcp_tool(secured, "list_all_executions", limit=201)["isError"] is True
    assert _mcp_tool(secured, "list_all_executions", status="nope")["isError"] is True
    assert _mcp_tool(secured, "list_all_executions", cursor="bad")["isError"] is True
    names = {
        t["name"]
        for t in secured.post(
            "/mcp",
            headers=MCP_HEADERS,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        ).json()["result"]["tools"]
    }
    assert "list_all_executions" in names


# ── migration 0025 ───────────────────────────────────────────────────

INDEXES = {"ix_executions_started_at", "ix_executions_status_started_at"}


def _indexes(path: Path) -> set[str]:
    with sqlite3.connect(path) as conn:
        return {r[1] for r in conn.execute("PRAGMA index_list(executions)")}


def test_migration_0025_adds_the_indexes_and_goes_down_and_up(
    unmigrated_settings: Settings,
) -> None:
    path = unmigrated_settings.data_dir / unmigrated_settings.database_filename
    cfg = alembic_config()
    command.upgrade(cfg, "0024")
    assert not INDEXES & _indexes(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, status, number, position, created_by, created_at, updated_at) "
            "VALUES ('t', 'T', 'backlog', 1, 0, 'user', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO executions (id, task_id, number, status, started_by, created_at, started_at) "
            "VALUES ('e', 't', 1, 'done', 'user', '2026-01-01', '2026-01-01')"
        )
    command.upgrade(cfg, "0025")
    assert _indexes(path) >= INDEXES
    command.downgrade(cfg, "0024")
    assert not INDEXES & _indexes(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM executions").fetchone() == (1,)  # data untouched
    command.upgrade(cfg, "head")
    assert _indexes(path) >= INDEXES


# ── deleting several at once ─────────────────────────────────────────


def test_several_executions_of_different_artifacts_are_deleted_at_once_and_a_running_one_stays(
    client: TestClient, seed: Seed
) -> None:
    a, b = make_task(client, "Alpha"), make_task(client, "Beta")
    done_a = seed.add(a, at=BASE, status="done")
    failed_b = seed.add(b, at=BASE + timedelta(hours=1), status="failed")
    running = seed.add(b, at=BASE + timedelta(hours=2), status="running")
    kept = seed.add(a, at=BASE + timedelta(hours=3), status="done")

    response = client.post(
        "/api/executions/delete",
        json={"ids": [done_a, failed_b, running, "no-such-id", done_a]},
    )
    assert response.status_code == 200, response.text
    # the duplicate counts once, the unknown id is simply gone already, the running one is refused and named
    assert response.json() == {"deleted": 2, "skipped_running": 1}
    assert set(_ids(_list(client))) == {running, kept}


def test_deleting_several_needs_ids_and_not_too_many(client: TestClient) -> None:
    assert client.post("/api/executions/delete", json={"ids": []}).status_code == 422
    assert client.post("/api/executions/delete", json={}).status_code == 422
    too_many = client.post("/api/executions/delete", json={"ids": [str(i) for i in range(501)]})
    assert too_many.status_code == 422
