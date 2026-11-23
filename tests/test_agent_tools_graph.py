"""Tool nodes in the graph: attached to the Tools port of an Agent node, never walked (ADR-040)."""

from __future__ import annotations

import json
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


def test_the_downgrade_of_0035_leaves_no_edge_and_no_setting_the_old_code_refuses(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0034")
    command.upgrade(alembic_config(), "0035")
    stamp = "2026-11-23 00:00:00"
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO graphs (id, name, slug, kind) VALUES ('g', 'G', 'g', 'action')")
        nodes = (
            "INSERT INTO graph_nodes (id, graph_id, kind, name, config) VALUES (?, 'g', ?, ?, ?)"
        )
        conn.execute(
            nodes, ("a", "agent", "Ask", '{"agent_id": "x", "max_iterations": 3, "retries": 1}')
        )
        conn.execute(nodes, ("m", "mcp_tool", "GitHub", "{}"))
        conn.execute(nodes, ("o", "output", "Output", "{}"))
        edges = "INSERT INTO graph_edges (id, graph_id, source_id, source_port, target_id, target_port) VALUES (?, 'g', ?, ?, ?, ?)"
        conn.execute(edges, ("e1", "m", "tool", "a", "tools"))
        conn.execute(edges, ("e2", "a", "pass", "o", "pass"))
        conn.execute(
            "INSERT INTO agents (id, name, draft, created_at, updated_at) VALUES ('x', 'T', ?, ?, ?)",
            ('{"user_prompt": "Hi", "max_iterations": 10}', stamp, stamp),
        )
        conn.execute(
            "INSERT INTO agent_versions (id, agent_id, number, config, published_via, published_at) VALUES ('v', 'x', 1, ?, 'user', ?)",
            ('{"user_prompt": "Hi", "max_iterations": 10}', stamp),
        )
    command.downgrade(alembic_config(), "0034")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id FROM graph_edges").fetchall() == [
            ("e2",)
        ]  # the tool's edge went with it
        (config,) = conn.execute("SELECT config FROM graph_nodes WHERE id = 'a'").fetchone()
        assert json.loads(config) == {"agent_id": "x", "retries": 1}
        assert json.loads(conn.execute("SELECT draft FROM agents").fetchone()[0]) == {
            "user_prompt": "Hi"
        }
        assert json.loads(conn.execute("SELECT config FROM agent_versions").fetchone()[0]) == {
            "user_prompt": "Hi"
        }
    command.upgrade(alembic_config(), "head")


# ── settings ─────────────────────────────────────────────────────────


def _keys(client: TestClient, kind: str) -> dict[str, dict[str, Any]]:
    described = {t["kind"]: t for t in client.get("/api/node-types").json()}[kind]
    return {s["key"]: s for s in described["settings"]}


def test_every_tool_has_a_name_and_a_description_for_the_model(client: TestClient) -> None:
    for kind in TOOL_KINDS:
        settings = _keys(client, kind)
        assert list(settings)[:2] == ["tool_name", "description"], kind
    mcp = _keys(client, "mcp_tool")
    assert {"url", "secret", "allow_private", "tools_mode", "tool_names", "timeout_seconds"} <= set(
        mcp
    )
    assert (
        mcp["tools_mode"]["options"] == ["all", "selected", "all_except"]
        and mcp["tools_mode"]["default"] == "all"
    )
    assert (
        mcp["timeout_seconds"]["minimum"],
        mcp["timeout_seconds"]["maximum"],
        mcp["timeout_seconds"]["default"],
    ) == (1, 300, 60)
    http = _keys(client, "http_tool")
    assert {
        "method",
        "url",
        "headers",
        "body",
        "parameters",
        "timeout_seconds",
        "success_status",
        "allow_private",
    } <= set(http)
    code = _keys(client, "code_tool")
    assert {"language", "code", "secrets", "parameters", "timeout_seconds"} <= set(code)


@pytest.mark.parametrize(
    ("kind", "change", "message"),
    [
        ("mcp_tool", {"tool_name": "has space"}, "letters, digits, _ and -"),
        ("mcp_tool", {"tool_name": "x" * 65}, "too long"),
        ("mcp_tool", {"url": "ftp://x"}, "http or https"),
        ("mcp_tool", {"url": "https://user:pw@x.example/mcp"}, "user name or password"),
        ("mcp_tool", {"secret": "lower"}, "capitals, digits and underscores"),
        ("mcp_tool", {"tool_names": "ok\nbad name"}, "Line 2"),
        ("mcp_tool", {"tools_mode": "some"}, "must be one of"),
        ("http_tool", {"parameters": "city"}, "Line 1 is not 'name: description'"),
        ("http_tool", {"parameters": "City: x"}, "Line 1"),
        ("http_tool", {"parameters": "a: one\na: two"}, "Parameter 'a' is declared twice"),
        (
            "code_tool",
            {"parameters": "q: query\n" + "\n".join(f"p{n}: x" for n in range(30))},
            "At most 30 parameters",
        ),
    ],
)
def test_wrong_tool_settings_are_refused(
    client: TestClient, kind: str, change: dict[str, Any], message: str
) -> None:
    action = post(client, "/api/actions", name=f"T {kind}")
    made = node(client, action, kind)
    refused = client.patch(f"{graph_url(action)}/nodes/{made['id']}", json={"config": change})
    assert refused.status_code == 422, refused.text
    assert message in refused.json()["detail"]


def test_good_tool_settings_are_saved(client: TestClient) -> None:
    action = post(client, "/api/actions", name="Good")
    made = node(
        client,
        action,
        "mcp_tool",
        config={
            "tool_name": "github",
            "description": "Read issues",
            "url": "https://api.githubcopilot.com/mcp/",
            "secret": "GITHUB_TOKEN",
            "tools_mode": "selected",
            "tool_names": "get_issue\nlist_issues",
        },
    )
    assert made["config"]["tool_names"] == "get_issue\nlist_issues"
    http = node(
        client,
        action,
        "http_tool",
        config={
            "parameters": "city: The city to look up\nunits: metric or imperial",
            "url": "https://wttr.in/{city}",
        },
    )
    assert http["config"]["parameters"].startswith("city:")
