"""The OpenArtifact MCP Tool node (ADR-079): the board tools for an agent inside a run, in this process, held to reading unless
*Allow writes* is on."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Generator, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.agents.board_tool_names import BOARD_TOOLS, READ_TOOLS, WRITE_TOOLS
from openartifact.app import _create_app
from openartifact.config import Settings
from tests.agent_support import (
    HEADERS,
    SECURE,
    FakeLlm,
    completion,
    fake_llm,
    make_agent,
    make_provider,
)
from tests.helpers import alembic_config, graph_url, make_task, post, wait_for_run
from tests.test_agent_tools_run import snapshot_agent, tool_answer, tool_flow

MCP_HEADERS = {**HEADERS, "Accept": "application/json, text/event-stream"}


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    with TestClient(_create_app(migrated_settings.model_copy(update=SECURE))) as client:
        client.headers.update(HEADERS)
        yield client


@pytest.fixture
def llm() -> Iterator[FakeLlm]:
    with fake_llm() as server:
        yield server


def _flow(client: TestClient, llm: FakeLlm, **config: Any) -> dict[str, Any]:
    make_provider(client, llm)
    agent = make_agent(client)
    return tool_flow(client, agent, [("openartifact_tool", "Board", config)])


def _run(
    client: TestClient, pipeline: dict[str, Any], task: dict[str, Any], status: str = "done"
) -> tuple[dict[str, Any], dict[str, Any]]:
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = wait_for_run(client, task, status, timeout=30)
    step = next(r for r in run["node_results"] if r["kind"] == "agent")
    url = f"/api/tasks/{task['id']}/executions/{run['execution_id']}/steps/{step['id']}"
    return step, client.get(url).json()


def _offered(llm: FakeLlm) -> list[str]:
    return [t["function"]["name"] for t in llm.completions()[0]["json"]["tools"]]


def _calls(read: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for turn in read["detail"]["turns"] for c in turn["tool_calls"]]


def test_the_node_reads_only_until_writes_are_allowed(api: TestClient, llm: FakeLlm) -> None:
    pipeline = _flow(api, llm)
    llm.script = [(200, completion("done"))]
    step, read = _run(api, pipeline, make_task(api))
    assert sorted(_offered(llm)) == sorted(READ_TOOLS)
    assert not set(_offered(llm)) & set(WRITE_TOOLS)
    assert "Allow writes is off" in " ".join(read["detail"]["tool_notes"])
    assert step["outcome"] == "pass"


def test_allow_writes_offers_every_tool_of_the_board(api: TestClient, llm: FakeLlm) -> None:
    pipeline = _flow(api, llm, allow_write=True)
    llm.script = [(200, completion("done"))]
    _, read = _run(api, pipeline, make_task(api))
    assert sorted(_offered(llm)) == sorted(BOARD_TOOLS)
    assert "tool_notes" not in read["detail"]


def test_the_tools_to_include_narrow_the_set_and_a_held_back_tool_is_said(
    api: TestClient,
    llm: FakeLlm,
) -> None:
    pipeline = _flow(
        api, llm, tools_mode="selected", tool_names="list_lanes\nmove_artifacts\nget_artifacts"
    )
    llm.script = [(200, completion("done"))]
    _, read = _run(api, pipeline, make_task(api))
    assert sorted(_offered(llm)) == ["get_artifacts", "list_lanes"]
    assert "move_artifacts not offered (it changes something and Allow writes is off)" in " ".join(
        read["detail"]["tool_notes"]
    )


def test_all_except_leaves_the_named_tools_out(api: TestClient, llm: FakeLlm) -> None:
    pipeline = _flow(
        api,
        llm,
        allow_write=True,
        tools_mode="all_except",
        tool_names="stop_processing\nlist_pipelines",
    )
    llm.script = [(200, completion("done"))]
    _run(api, pipeline, make_task(api))
    assert set(_offered(llm)) == set(BOARD_TOOLS) - {"stop_processing", "list_pipelines"}


def test_a_name_that_is_no_tool_is_refused_when_the_node_is_saved(
    api: TestClient, llm: FakeLlm
) -> None:
    action = post(api, "/api/actions", name="Tidy")
    refused = api.post(
        f"{graph_url(action)}/nodes",
        json={
            "kind": "openartifact_tool",
            "config": {"tools_mode": "selected", "tool_names": "delete_artifact"},
        },
    )
    assert refused.status_code == 422
    assert "'delete_artifact' is not a tool. The tools: list_pipelines" in refused.text


def test_the_agent_reads_and_moves_cards_and_the_change_is_on_the_board(
    api: TestClient,
    llm: FakeLlm,
) -> None:
    for title in ("Old A", "Old B"):
        post(api, "/api/tasks", title=title, status="backlog")
    pipeline = _flow(api, llm, allow_write=True)
    llm.script = [
        (200, tool_answer(("c1", "list_artifacts", {"brief": True, "lane": "backlog"}))),
        (200, tool_answer(("c2", "move_artifacts", {"artifacts": ["1", "2"], "lane": "done"}))),
        (200, completion("moved two cards")),
    ]
    step, read = _run(api, pipeline, make_task(api, "Tidy up"))
    listed, moved = _calls(read)
    assert {c["title"] for c in json.loads(listed["result"])} >= {"Old A", "Old B"}
    assert (json.loads(moved["result"])["ok"], moved["error"]) == (2, False)
    assert [
        api.get(f"/api/tasks/{t['id']}").json()["status"]
        for t in api.get("/api/tasks").json()
        if t["title"] in ("Old A", "Old B")
    ] == ["done", "done"]
    assert step["output"] == "moved two cards"


def test_the_agent_cannot_move_the_card_its_own_run_is_on_and_is_told_why(
    api: TestClient,
    llm: FakeLlm,
) -> None:
    pipeline = _flow(api, llm, allow_write=True)
    task = make_task(api, "Itself")
    llm.script = [
        (
            200,
            tool_answer(
                ("c1", "update_artifact", {"artifact": str(task["number"]), "lane": "done"})
            ),
        ),
        (200, tool_answer(("c2", "archive_artifact", {"artifact": str(task["number"])}))),
        (200, completion("could not")),
    ]
    _, read = _run(api, pipeline, task)
    first, second = _calls(read)
    for call in (first, second):
        assert call["error"] is True
        assert call["result"].startswith("Error: ") and "being processed" in call["result"]
    assert api.get(f"/api/tasks/{task['id']}").json()["status"] == "backlog"


def test_a_call_of_the_node_answers_what_the_mcp_server_answers(
    api: TestClient, llm: FakeLlm
) -> None:
    for title in ("One", "Two"):
        post(api, "/api/tasks", title=title, status="backlog")
    pipeline = _flow(api, llm)
    llm.script = [
        (
            200,
            tool_answer(("c1", "list_lanes", {}), ("c2", "count_artifacts", {"lane": "backlog"})),
        ),
        (200, completion("done")),
    ]
    task = make_task(api, "Ask")
    _, read = _run(api, pipeline, task)

    def over_mcp(name: str, **arguments: Any) -> Any:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        result = api.post("/mcp", headers=MCP_HEADERS, json=body).json()["result"]
        data = result["structuredContent"]
        return data["result"] if list(data) == ["result"] else data

    lanes, count = _calls(read)
    # the run's own card counts as a card of the backlog while the call is made: the same board, asked two ways
    assert json.loads(lanes["result"]) == over_mcp("list_lanes")
    assert json.loads(count["result"]) == {
        **over_mcp("count_artifacts", lane="backlog"),
        "total": 3,
    }


def test_the_card_of_the_run_shows_the_node_as_the_tool_that_was_used(
    api: TestClient, llm: FakeLlm
) -> None:
    pipeline = _flow(api, llm)
    llm.script = [
        (200, tool_answer(("c1", "list_lanes", {}))),
        (200, completion("done")),
    ]
    task = make_task(api)
    _, read = _run(api, pipeline, task)
    (call,) = _calls(read)
    assert (call["tool"], call["node_name"], call["error"]) == ("list_lanes", "Board", False)
    frozen = snapshot_agent(api, task)
    assert [(t["kind"], t["name"]) for t in frozen["tools"]] == [("openartifact_tool", "Board")]
    assert (
        "secret" not in frozen["tools"][0]["config"] and "url" not in frozen["tools"][0]["config"]
    )


def test_migration_0063_allows_the_kind_and_the_downgrade_removes_its_nodes(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0062")
    insert = "INSERT INTO graph_nodes (id, graph_id, kind, name) VALUES (?, 'g', ?, ?)"
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO graphs (id, name, slug, kind) VALUES ('g', 'G', 'g', 'action')")
        with pytest.raises(
            sqlite3.IntegrityError, match=r"CHECK constraint failed: ck_graph_nodes_kind"
        ):
            conn.execute(insert, ("b", "openartifact_tool", "Board"))
    command.upgrade(alembic_config(), "0063")
    with sqlite3.connect(db) as conn:
        conn.execute(insert, ("b", "openartifact_tool", "Board"))
        conn.execute(insert, ("x", "code", "Code"))
    command.downgrade(alembic_config(), "0062")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id FROM graph_nodes").fetchall() == [("x",)]
    command.upgrade(alembic_config(), "head")
