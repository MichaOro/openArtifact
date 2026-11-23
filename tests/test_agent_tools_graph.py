"""Tool nodes in the graph: attached to the Tools port of an Agent node, never walked (ADR-040)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from tests.helpers import alembic_config, graph_url, kind_of, node, post

TOOL_KINDS = ("mcp_tool", "http_tool", "code_tool")


def _edge(
    client: TestClient,
    graph: dict[str, Any],
    source: dict[str, Any],
    sport: str,
    target: dict[str, Any],
    tport: str,
) -> Any:
    return client.post(
        f"{graph_url(graph)}/edges",
        json={
            "source_id": source["id"],
            "source_port": sport,
            "target_id": target["id"],
            "target_port": tport,
        },
    )


def test_tool_kinds_are_described_with_one_port_on_top(client: TestClient) -> None:
    described = {t["kind"]: t for t in client.get("/api/node-types").json()}
    labels = {
        "mcp_tool": "MCP Client Tool",
        "http_tool": "HTTP Request Tool",
        "code_tool": "Code Tool",
    }
    for kind in TOOL_KINDS:
        entry = described[kind]
        assert (entry["label"], entry["scopes"], entry["addable"], entry["tool"]) == (
            labels[kind],
            ["action"],
            True,
            True,
        )
        assert entry["inputs"] == []
        assert entry["outputs"] == [{"name": "tool", "label": "Tool", "side": "top"}]
    tools_port = [p for p in described["agent"]["inputs"] if p["name"] == "tools"]
    assert tools_port == [{"name": "tools", "label": "Tools", "side": "bottom"}]
    assert described["agent"]["tool"] is False
    assert {"name": "in", "label": "Input"} in described["agent"]["inputs"]  # usual side: unchanged


def test_a_tool_attaches_only_to_the_tools_port_of_an_agent(client: TestClient) -> None:
    action = post(client, "/api/actions", name="With tools")
    agent = node(client, action, "agent", name="Ask")
    first = node(client, action, "mcp_tool", name="GitHub")
    second = node(client, action, "http_tool", name="Weather")
    code = node(client, action, "code", name="Code")
    output = kind_of(client, action, "output")
    assert _edge(client, action, first, "tool", agent, "tools").status_code == 201
    assert (
        _edge(client, action, second, "tool", agent, "tools").status_code == 201
    )  # several tools per agent
    wrong_target = _edge(client, action, node(client, action, "code_tool"), "tool", output, "pass")
    assert wrong_target.status_code == 422
    assert wrong_target.json()["detail"] == "A tool attaches to the Tools port of an Agent node"
    flow_into_tools = _edge(client, action, code, "pass", agent, "tools")
    assert flow_into_tools.status_code == 422
    assert flow_into_tools.json()["detail"] == "Only a tool node attaches to Tools"
    # a tool serves one agent: attaching it elsewhere moves its one edge (as every output's edge moves)
    other = node(client, action, "agent", name="Other")
    assert _edge(client, action, first, "tool", other, "tools").status_code == 201
    edges = [
        e for e in client.get(graph_url(action)).json()["edges"] if e["source_id"] == first["id"]
    ]
    assert [(e["target_id"], e["target_port"]) for e in edges] == [(other["id"], "tools")]


@pytest.mark.parametrize("kind", TOOL_KINDS)
def test_tool_nodes_exist_only_in_action_definitions(client: TestClient, kind: str) -> None:
    pipeline = post(client, "/api/pipelines", name="P")
    refused = client.post(f"{graph_url(pipeline)}/nodes", json={"kind": kind})
    assert refused.status_code == 422
    assert refused.json()["detail"] == f"A pipeline cannot contain a {kind}"


def test_migration_0035_allows_the_tool_kinds_and_the_downgrade_removes_them(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0034")
    insert = "INSERT INTO graph_nodes (id, graph_id, kind, name) VALUES (?, 'g', ?, ?)"
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO graphs (id, name, slug, kind) VALUES ('g', 'G', 'g', 'action')")
        with pytest.raises(
            sqlite3.IntegrityError, match=r"CHECK constraint failed: ck_graph_nodes_kind"
        ):
            conn.execute(insert, ("m", "mcp_tool", "M"))
    command.upgrade(alembic_config(), "0035")
    with sqlite3.connect(db) as conn:
        for node_id, kind in (
            ("m", "mcp_tool"),
            ("h", "http_tool"),
            ("c", "code_tool"),
            ("x", "code"),
        ):
            conn.execute(insert, (node_id, kind, kind))
    command.downgrade(alembic_config(), "0034")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id FROM graph_nodes").fetchall() == [("x",)]
    command.upgrade(alembic_config(), "head")
