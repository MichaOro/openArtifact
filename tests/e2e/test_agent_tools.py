"""Tools of an agent in the browser (ADR-040): attached below an Agent node in the editor, and the calls
the model made in the history of a step. The model is the local stand-in, the MCP server a local one."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.agent_support import FakeLlm, completion
from tests.e2e.helpers import drag, eventually, pick_node
from tests.e2e.test_agents import _agent, _provider, agents_url, api, llm, signed_in
from tests.helpers import build_pipeline, connect, graph_url, kind_of, node, wait_until
from tests.mcp_support import TOKEN as MCP_TOKEN
from tests.mcp_support import mcp_server

__all__ = ["agents_url", "api", "llm", "signed_in"]  # the fixtures of the agent tests, used by name


@pytest.fixture(scope="module")
def github() -> Iterator[str]:
    with mcp_server() as url:
        yield url


def _edges(api: httpx.Client, action: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    graph = api.get(graph_url(action)).json()
    kinds = {n["id"]: n["kind"] for n in graph["nodes"]}
    return sorted(
        (kinds[e["source_id"]], e["source_port"], kinds[e["target_id"]], e["target_port"])
        for e in graph["edges"]
    )


def test_a_tool_is_added_below_its_agent_and_another_is_attached_by_dragging(
    signed_in: Page, agents_url: str, api: httpx.Client
) -> None:
    action = api.post("/api/actions", json={"name": "With tools"}).json()
    page = signed_in
    page.goto(f"{agents_url}/actions/{action['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.click("[data-add-menu]")
    pick_node(page, "agent")
    agent_card = page.locator(".ge-node--agent")
    expect(agent_card).to_be_visible()

    page.click("[data-add-menu]")
    pick_node(page, "mcp_tool")  # the agent is selected: the tool hangs below it, attached
    tool_card = page.locator(".ge-node--mcp_tool")
    expect(tool_card.locator(".ge-node__kind")).to_have_text("no endpoint yet")
    eventually(lambda: ("mcp_tool", "tool", "agent", "tools") in _edges(api, action), True)
    expect(page.locator(".ge-edge--attachment")).to_have_count(1)
    agent_box, tool_box = agent_card.bounding_box(), tool_card.bounding_box()
    assert (
        agent_box and tool_box and tool_box["y"] > agent_box["y"] + agent_box["height"]
    )  # below it

    tool_card.dblclick(position={"x": 30, "y": 5})
    inspector = page.locator(".ge-inspector")
    inspector.get_by_label("Endpoint").fill("https://api.githubcopilot.com/mcp/")
    inspector.get_by_label("Endpoint").press("Enter")
    expect(tool_card.locator(".ge-node__kind")).to_have_text("api.githubcopilot.com/mcp/")
    page.keyboard.press("Escape")

    # a tool added with nothing selected, then detached and attached again by dragging its port
    page.locator(".ge-viewport").click(position={"x": 5, "y": 5})
    page.click("[data-add-menu]")
    pick_node(page, "http_tool")
    eventually(lambda: ("http_tool", "tool", "agent", "tools") in _edges(api, action), True)
    graph = api.get(graph_url(action)).json()
    http_id = next(n["id"] for n in graph["nodes"] if n["kind"] == "http_tool")
    edge = next(e for e in graph["edges"] if e["source_id"] == http_id)
    api.delete(f"{graph_url(action)}/edges/{edge['id']}").raise_for_status()
    page.reload()
    http_port = page.locator(f'.ge-port[data-node-id="{http_id}"][data-port="tool"]')
    tools_port = page.locator('.ge-node--agent .ge-port[data-port="tools"]')
    expect(page.locator(".ge-edge--attachment")).to_have_count(1)
    drag(page, http_port, tools_port)
    eventually(lambda: ("http_tool", "tool", "agent", "tools") in _edges(api, action), True)
    expect(page.locator(".ge-edge--attachment")).to_have_count(2)
    # a tool's port does not feed the flow: the Output is no target while dragging it
    output_port = page.locator('.ge-node--output .ge-port[data-port="pass"]')
    drag(page, http_port, output_port)
    expect(page.locator(".ge-edge--attachment")).to_have_count(2)
    assert ("http_tool", "tool", "output", "pass") not in _edges(api, action)


def test_the_tool_calls_of_an_agent_step_are_shown(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm, github: str
) -> None:
    _provider(api, llm)
    api.put("/api/secrets/GITHUB_TOKEN", json={"value": MCP_TOKEN}).raise_for_status()
    agent = _agent(api)
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    trigger, output = kind_of(api, action, "trigger"), kind_of(api, action, "output")
    for edge in api.get(graph_url(action)).json()["edges"]:
        api.delete(f"{graph_url(action)}/edges/{edge['id']}")
    ask = node(
        api, action, "agent", name="Ask", config={"agent_id": agent["id"], "inputs": "ticket = T-7"}
    )
    tool_config = {
        "url": github,
        "secret": "GITHUB_TOKEN",
        "allow_private": True,
        "tools_mode": "selected",
        "tool_names": "get_issue",
    }
    github_tool = node(api, action, "mcp_tool", name="GitHub", config=tool_config)
    connect(api, action, trigger, "out", ask, "in")
    connect(api, action, ask, "pass", output, "pass")
    connect(api, action, github_tool, "tool", ask, "tools")
    pipeline = build_pipeline(api, stages=1)
    api.patch(
        f"{graph_url(pipeline)}/nodes/{pipeline['stages'][0][1]['id']}",
        json={"definition_id": action["id"]},
    )
    call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "get_issue", "arguments": json.dumps({"number": 7})},
    }
    asks = {
        "id": "x",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": None, "tool_calls": [call]},
                "finish_reason": "tool_calls",
            }
        ],
    }
    llm.script = [(200, asks), (200, completion("Issue 7 is about the login."))]
    task = api.post("/api/tasks", json={"title": "Item", "status": "backlog"}).json()
    api.post(
        f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]}
    ).raise_for_status()
    run = wait_until(
        lambda: next(r for r in api.get("/api/runs").json() if r["task_id"] == task["id"]),
        lambda r: r["status"] in ("done", "failed"),
        timeout=30,
    )
    assert run["status"] == "done", run
    page = signed_in
    page.goto(f"{agents_url}/artifacts/{task['number']}/executions/{run['execution_id']}")
    page.get_by_label("Open Answer").click()
    page.locator("[data-node-id]", has_text="Ask").locator(".ef-path__main").click()
    step = page.locator("[data-panel-detail] .history-step")
    step.locator("[data-step-agent] > summary").click()
    calls = step.locator(".ag-detail").get_by_label("Tool calls").locator("tbody tr")
    expect(calls).to_have_count(1)
    expect(calls.nth(0)).to_contain_text("get_issue")
    expect(calls.nth(0)).to_contain_text('{"number": 7}')
    expect(calls.nth(0)).to_contain_text("Issue #7: Login is broken")
    expect(step.locator(".ag-detail")).to_contain_text("Max iterations 10")
    expect(page.locator("body")).not_to_contain_text(MCP_TOKEN)
