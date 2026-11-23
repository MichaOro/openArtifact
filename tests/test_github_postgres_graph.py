"""The GitHub node, the Postgres node and the Postgres Tool in the graph (ADR-041): kinds, ports, settings, migration."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import openartifact
from alembic import command
from tests.helpers import alembic_config, graph_url, kind_of, node, post

NEW_KINDS = ("github", "postgres", "postgres_tool")


def _described(client: TestClient, kind: str) -> dict[str, Any]:
    described: dict[str, Any] = {t["kind"]: t for t in client.get("/api/node-types").json()}[kind]
    return described


def _keys(client: TestClient, kind: str) -> dict[str, dict[str, Any]]:
    return {s["key"]: s for s in _described(client, kind)["settings"]}


def test_github_and_postgres_are_flow_nodes_leaving_by_pass_or_fail(client: TestClient) -> None:
    for kind, label in (("github", "GitHub"), ("postgres", "Postgres")):
        entry = _described(client, kind)
        assert (entry["label"], entry["scopes"], entry["addable"], entry["chain"]) == (
            label,
            ["action"],
            True,
            True,
        )
        assert entry["tool"] is False
        assert [p["name"] for p in entry["inputs"]] == ["in"]
        assert [p["name"] for p in entry["outputs"]] == ["pass", "fail"]


def test_the_postgres_tool_is_a_tool_with_one_port_on_top(client: TestClient) -> None:
    entry = _described(client, "postgres_tool")
    assert (entry["label"], entry["scopes"], entry["addable"], entry["tool"]) == (
        "Postgres Tool",
        ["action"],
        True,
        True,
    )
    assert entry["inputs"] == []
    assert entry["outputs"] == [{"name": "tool", "label": "Tool", "side": "top"}]
    action = post(client, "/api/actions", name="With a database")
    agent = node(client, action, "agent", name="Ask")
    database = node(client, action, "postgres_tool", name="Tickets")
    attached = client.post(
        f"{graph_url(action)}/edges",
        json={
            "source_id": database["id"],
            "source_port": "tool",
            "target_id": agent["id"],
            "target_port": "tools",
        },
    )
    assert attached.status_code == 201
    output = kind_of(client, action, "output")
    elsewhere = client.post(
        f"{graph_url(action)}/edges",
        json={
            "source_id": database["id"],
            "source_port": "tool",
            "target_id": output["id"],
            "target_port": "pass",
        },
    )
    assert elsewhere.status_code == 422
    assert elsewhere.json()["detail"] == "A tool attaches to the Tools port of an Agent node"


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_the_new_kinds_exist_only_in_action_definitions(client: TestClient, kind: str) -> None:
    pipeline = post(client, "/api/pipelines", name="P")
    refused = client.post(f"{graph_url(pipeline)}/nodes", json={"kind": kind})
    assert refused.status_code == 422
    assert refused.json()["detail"] == f"A pipeline cannot contain a {kind}"


# ── settings ─────────────────────────────────────────────────────────


def test_the_github_node_offers_read_operations_and_one_write_behind_a_switch(
    client: TestClient,
) -> None:
    settings = _keys(client, "github")
    assert settings["operation"]["options"] == [
        "Get repository",
        "List issues",
        "Get issue",
        "List pull requests",
        "Get pull request",
        "Get pull request diff",
        "List pull request files",
        "Get file",
        "List comments",
        "Create comment",
    ]
    assert (settings["allow_comments"]["type"], settings["allow_comments"]["default"]) == (
        "switch",
        False,
    )
    assert (
        settings["limit"]["minimum"],
        settings["limit"]["maximum"],
        settings["limit"]["default"],
    ) == (1, 100, 30)
    assert settings["api_url"]["default"] == "https://api.github.com"
    assert settings["state"]["options"] == ["open", "closed", "all"]
    for key in ("repository", "number", "path", "ref", "comment"):
        assert settings[key]["references"] == "context", key  # earlier results may feed them
    assert {"secret", "timeout_seconds", "on_failure"} <= set(settings)


def test_the_postgres_node_is_read_only_and_bounded_by_default(client: TestClient) -> None:
    settings = _keys(client, "postgres")
    assert settings["allow_write"]["default"] is False
    assert settings["allow_private"]["default"] is False
    assert "OPENARTIFACT_HTTP_ALLOW_PRIVATE_NETWORKS" in settings["allow_private"]["help"]
    assert (
        settings["max_rows"]["minimum"],
        settings["max_rows"]["maximum"],
        settings["max_rows"]["default"],
    ) == (1, 1000, 100)
    assert settings["values"]["references"] == "context"  # earlier results, never a secret
    assert {"secret", "query", "timeout_seconds", "on_failure"} <= set(settings)


def test_the_postgres_tool_has_the_tool_settings_and_the_same_bounds(client: TestClient) -> None:
    settings = _keys(client, "postgres_tool")
    assert list(settings)[:2] == ["tool_name", "description"]
    assert {"secret", "query", "parameters", "allow_write", "allow_private", "max_rows"} <= set(
        settings
    )
    assert settings["allow_write"]["default"] is False
    assert "OPENARTIFACT_LLM_ALLOW_PRIVATE_NETWORKS" in settings["allow_private"]["help"]


@pytest.mark.parametrize(
    ("kind", "change", "message"),
    [
        ("github", {"operation": "Delete repository"}, "must be one of"),
        ("github", {"repository": "no-slash"}, "owner/name"),
        ("github", {"repository": "a/b/c"}, "owner/name"),
        ("github", {"repository": "own er/name"}, "owner/name"),
        ("github", {"number": "seven"}, "whole number"),
        ("github", {"number": "-3"}, "whole number"),
        ("github", {"secret": "lower"}, "capitals, digits and underscores"),
        ("github", {"api_url": "ftp://x"}, "http or https"),
        ("github", {"api_url": "https://u:p@x.example"}, "user name or password"),
        ("github", {"limit": 101}, "1 to 100"),
        ("github", {"path": "a/../b"}, "'..'"),
        ("postgres", {"secret": "lower"}, "capitals, digits and underscores"),
        ("postgres", {"query": "SELECT ${var.id}"}, "$1"),
        ("postgres", {"query": "SELECT 1", "max_rows": 1001}, "1 to 1000"),
        ("postgres", {"values": "${secret:DB_PASSWORD}"}, "${secret:NAME} cannot be used"),
        ("postgres", {"values": "\n".join("x" for _ in range(101))}, "At most 100 values"),
        ("postgres_tool", {"query": "SELECT ${var.id}"}, "$1"),
        ("postgres_tool", {"parameters": "Id: no capitals"}, "Line 1"),
        ("postgres_tool", {"tool_name": "has space"}, "letters, digits, _ and -"),
    ],
)
def test_wrong_settings_are_refused(
    client: TestClient, kind: str, change: dict[str, Any], message: str
) -> None:
    action = post(client, "/api/actions", name=f"Wrong {kind}")
    made = node(client, action, kind)
    refused = client.patch(f"{graph_url(action)}/nodes/{made['id']}", json={"config": change})
    assert refused.status_code == 422, refused.text
    assert message in refused.json()["detail"]


def test_good_settings_are_saved_and_references_pass_the_checks(client: TestClient) -> None:
    action = post(client, "/api/actions", name="Good")
    github = node(
        client,
        action,
        "github",
        config={
            "operation": "Create comment",
            "repository": "${node.Trigger.data.repo}",
            "number": "${var.issue}",
            "comment": "Seen by ${var.who}",
            "secret": "GITHUB_TOKEN",
            "allow_comments": True,
            "api_url": "https://github.example.com/api/v3",
        },
    )
    assert github["config"]["repository"] == "${node.Trigger.data.repo}"
    plain = node(
        client, action, "github", config={"repository": "MichaOro/openArtifact", "number": "7"}
    )
    assert plain["config"]["number"] == "7"
    postgres = node(
        client,
        action,
        "postgres",
        config={
            "secret": "TICKETS_DB",
            "query": "SELECT id, title FROM tickets WHERE status = $1 AND note LIKE '%$2%'",
            "values": "open\n${var.term}",
        },
    )
    assert postgres["config"]["values"] == "open\n${var.term}"
    tool = node(
        client,
        action,
        "postgres_tool",
        config={
            "secret": "TICKETS_DB",
            "query": "SELECT title FROM tickets WHERE id = $1",
            "parameters": "id: The ticket's number",
        },
    )
    assert tool["config"]["parameters"] == "id: The ticket's number"


# ── migration ────────────────────────────────────────────────────────


def test_migration_0036_allows_the_new_kinds_and_the_downgrade_removes_them_with_their_edges(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0035")
    insert = "INSERT INTO graph_nodes (id, graph_id, kind, name) VALUES (?, 'g', ?, ?)"
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO graphs (id, name, slug, kind) VALUES ('g', 'G', 'g', 'action')")
        with pytest.raises(
            sqlite3.IntegrityError, match=r"CHECK constraint failed: ck_graph_nodes_kind"
        ):
            conn.execute(insert, ("n", "github", "N"))
    command.upgrade(alembic_config(), "0036")
    edges = (
        "INSERT INTO graph_edges (id, graph_id, source_id, source_port, target_id, target_port) "
        "VALUES (?, 'g', ?, ?, ?, ?)"
    )
    with sqlite3.connect(db) as conn:
        for node_id, kind in (
            ("gh", "github"),
            ("pg", "postgres"),
            ("pt", "postgres_tool"),
            ("a", "agent"),
            ("o", "output"),
        ):
            conn.execute(insert, (node_id, kind, kind))
        conn.execute(edges, ("e1", "pt", "tool", "a", "tools"))
        conn.execute(edges, ("e2", "gh", "pass", "pg", "in"))
        conn.execute(edges, ("e3", "a", "pass", "o", "pass"))
    command.downgrade(alembic_config(), "0035")
    with sqlite3.connect(db) as conn:
        assert sorted(conn.execute("SELECT id FROM graph_nodes").fetchall()) == [("a",), ("o",)]
        assert conn.execute("SELECT id FROM graph_edges").fetchall() == [("e3",)]
    command.upgrade(alembic_config(), "head")


# ── the editor ───────────────────────────────────────────────────────


def test_every_icon_a_node_card_asks_for_is_drawn_by_the_icon_template() -> None:
    """A card whose icon the template does not know is drawn without one: no error, just a hole."""
    root = Path(openartifact.__file__).parent
    source = (root / "static/js/editor/node-types.js").read_text()
    asked = set(re.findall(r'static icon = "([a-z-]+)"', source))
    template = (root / "templates/components/icons.html").read_text()
    names_line = next(
        line for line in template.splitlines() if line.startswith("{% set icon_names")
    )
    assert {"github", "database"} <= asked
    for name in sorted(asked):
        assert f'"{name}"' in names_line, name
        assert f'name == "{name}"' in template or name == "board", name
