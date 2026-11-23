"""The Postgres node and the Postgres Tool in a run (ADR-041): the secret, references, the switches, masking."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.agents.tools import (
    TOOL_RESULT_LIMIT_BYTES,
    ToolboxError,
    ToolContext,
    open_toolbox,
)
from openartifact.engine.context import NodeIndex, RunContext, RunView
from openartifact.engine.executors import Limits
from tests.agent_support import FakeLlm, completion, make_agent, make_provider, put_secret
from tests.helpers import build_pipeline as _pipeline
from tests.helpers import connect as _connect
from tests.helpers import graph_url as _url
from tests.helpers import make_task as _make_task
from tests.helpers import node as _node
from tests.helpers import post, wait_for_run
from tests.helpers import wait_for_run as _wait
from tests.postgres_support import PgDb
from tests.test_agent_tools_run import api, llm, run_and_step, tool_answer, tool_flow
from tests.test_execution_nodes import Make, _definition, _start, _use, make_client

__all__ = ["api", "llm", "make_client"]  # fixtures, used by name

TOKEN = "t" * 40
VIEW = RunView(RunContext({"vars": {"status": "open"}}), NodeIndex())


def _client(make: Make, pg: PgDb, **overrides: Any) -> TestClient:
    """A client with a token and a secret store, the loopback allowed for HTTP-like nodes, and the secret
    ``TICKETS_DB`` holding the URL of the test database."""
    overrides.setdefault("http_allow_private_networks", True)
    client = make(api_token=TOKEN, secret_key="s" * 40, **overrides)
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    assert client.put("/api/secrets/TICKETS_DB", json={"value": pg.url}).status_code in (200, 201)
    return client


def _steps(run: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in run["node_results"] if r["kind"] == "postgres"]


def _flow(client: TestClient, status: str, **config: Any) -> dict[str, Any]:
    """Run trigger -> Postgres node -> Output with this config; the node's step."""
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    config.setdefault("secret", "TICKETS_DB")
    config.setdefault("allow_private", True)
    _use(client, pipeline, _definition(client, "postgres", **config))
    _start(client, pipeline, task)
    (step,) = _steps(_wait(client, task, status))
    return step


def _tickets(pg: PgDb) -> None:
    pg.sql("CREATE TABLE tickets (id int PRIMARY KEY, title text, status text)")
    pg.sql(
        "INSERT INTO tickets VALUES (1, 'Login is broken', 'open'), (2, 'Slow search', 'open'),"
        " (3, 'Typo', 'closed')"
    )


# ── the node ─────────────────────────────────────────────────────────


def test_the_node_returns_the_rows_as_a_list_in_data_and_as_json_in_the_output(
    make_client: Make, pg: PgDb
) -> None:
    _tickets(pg)
    client = _client(make_client, pg)
    step = _flow(
        client,
        "done",
        query="SELECT id, title FROM tickets WHERE status = $1 ORDER BY id",
        values="open",
    )
    assert step["outcome"] == "pass"
    assert step["data"]["rows"] == [
        {"id": 1, "title": "Login is broken"},
        {"id": 2, "title": "Slow search"},
    ]
    assert (step["data"]["columns"], step["data"]["row_count"], step["data"]["truncated"]) == (
        ["id", "title"],
        2,
        False,
    )
    assert json.loads(step["output"]) == step["data"]["rows"]


def test_values_come_from_earlier_results_and_are_bound_not_pasted(
    make_client: Make, pg: PgDb
) -> None:
    _tickets(pg)
    client = _client(make_client, pg)
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    action = _definition(client, "postgres", secret="TICKETS_DB", allow_private=True)
    prepare = _node(
        client,
        action,
        "code",
        name="Prepare",
        config={"language": "sh", "code": "printf %s \"x' OR '1'='1\""},
    )
    database = action["node"]
    client.patch(
        f"{_url(action)}/nodes/{database['id']}",
        json={
            "config": {
                "query": "SELECT count(*) AS n FROM tickets WHERE title = $1",
                "values": "${node.Prepare.output}",
            }
        },
    )
    edges = client.get(_url(action)).json()["edges"]
    trigger_edge = next(e for e in edges if e["target_id"] == database["id"])
    client.delete(f"{_url(action)}/edges/{trigger_edge['id']}")
    trigger = next(n for n in client.get(_url(action)).json()["nodes"] if n["kind"] == "trigger")
    _connect(client, action, trigger, "out", prepare, "in")
    _connect(client, action, prepare, "pass", database, "in")
    _use(client, pipeline, action)
    _start(client, pipeline, task)
    (step,) = _steps(_wait(client, task, "done"))
    assert step["data"]["rows"] == [{"n": 0}]  # the quote did not end the string: nothing matched


