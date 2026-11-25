"""The SQLite node and the SQLite Tool (ADR-068): read-only SQL on the application's data through the ``v_guard_*`` views, enforced by
the engine's authorizer. The attacks are tested as the model or an author would make them, not only the polite uses."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from openartifact.config import Settings
from openartifact.engine import guard_views
from openartifact.engine.context import NodeIndex, RunContext, RunView
from openartifact.engine.sqlite_runner import (
    DataSource,
    SqliteError,
    application_source,
    blocked_names,
    query,
    run_sqlite,
)

NOW = "2026-11-25 10:00:00"


@pytest.fixture
def db(migrated_settings: Settings) -> Path:
    """A migrated database with a little of everything, and the views."""
    path = migrated_settings.data_dir / migrated_settings.database_filename
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, body, status, number, position, created_by, execution_seq, created_at, updated_at) "
            "VALUES ('t1', 'Card one', 'a secret body', 'backlog', 1, 0, 'api', 0, ?, ?)",
            (NOW, NOW),
        )
        conn.execute(
            "INSERT INTO tasks (id, title, body, status, number, position, created_by, execution_seq, created_at, updated_at) "
            "VALUES ('t2', 'Card two', '', 'done', 2, 0, 'api', 0, ?, ?)",
            (NOW, NOW),
        )
        conn.execute(
            "INSERT INTO executions (id, task_id, number, pipeline_name, status, started_by, step_count, snapshot, context, created_at, started_at) "
            "VALUES ('e1', 't1', 1, 'Flow', 'running', 'api', 3, '{}', '{\"vars\": {\"x\": \"CONTEXT-VALUE\"}}', ?, ?)",
            (NOW, NOW),
        )
        detail = {
            "turns": [
                {
                    "tool_calls": [
                        {
                            "tool": "get_file",
                            "node_name": "GitHub MCP",
                            "arguments": '{"path":"README.md"}',
                            "error": False,
                            "duration_ms": 10,
                        }
                    ]
                },
                {
                    "tool_calls": [
                        {
                            "tool": "get_file",
                            "node_name": "GitHub MCP",
                            "arguments": '{"path":"README.md"}',
                            "error": True,
                            "duration_ms": 12,
                        }
                    ]
                },
            ]
        }
        conn.execute(
            "INSERT INTO run_node_results (id, run_id, execution_id, seq, node_id, node_name, kind, outcome, output, detail, started_at, finished_at) "
            "VALUES ('r1', 'run1', 'e1', 1, 'n1', 'Agent', 'agent', 'pass', 'OUTPUT-TEXT', ?, ?, ?)",
            (json.dumps(detail), NOW, NOW),
        )
        conn.commit()
    guard_views.install(path)
    return path


def _has(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return column in [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _q(db: Path, sql: str, *values: str, **limits: Any) -> list[dict[str, Any]]:
    return query(application_source(db), sql, values, **limits).rows


def test_a_view_is_read_and_the_rows_come_back_as_objects(db: Path) -> None:
    rows = _q(db, "SELECT lane, count(*) AS n FROM v_guard_artifacts GROUP BY lane ORDER BY lane")
    assert rows == [{"lane": "backlog", "n": 1}, {"lane": "done", "n": 1}]
    assert _q(db, "SELECT status, step_count FROM v_guard_runs") == [
        {"status": "running", "step_count": 3}
    ]
    assert [r["kind"] for r in _q(db, "SELECT kind FROM v_guard_steps")] == ["agent"]


def test_the_tool_calls_of_an_agent_step_are_a_view_with_the_arguments_cut_short(db: Path) -> None:
    rows = _q(
        db,
        "SELECT tool, arguments, count(*) AS calls, sum(is_error) AS failed FROM v_guard_tool_calls GROUP BY tool, arguments",
    )
    assert rows == [
        {"tool": "get_file", "arguments": '{"path":"README.md"}', "calls": 2, "failed": 1}
    ]
    # the same call twice is what a guard counts as a repeat; different arguments would be two rows


def test_values_are_bound_as_parameters(db: Path) -> None:
    assert _q(db, "SELECT title FROM v_guard_artifacts WHERE lane = ?1", "done") == [
        {"title": "Card two"}
    ]
    assert _q(db, "SELECT title FROM v_guard_artifacts WHERE lane = ?1", "done' OR '1'='1") == []


def test_rows_and_bytes_are_limited_and_the_result_says_so(db: Path) -> None:
    result = query(application_source(db), "SELECT * FROM v_guard_artifacts", max_rows=1)
    assert (len(result.rows), result.truncated) == (1, True)
    small = query(application_source(db), "SELECT title FROM v_guard_artifacts", max_bytes=30)
    assert small.truncated is True and len(small.rows) < 2


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO v_guard_lanes VALUES ('x', 'X', 9)",
        "UPDATE tasks SET title = 'x'",
        "DELETE FROM tasks",
        "DROP TABLE tasks",
        "DROP VIEW v_guard_runs",
        "CREATE TABLE evil (a)",
        "CREATE TEMP TABLE evil (a)",
        "CREATE VIEW v_evil AS SELECT * FROM tasks",
        "ALTER TABLE tasks ADD COLUMN x",
        "PRAGMA table_info(tasks)",
        "PRAGMA writable_schema = 1",
        "PRAGMA query_only = OFF",
        "ATTACH DATABASE '/tmp/evil.db' AS evil",
        "DETACH DATABASE main",
        "VACUUM",
        "REINDEX",
        "ANALYZE",
        "BEGIN",
        "SAVEPOINT a",
        "SELECT load_extension('/tmp/evil.so')",
        "SELECT fts3_tokenizer('x', x'00')",
    ],
)
def test_a_statement_that_changes_or_reaches_out_is_refused(db: Path, sql: str) -> None:
    before = _q(db, "SELECT count(*) AS n FROM v_guard_artifacts")
    with pytest.raises(SqliteError):
        _q(db, sql)
    assert _q(db, "SELECT count(*) AS n FROM v_guard_artifacts") == before


def test_more_than_one_statement_is_refused(db: Path) -> None:
    with pytest.raises(SqliteError, match="One statement only"):
        _q(db, "SELECT 1; DELETE FROM tasks")
    with pytest.raises(SqliteError, match="One statement only"):
        _q(db, "SELECT 1; SELECT 2")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM tasks",  # a table is read through a view only
        "SELECT * FROM executions",
        "SELECT * FROM run_node_results",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM sqlite_schema",
        "SELECT * FROM secrets",
        "SELECT * FROM credentials",
        "SELECT * FROM internal_tokens",
        "SELECT * FROM llm_providers",
        "SELECT * FROM app_settings",
        "SELECT * FROM main.tasks",
        "SELECT * FROM temp.sqlite_master",
        "SELECT title FROM (SELECT * FROM tasks)",
        "WITH t AS (SELECT * FROM tasks) SELECT title FROM t",
        "SELECT (SELECT body FROM tasks LIMIT 1)",
        "SELECT title FROM v_guard_artifacts WHERE id IN (SELECT id FROM tasks)",
        "SELECT * FROM v_guard_artifacts JOIN tasks ON tasks.id = v_guard_artifacts.id",
        "SELECT * FROM pragma_table_info('tasks')",
        "SELECT * FROM json_each('[1]') JOIN tasks",
    ],
)
def test_a_table_is_never_read_directly_and_the_secrets_not_at_all(db: Path, sql: str) -> None:
    with pytest.raises(SqliteError, match=r"Not allowed here|not valid"):
        _q(db, sql)


def test_the_content_columns_are_not_in_the_views(db: Path) -> None:
    for column, view in (
        ("body", "v_guard_artifacts"),
        ("output", "v_guard_steps"),
        ("context", "v_guard_runs"),
        ("detail", "v_guard_steps"),
    ):
        with pytest.raises(SqliteError):
            _q(db, f"SELECT {column} FROM {view}")


def test_the_floor_holds_even_through_a_view_that_would_read_a_secret(db: Path) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE VIEW v_guard_leak AS SELECT name, value FROM secrets") if _has(
            conn, "secrets", "value"
        ) else None
        conn.execute("CREATE VIEW v_guard_leak2 AS SELECT key, value FROM app_settings")
        conn.commit()
    source = DataSource("app", "x", db, frozenset({"v_guard_leak", "v_guard_leak2"}))
    for view in ("v_guard_leak", "v_guard_leak2"):
        with pytest.raises(SqliteError, match="Not allowed here"):
            query(source, f"SELECT * FROM {view}")


def test_what_the_author_blocks_is_refused_even_through_a_view(db: Path) -> None:
    assert _q(db, "SELECT title FROM v_guard_artifacts WHERE number = 1")
    with pytest.raises(SqliteError, match="Not allowed here"):
        _q(db, "SELECT title FROM v_guard_artifacts", blocked=blocked_names("tasks.title"))
    with pytest.raises(SqliteError, match="Not allowed here"):
        _q(db, "SELECT * FROM v_guard_artifacts", blocked=blocked_names("tasks"))
    # a blocked column the view does not read changes nothing; one it reads makes the whole view unreadable (a view reads all its columns)
    assert _q(
        db,
        "SELECT number FROM v_guard_artifacts WHERE number = 1",
        blocked=blocked_names("tasks.body"),
    ) == [{"number": 1}]
    with pytest.raises(SqliteError, match="Not allowed here"):
        _q(db, "SELECT number FROM v_guard_artifacts", blocked=blocked_names("tasks.title"))
    for bad in ("tasks;drop", "a.b.c", "1table", "ta sks"):
        with pytest.raises(SqliteError, match="blocked list"):
            blocked_names(bad)


def test_a_statement_that_runs_for_ever_is_interrupted_at_the_time_limit(db: Path) -> None:
    with pytest.raises(SqliteError, match="took longer than"):
        _q(
            db,
            "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT count(*) FROM c",
            timeout=0.5,
        )


def test_a_data_source_that_is_not_there_fails_in_words(db: Path) -> None:
    gone = DataSource("app", "x", db.parent / "nope.db", frozenset({"v_guard_runs"}))
    with pytest.raises(SqliteError, match=r"cannot be opened|not valid|failed"):
        query(gone, "SELECT * FROM v_guard_runs")


async def test_the_node_runs_the_query_with_its_values_and_leaves_rows_data_and_output(
    db: Path,
) -> None:
    sources = {"app": application_source(db)}
    view = RunView(RunContext({"vars": {}}), NodeIndex())
    ok = await run_sqlite(
        {
            "query": "SELECT title FROM v_guard_artifacts WHERE lane = ?1",
            "values": "backlog",
            "timeout_seconds": 5,
            "max_rows": 10,
        },
        sources,
        view=view,
    )
    assert ok.outcome == "pass"
    assert ok.data["rows"] == [{"title": "Card one"}] and ok.data["row_count"] == 1
    assert json.loads(ok.output or "[]") == [{"title": "Card one"}]
    refused = await run_sqlite({"query": "SELECT * FROM tasks"}, sources, view=view)
    assert refused.outcome == "fail" and "Not allowed here" in (refused.reason or "")
    unknown = await run_sqlite({"source": "other", "query": "SELECT 1"}, sources, view=view)
    assert unknown.outcome == "fail" and "'other' is not there" in (unknown.reason or "")


@pytest.mark.parametrize(
    "sql",
    [
        'SELECT title FROM "tasks"',
        "SELECT title FROM [tasks]",
        "SELECT title FROM `tasks`",
        "SELECT title FROM TASKS",
        "SELECT TITLE FROM Tasks",
        # a WITH that is named like a listed view reads no more than that view reads
        "WITH v_guard_artifacts AS (SELECT body AS title FROM tasks) SELECT title FROM v_guard_artifacts",
        "WITH v_guard_artifacts AS (SELECT * FROM tasks) SELECT * FROM v_guard_artifacts",
        "WITH v_guard_runs AS (SELECT value FROM app_settings) SELECT * FROM v_guard_runs",
        "SELECT body FROM v_guard_artifacts",
        "SELECT a.title FROM v_guard_artifacts a, tasks b WHERE b.body LIKE '%secret%'",
        "SELECT title FROM v_guard_artifacts UNION SELECT body FROM tasks",
    ],
)
def test_naming_the_table_in_another_way_or_shadowing_a_view_reads_nothing_more(
    db: Path, sql: str
) -> None:
    with pytest.raises(SqliteError, match=r"Not allowed here|no such column"):
        _q(db, sql)


def test_a_count_shows_how_many_rows_and_never_what_is_in_them(db: Path) -> None:
    assert _q(db, "SELECT count(*) AS n FROM v_guard_artifacts") == [{"n": 2}]
    assert _q(db, "SELECT count(*) AS n FROM tasks") == [{"n": 2}], (
        "a count of a table: the rows, not their content"
    )
    with pytest.raises(SqliteError):
        _q(db, "SELECT count(*) AS n FROM secrets")  # the floor: not even a count
    with pytest.raises(SqliteError):
        _q(db, "SELECT count(*) AS n FROM tasks", blocked=blocked_names("tasks"))


# ── the node in the graph: only a guard action may hold it ───────────


def test_the_sqlite_node_and_tool_are_for_guard_actions_only_and_the_server_keeps_it(
    client: Any,
) -> None:
    from tests.helpers import graph_url, node, post

    kinds = {t["kind"]: t for t in client.get("/api/node-types").json()}
    for kind in ("sqlite", "sqlite_tool"):
        assert kinds[kind]["purposes"] == ["guard"], kind
    assert kinds["sqlite"]["menu"]["group"] == kinds["postgres"]["menu"]["group"] == "Apps and data"
    judge = post(client, "/api/actions", name="Judge", purpose="guard")
    plain = post(client, "/api/actions", name="Plain")
    assert node(client, judge, "sqlite")["kind"] == "sqlite"
    assert node(client, judge, "sqlite_tool")["kind"] == "sqlite_tool"
    for kind in ("sqlite", "sqlite_tool"):
        refused = client.post(f"{graph_url(plain)}/nodes", json={"kind": kind})
        assert refused.status_code == 422, kind
        assert "can only be used in a guard action" in refused.json()["detail"]
    # an action that holds one cannot become a pipeline action
    blocked = client.patch(graph_url(judge), json={"purpose": "pipeline"})
    assert blocked.status_code == 409 and "SQLite" in blocked.json()["detail"]
    # a pipeline cannot hold it at all
    pipeline = post(client, "/api/pipelines", name="P")
    assert client.post(f"{graph_url(pipeline)}/nodes", json={"kind": "sqlite"}).status_code == 422


def test_the_settings_of_the_node_are_checked_when_they_are_saved(client: Any) -> None:
    from tests.helpers import graph_url, node, post

    judge = post(client, "/api/actions", name="Judge", purpose="guard")
    made = node(client, judge, "sqlite")
    url = f"{graph_url(judge)}/nodes/{made['id']}"
    refused = client.patch(url, json={"config": {"query": "SELECT ${var.id}"}})
    assert refused.status_code == 422 and "never made part of the query text" in refused.text
    refused = client.patch(url, json={"config": {"blocked": "a.b.c"}})
    assert refused.status_code == 422 and "blocked list" in refused.text
    ok = client.patch(
        url,
        json={"config": {"query": "SELECT 1", "blocked": "tasks.title\nlanes", "source": "app"}},
    )
    assert ok.status_code == 200, ok.text
    assert client.patch(url, json={"config": {"source": "elsewhere"}}).status_code == 422, (
        "a data source is chosen, not typed"
    )


async def test_the_tool_answers_an_agent_with_rows_and_with_the_refusal_as_text(db: Path) -> None:
    from openartifact.agents.tools import ToolContext, open_toolbox
    from openartifact.engine.executors import Limits

    limits = Limits(data_sources={"app": application_source(db)})
    frozen = [
        {
            "kind": "sqlite_tool",
            "name": "Runs",
            "tool_name": "lane_count",
            "config": {
                "query": "SELECT count(*) AS n FROM v_guard_artifacts WHERE lane = ?1",
                "parameters": "lane: The lane to count",
            },
        },
        {
            "kind": "sqlite_tool",
            "name": "Bad",
            "tool_name": "raw",
            "config": {"query": "SELECT title FROM tasks"},
        },
    ]
    async with open_toolbox(
        frozen,
        ToolContext({}, False, limits=limits, view=RunView(RunContext({"vars": {}}), NodeIndex())),
    ) as box:
        ok = await box.call("c1", "lane_count", '{"lane": "backlog"}')
        assert json.loads(ok.result)["rows"] == [{"n": 1}] and not ok.error
        missing = await box.call("c2", "lane_count", "{}")
        assert missing.error and "lane is missing" in missing.result
        refused = await box.call("c3", "raw", "{}")
        assert refused.error and "Not allowed here" in refused.result
