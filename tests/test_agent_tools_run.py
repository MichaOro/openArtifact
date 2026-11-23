"""Agents with tools in a run: what the snapshot keeps, the loop, the tools (ADR-040)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.agents.schemas import AgentConfig
from openartifact.app import _create_app
from openartifact.config import Settings
from tests.agent_support import HEADERS, SECURE, FakeLlm, fake_llm, make_agent, make_provider
from tests.helpers import (
    build_pipeline,
    connect,
    graph_url,
    kind_of,
    link,
    make_task,
    node,
    post,
    wait_for_run,
)


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    with TestClient(_create_app(migrated_settings.model_copy(update=SECURE))) as client:
        client.headers.update(HEADERS)
        yield client


@pytest.fixture
def llm() -> Iterator[FakeLlm]:
    with fake_llm() as server:
        yield server


def tool_flow(
    client: TestClient,
    agent: dict[str, Any],
    tools: list[tuple[str, str, dict[str, Any]]],
    **config: Any,
) -> dict[str, Any]:
    """A pipeline whose action is trigger -> agent node "Ask" -> Output, with ``tools`` attached to Ask."""
    action = post(client, "/api/actions", name="Answer")
    trigger, output = kind_of(client, action, "trigger"), kind_of(client, action, "output")
    for edge in client.get(graph_url(action)).json()["edges"]:
        client.delete(f"{graph_url(action)}/edges/{edge['id']}")
    client.patch(f"{graph_url(action)}/nodes/{output['id']}", json={"fail_enabled": True})
    ask = node(
        client,
        action,
        "agent",
        name="Ask",
        config={"agent_id": agent["id"], "inputs": "ticket = T-1", **config},
    )
    connect(client, action, trigger, "out", ask, "in")
    connect(client, action, ask, "pass", output, "pass")
    connect(client, action, ask, "fail", output, "fail")
    made: list[dict[str, Any]] = []
    for kind, name, tool_config in tools:
        tool = node(
            client, action, kind, name=name, config=tool_config, x=100 + 220 * len(made), y=300
        )
        connect(client, action, tool, "tool", ask, "tools")
        made.append(tool)
    pipeline = build_pipeline(client, stages=1)
    link(client, pipeline, pipeline["stages"][0][1], action)
    pipeline["action"], pipeline["ask"], pipeline["tools"] = action, ask, made
    return pipeline


def snapshot_agent(client: TestClient, task: dict[str, Any]) -> dict[str, Any]:
    settings = client.app.state.settings  # type: ignore[attr-defined]
    with sqlite3.connect(settings.data_dir / settings.database_filename) as db:
        (text,) = db.execute(
            "SELECT snapshot FROM pipeline_runs WHERE task_id = ?", (task["id"],)
        ).fetchone()
    (definition,) = json.loads(text)["definitions"].values()
    return next(n for n in definition["nodes"] if n["kind"] == "agent")["agent"]  # type: ignore[no-any-return]


# ── the snapshot ─────────────────────────────────────────────────────


def test_max_iterations_is_an_agent_setting_from_1_to_50() -> None:
    assert AgentConfig().max_iterations == 10
    assert AgentConfig(max_iterations=50).max_iterations == 50
    for wrong in (0, 51):
        with pytest.raises(ValueError):
            AgentConfig(max_iterations=wrong)


def test_the_snapshot_keeps_the_attached_tools_in_their_order(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    agent = make_agent(api)
    tools = [
        (
            "mcp_tool",
            "GitHub",
            {
                "url": "https://api.githubcopilot.com/mcp/",
                "secret": "GITHUB_TOKEN",
                "tools_mode": "selected",
                "tool_names": "get_issue",
            },
        ),
        (
            "http_tool",
            "Weather lookup",
            {
                "tool_name": "weather",
                "url": "https://wttr.in/{city}",
                "parameters": "city: The city",
            },
        ),
    ]
    pipeline = tool_flow(api, agent, tools, max_iterations=3)
    task = make_task(api)
    post(api, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    # the snapshot is written when the execution starts; how the run ends does not matter here
    frozen = snapshot_agent(api, task)
    assert [(t["name"], t["kind"], t["tool_name"]) for t in frozen["tools"]] == [
        ("GitHub", "mcp_tool", "GitHub"),
        ("Weather lookup", "http_tool", "weather"),
    ]
    assert frozen["tools"][0]["node_id"] == pipeline["tools"][0]["id"]
    assert frozen["tools"][0]["config"]["tool_names"] == "get_issue"
    assert frozen["tools"][1]["config"]["parameters"] == "city: The city"
    assert frozen["settings"]["max_iterations"] == 3 and frozen["overrides"]["max_iterations"] == 3


def test_an_agent_without_tools_has_an_empty_list(api: TestClient, llm: FakeLlm) -> None:
    make_provider(api, llm)
    agent = make_agent(api)
    pipeline = tool_flow(api, agent, [])
    task = make_task(api)
    post(api, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(api, task, "done")
    frozen = snapshot_agent(api, task)
    assert frozen["tools"] == [] and frozen["settings"]["max_iterations"] == 10