def test_by_default_the_node_cannot_change_anything_and_says_how_to_allow_it(
    make_client: Make, pg: PgDb
) -> None:
    _tickets(pg)
    client = _client(make_client, pg)
    step = _flow(client, "failed", query="DELETE FROM tickets")
    assert step["outcome"] == "fail"
    assert "read-only" in step["reason"] and "Allow changes" in step["reason"]
    assert pg.sql("SELECT count(*) FROM tickets") == [(3,)]


def test_with_changes_allowed_the_statement_is_committed(make_client: Make, pg: PgDb) -> None:
    _tickets(pg)
    client = _client(make_client, pg)
    step = _flow(
        client,
        "done",
        query="UPDATE tickets SET status = $1 WHERE status = 'open' RETURNING id",
        values="closed",
        allow_write=True,
    )
    assert [r["id"] for r in step["data"]["rows"]] == [1, 2]
    assert pg.sql("SELECT count(*) FROM tickets WHERE status = 'closed'") == [(3,)]


def test_max_rows_cuts_the_list_and_says_so(make_client: Make, pg: PgDb) -> None:
    client = _client(make_client, pg)
    step = _flow(client, "done", query="SELECT g FROM generate_series(1, 50) g", max_rows=3)
    assert [r["g"] for r in step["data"]["rows"]] == [1, 2, 3]
    assert step["data"]["truncated"] is True


def test_the_time_limit_of_the_node_stops_the_statement(make_client: Make, pg: PgDb) -> None:
    client = _client(make_client, pg)
    step = _flow(client, "failed", query="SELECT pg_sleep(30)", timeout_seconds=1)
    assert step["reason"].startswith("Timeout after 1 s")


@pytest.mark.parametrize(
    ("operator", "node_switch"), [(True, False), (False, True), (False, False)]
)
def test_a_private_database_needs_the_switch_of_the_node_and_the_operators(
    make_client: Make, pg: PgDb, operator: bool, node_switch: bool
) -> None:
    client = _client(make_client, pg, http_allow_private_networks=operator)
    step = _flow(client, "failed", query="SELECT 1", allow_private=node_switch)
    assert "private network address" in step["reason"]


def test_a_node_without_a_secret_or_with_an_unknown_one_fails_clearly(
    make_client: Make, pg: PgDb
) -> None:
    client = _client(make_client, pg)
    empty = _flow(client, "failed", query="SELECT 1", secret="")
    assert empty["reason"] == "No secret with the connection URL is set"
    unknown = _flow(client, "failed", query="SELECT 1", secret="NOT_STORED")
    assert "NOT_STORED" in unknown["reason"]
    no_query = _flow(client, "failed", query="")
    assert no_query["reason"] == "The query is empty"


def test_a_value_the_query_does_not_use_fails_before_the_database_is_asked(
    make_client: Make, pg: PgDb
) -> None:
    client = _client(make_client, pg)
    step = _flow(client, "failed", query="SELECT 1", values="stray")
    assert step["reason"] == "Value 1 is not used by the query (no $1 in it)"


def test_a_reference_that_cannot_be_resolved_fails_naming_it(make_client: Make, pg: PgDb) -> None:
    client = _client(make_client, pg)
    step = _flow(client, "failed", query="SELECT $1", values="${var.nothing}")
    assert "${var.nothing}" in step["reason"]


def test_a_url_pasted_into_the_query_by_mistake_is_masked_in_the_result(
    make_client: Make, pg: PgDb
) -> None:
    pg.sql(f"CREATE ROLE {pg.role} LOGIN PASSWORD 'pw-of-the-reader'")
    reader = pg.url_as(pg.role, "pw-of-the-reader")
    client = _client(make_client, pg)
    assert client.put("/api/secrets/READER_DB", json={"value": reader}).status_code in (200, 201)
    step = _flow(client, "done", secret="READER_DB", query=f"SELECT '{reader}' AS leak")
    assert reader not in json.dumps(step) and "***" in step["output"]


