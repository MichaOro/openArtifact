"""Agents at the edges: the MCP tools, the pages, migration 0033 and the visible cut of a long output."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Generator, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.engine import runner
from openartifact.engine.results import NodeResult
from tests.agent_support import (
    API_KEY,
    HEADERS,
    SECURE,
    FakeLlm,
    fake_llm,
    make_agent,
    make_provider,
)
from tests.helpers import alembic_config

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


def _mcp(api: TestClient, method: str, params: dict[str, Any] | None = None) -> Any:
    response = api.post(
        "/mcp",
        headers=MCP_HEADERS,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _tool(api: TestClient, name: str, **arguments: Any) -> tuple[bool, Any]:
    result = _mcp(api, "tools/call", {"name": name, "arguments": arguments})["result"]
    text = result["content"][0]["text"] if result["content"] else "[]"
    if result.get("isError"):
        return True, text
    return False, result.get("structuredContent", {}).get("result", json.loads(text))


# ── MCP: read only ───────────────────────────────────────────────────


def test_mcp_reads_agents_and_providers_and_writes_nothing(api: TestClient, llm: FakeLlm) -> None:
    provider = make_provider(api, llm)
    agent = make_agent(api)
    names = {t["name"] for t in _mcp(api, "tools/list")["result"]["tools"]}
    assert {"list_agents", "get_agent", "list_providers"} <= names
    writing = ("create", "update", "delete", "publish", "save", "put", "set", "test", "refresh")
    assert not [n for n in names if ("agent" in n or "provider" in n) and n.startswith(writing)]

    error, agents = _tool(api, "list_agents")
    assert not error and [(a["name"], a["published_number"], a["active"]) for a in agents] == [
        ("Triage", 1, True)
    ]
    error, detail = _tool(api, "get_agent", agent="Triage")
    assert not error and detail["id"] == agent["id"]
    assert detail["published"]["user_prompt"].startswith("Analyse:")
    assert [v["number"] for v in detail["versions"]] == [1]
    error, providers = _tool(api, "list_providers")
    assert not error and providers[0]["id"] == provider["id"]
    assert providers[0]["secret_name"] == "LLM_KEY"
    assert {m["model_id"] for m in providers[0]["models"]} == {"small", "large"}
    assert API_KEY not in json.dumps([agents, detail, providers])
    error, text = _tool(api, "get_agent", agent="nope")
    assert error and "Agent not found" in text


# ── pages ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "script", "current"),
    [
        ("/agents", "/static/js/agents/list-page.js", "Agents"),
        ("/agents/some-id", "/static/js/agents/editor-page.js", "Agents"),
        ("/settings/providers", "/static/js/agents/providers-page.js", "LLM providers"),
    ],
)
def test_the_pages_load_their_script_and_mark_their_place(
    client: TestClient, path: str, script: str, current: str
) -> None:
    html = client.get(path).text
    assert script in html and "/static/css/agents.css" in html
    marked = html.split('aria-current="page"')[1].split("</a>")[0]
    assert current in marked
    assert 'href="/settings/providers"' in html
    # Agents is a sub-entry of Pipeline: shown with Pipeline's other entries on the pages inside it only
    assert ('href="/agents"' in html) == path.startswith("/agents")


def test_the_agent_page_carries_the_reference_and_the_pages_are_not_in_the_api_document(
    client: TestClient,
) -> None:
    assert 'data-agent-ref="some-id"' in client.get("/agents/some-id").text
    paths = client.get("/openapi.json").json()["paths"]
    assert "/agents" not in paths and "/settings/providers" not in paths
    described = {t["kind"]: t for t in client.get("/api/node-types").json()}
    settings = {s["key"]: s for s in described["agent"]["settings"]}
    assert settings["temperature"]["type"] == "number"
    assert (settings["temperature"]["minimum"], settings["temperature"]["maximum"]) == (0, 2)
    assert (settings["max_tokens"]["maximum"], settings["retries"]["maximum"]) == (8192, 4)
    assert (
        settings["inputs"]["references"] == "context" and settings["max_tokens"]["default"] is None
    )


# ── migration ────────────────────────────────────────────────────────


def test_migration_0033_adds_agents_and_the_downgrade_removes_them(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0032")
    insert = "INSERT INTO graph_nodes (id, graph_id, kind, name) VALUES (?, 'g', ?, ?)"
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO graphs (id, name, slug, kind) VALUES ('g', 'G', 'g', 'action')")
        with pytest.raises(sqlite3.IntegrityError, match=r"ck_graph_nodes_kind"):
            conn.execute(insert, ("a", "agent", "Ask"))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not tables & {"agents", "agent_versions", "llm_providers", "llm_models"}
    command.upgrade(alembic_config(), "0033")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(insert, ("a", "agent", "Ask"))
        conn.execute(insert, ("c", "code", "Code"))
        now = "2026-01-01 00:00:00"
        conn.execute(
            "INSERT INTO agents (id, name, created_at, updated_at) VALUES ('x', 'Triage', ?, ?)",
            (now, now),
        )
        with pytest.raises(
            sqlite3.IntegrityError, match=r"UNIQUE constraint failed: agents\.name"
        ):  # names are unique ignoring case
            conn.execute(
                "INSERT INTO agents (id, name, created_at, updated_at) VALUES ('y', 'TRIAGE', ?, ?)",
                (now, now),
            )
        conn.execute(
            "INSERT INTO agent_versions (id, agent_id, number, config, published_via, published_at) VALUES ('v', 'x', 1, '{}', 'user', ?)",
            (now,),
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match=r"UNIQUE constraint failed: agent_versions\.agent_id, agent_versions\.number",
        ):  # a number is used once per agent
            conn.execute(
                "INSERT INTO agent_versions (id, agent_id, number, config, published_via, published_at) VALUES ('w', 'x', 1, '{}', 'user', ?)",
                (now,),
            )
        conn.execute(
            "INSERT INTO llm_providers (id, kind, name, created_at, updated_at) VALUES ('p', 'openrouter', 'OpenRouter', ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO llm_models (id, provider_id, model_id, source, created_at, updated_at) VALUES ('m', 'p', 'small', 'fetched', ?, ?)",
            (now, now),
        )
        assert conn.execute("SELECT active, draft, version_seq FROM agents").fetchone() == (
            1,
            "{}",
            0,
        )
        assert conn.execute("SELECT enabled, available FROM llm_models").fetchone() == (0, 1)
        assert "detail" in {r[1] for r in conn.execute("PRAGMA table_info(run_node_results)")}
        conn.execute(
            "DELETE FROM agents"
        )  # the versions go with their agent, the models with their provider
        conn.execute("DELETE FROM llm_providers")
        assert conn.execute("SELECT count(*) FROM agent_versions").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM llm_models").fetchone() == (0,)
    command.downgrade(alembic_config(), "0032")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id FROM graph_nodes").fetchall() == [("c",)]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not tables & {"agents", "agent_versions", "llm_providers", "llm_models"}
        assert "detail" not in {r[1] for r in conn.execute("PRAGMA table_info(run_node_results)")}
    command.upgrade(alembic_config(), "head")


# ── the cut of a long output ─────────────────────────────────────────


def test_a_cut_output_keeps_its_reason_and_data_and_says_that_it_was_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "RESULT_OUTPUT_LIMIT_CHARS", 2048)
    result = NodeResult(
        "fail", output="z" * 5000, reason="HTTP 500 is not accepted", data={"status": 500}
    )
    cut = runner._cut(result)
    assert len(cut.output) == 2048 and cut.output.endswith("\n[output truncated]")
    assert cut.data == {"status": 500, "output_truncated": True}
    assert cut.reason == "HTTP 500 is not accepted; the output was cut at 2 Ki characters"
    assert result.data == {"status": 500}  # the original is not changed
    bare = runner._cut(NodeResult("pass", output="z" * 5000))
    assert (
        bare.data == {"output_truncated": True}
        and bare.reason == "Note: the output was cut at 2 Ki characters"
    )