def test_a_failed_login_and_the_stored_run_hold_no_password_user_or_address(
    make_client: Make, pg: PgDb
) -> None:
    pg.sql(f"CREATE ROLE {pg.role} LOGIN PASSWORD 'pw-of-the-reader'")
    client = _client(make_client, pg)
    for name, password in (("READER_DB", "pw-of-the-reader"), ("WRONG_DB", "not-the-password")):
        stored = client.put(f"/api/secrets/{name}", json={"value": pg.url_as(pg.role, password)})
        assert stored.status_code in (200, 201)
    worked = _flow(client, "done", secret="READER_DB", query="SELECT current_user AS who")
    assert worked["data"]["rows"] == [{"who": pg.role}]
    failed = _flow(client, "failed", secret="WRONG_DB", query="SELECT 1")
    assert (
        failed["reason"]
        == "Could not connect to the database: the user or the password was refused"
    )
    # nothing of a URL is in the database of the application: the snapshots and the results were written
    settings = client.app.state.settings  # type: ignore[attr-defined]
    with sqlite3.connect(settings.data_dir / settings.database_filename) as db:
        dump = "\n".join(db.iterdump())
    for text in ("pw-of-the-reader", "not-the-password", ":pw@127.0.0.1"):
        assert text not in dump


# ── the tool ─────────────────────────────────────────────────────────


def _tool(**config: Any) -> dict[str, Any]:
    base = {
        "secret": "TICKETS_DB",
        "query": "SELECT id, title FROM tickets WHERE status = $1 AND id >= $2::int ORDER BY id",
        "parameters": "status: open or closed\nfirst: The lowest ticket number",
        "allow_private": True,
        "timeout_seconds": 10,
    }
    return {
        "node_id": "t1",
        "name": "Tickets",
        "kind": "postgres_tool",
        "tool_name": "find_tickets",
        "config": {**base, **config},
    }


async def _call(pg: PgDb, tool: dict[str, Any], arguments: dict[str, Any], **context: Any) -> str:
    secrets = context.pop("secrets", {"TICKETS_DB": pg.url})
    private = context.pop("private", True)
    async with open_toolbox(
        [tool], ToolContext(secrets, private, limits=Limits(), view=VIEW)
    ) as box:
        (schema,) = box.schemas()
        record = await box.call("c1", schema["function"]["name"], json.dumps(arguments))
        return record.result


async def test_the_tool_offers_its_parameters_and_answers_with_the_rows(pg: PgDb) -> None:
    _tickets(pg)
    async with open_toolbox(
        [_tool()], ToolContext({"TICKETS_DB": pg.url}, True, limits=Limits(), view=VIEW)
    ) as box:
        (schema,) = box.schemas()
        assert schema["function"]["name"] == "find_tickets"
        assert schema["function"]["parameters"] == {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "open or closed"},
                "first": {"type": "string", "description": "The lowest ticket number"},
            },
            "required": ["status", "first"],
        }
        record = await box.call("c1", "find_tickets", '{"status": "open", "first": 2}')
    assert record.error is False
    assert json.loads(record.result) == {
        "rows": [{"id": 2, "title": "Slow search"}],
        "row_count": 1,
        "truncated": False,
    }


async def test_what_the_model_writes_is_data_never_sql(pg: PgDb) -> None:
    _tickets(pg)
    hostile = "open'; DROP TABLE tickets; --"
    answer = await _call(pg, _tool(), {"status": hostile, "first": 1})
    assert json.loads(answer)["rows"] == []
    assert pg.sql("SELECT count(*) FROM tickets") == [(3,)]
    wrong_type = await _call(pg, _tool(), {"status": "open", "first": "1 OR 1=1"})
    assert wrong_type.startswith("Error: 22P02")  # refused as a number, not run as SQL


async def test_the_tool_is_read_only_until_changes_are_allowed(pg: PgDb) -> None:
    _tickets(pg)
    change = _tool(
        query="DELETE FROM tickets WHERE id = $1::int RETURNING id", parameters="id: Which"
    )
    refused = await _call(pg, change, {"id": 1})
    assert refused.startswith("Error: 25006") and "Allow changes" in refused
    assert pg.sql("SELECT count(*) FROM tickets") == [(3,)]
    allowed = await _call(
        pg, {**change, "config": {**change["config"], "allow_write": True}}, {"id": 1}
    )
    assert json.loads(allowed)["rows"] == [{"id": 1}]
    assert pg.sql("SELECT count(*) FROM tickets") == [(2,)]


@pytest.mark.parametrize(("operator", "tool_switch"), [(True, False), (False, True)])
async def test_a_private_database_needs_the_switch_of_the_tool_and_the_operators(
    pg: PgDb, operator: bool, tool_switch: bool
) -> None:
    answer = await _call(
        pg,
        _tool(allow_private=tool_switch),
        {"status": "open", "first": 1},
        private=operator,
    )
    assert answer.startswith("Error:") and "private network address" in answer


async def test_a_missing_parameter_is_an_error_for_the_model(pg: PgDb) -> None:
    answer = await _call(pg, _tool(), {"status": "open"})
    assert answer == "Error: the parameter first is missing"


async def test_the_answer_is_cut_before_the_limit_and_stays_valid_json(pg: PgDb) -> None:
    wide = _tool(
        query="SELECT g, repeat('x', 500) AS wide FROM generate_series(1, 400) g",
        parameters="",
        max_rows=400,
    )
    answer = await _call(pg, wide, {})
    assert len(answer.encode()) <= TOOL_RESULT_LIMIT_BYTES
    parsed = json.loads(answer)  # not cut in the middle
    assert parsed["truncated"] is True and 0 < len(parsed["rows"]) < 400


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"query": "SELECT $2", "parameters": "a: first"}, r"uses \$2 but only 1 value"),
        ({"query": "SELECT 1", "parameters": "a: first"}, "Value 1 is not used"),
        ({"secret": ""}, "No secret with the connection URL is set"),
        ({"query": ""}, "The query is empty"),
    ],
)
async def test_a_tool_that_cannot_work_fails_the_node_naming_it(
    pg: PgDb, change: dict[str, Any], message: str
) -> None:
    with pytest.raises(ToolboxError, match=f"Tool Tickets: .*{message}"):
        await _call(pg, _tool(**change), {})


async def test_the_secret_of_the_tool_is_resolved_like_every_secret(pg: PgDb) -> None:
    from openartifact.agents.tools import secret_names

    assert secret_names([_tool()]) == ["TICKETS_DB"]
    assert secret_names([_tool(secret="")]) == []


@pytest.fixture
def database(pg: PgDb) -> PgDb:
    _tickets(pg)
    return pg


def test_an_agent_looks_a_ticket_up_and_the_history_shows_the_call_without_the_url(
    api: TestClient, llm: FakeLlm, database: PgDb
) -> None:
    make_provider(api, llm)
    put_secret(api, "TICKETS_DB", database.url)
    agent = make_agent(api)
    config = {
        "tool_name": "ticket",
        "description": "Look a ticket up by its number",
        "secret": "TICKETS_DB",
        "query": "SELECT title, status FROM tickets WHERE id = $1::int",
        "parameters": "id: The number of the ticket",
        "allow_private": True,
    }
    pipeline = tool_flow(api, agent, [("postgres_tool", "Tickets", config)])
    llm.script = [
        (200, tool_answer(("c1", "ticket", {"id": "2"}))),
        (200, completion("Ticket 2 is Slow search")),
    ]
    step, read = run_and_step(api, pipeline, "done")
    assert step["output"] == "Ticket 2 is Slow search"
    (call,) = read["detail"]["turns"][0]["tool_calls"]
    assert call["tool"] == "ticket" and call["error"] is False
    assert json.loads(call["result"])["rows"] == [{"title": "Slow search", "status": "open"}]
    assert llm.completions()[1]["json"]["messages"][-1]["content"] == call["result"]
    assert database.url not in json.dumps(read) and "pw" not in json.dumps(read["detail"])


def test_a_tool_node_is_frozen_with_its_secret_name_and_never_the_url(
    api: TestClient, llm: FakeLlm, database: PgDb
) -> None:
    from tests.test_agent_tools_run import snapshot_agent

    make_provider(api, llm)
    put_secret(api, "TICKETS_DB", database.url)
    agent = make_agent(api)
    config = {"secret": "TICKETS_DB", "query": "SELECT 1", "allow_private": True}
    pipeline = tool_flow(api, agent, [("postgres_tool", "Tickets", config)])
    task = _make_task(api)
    post(api, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(api, task, "done", timeout=30)
    frozen = snapshot_agent(api, task)
    assert [(t["kind"], t["config"]["secret"]) for t in frozen["tools"]] == [
        ("postgres_tool", "TICKETS_DB")
    ]
    assert database.url not in json.dumps(frozen)
