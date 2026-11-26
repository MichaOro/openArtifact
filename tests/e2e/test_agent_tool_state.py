"""The tool nodes of an agent in the flow of an execution: one the agent asked and that did its work is green, one with a failed call is
red, one that was never asked stays dim and dashed; while a call is in progress the node works (the pulse) and bubbles run along its
line from the agent. The model is the local stand-in, the MCP server a local one."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.agent_support import FakeLlm, completion
from tests.e2e.test_agents import _agent, _provider, agents_url, api, llm, signed_in
from tests.helpers import build_pipeline, connect, graph_url, kind_of, node, wait_until
from tests.mcp_support import TOKEN as MCP_TOKEN
from tests.mcp_support import mcp_server

__all__ = ["agents_url", "api", "llm", "signed_in"]  # the fixtures of the agent tests, used by name


@pytest.fixture(scope="module")
def github() -> Iterator[str]:
    with mcp_server() as url:
        yield url


def _asks(*calls: tuple[str, str, dict[str, Any]]) -> dict[str, Any]:
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": i, "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
            for i, n, a in calls
        ],
    }
    return {"id": "x", "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls"}]}


def _flow(
    api: httpx.Client, llm: FakeLlm, tools: list[tuple[str, str, dict[str, Any]]]
) -> dict[str, Any]:
    """A pipeline whose action is trigger -> Ask (agent) -> output with ``tools`` attached to Ask; returns the pipeline and the nodes."""
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
    connect(api, action, trigger, "out", ask, "in")
    connect(api, action, ask, "pass", output, "pass")
    for i, (kind, name, config) in enumerate(tools):
        made = node(api, action, kind, name=name, config=config, x=100 + 230 * i, y=320)
        connect(api, action, made, "tool", ask, "tools")
    pipeline = build_pipeline(api, stages=1)
    api.patch(
        f"{graph_url(pipeline)}/nodes/{pipeline['stages'][0][1]['id']}",
        json={"definition_id": action["id"]},
    )
    return pipeline


def _mcp(url: str, names: str) -> dict[str, Any]:
    return {
        "url": url,
        "secret": "GITHUB_TOKEN",
        "allow_private": True,
        "tools_mode": "selected",
        "tool_names": names,
    }


def _start(api: httpx.Client, pipeline: dict[str, Any]) -> dict[str, Any]:
    task: dict[str, Any] = api.post(
        "/api/tasks", json={"title": "Item", "status": "backlog"}
    ).json()
    api.post(
        f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]}
    ).raise_for_status()
    return task


def _run(api: httpx.Client, task: dict[str, Any], states: tuple[str, ...]) -> dict[str, Any]:
    return wait_until(
        lambda: next(r for r in api.get("/api/runs").json() if r["task_id"] == task["id"]),
        lambda r: r["status"] in states,
        timeout=30,
    )


def _card(page: Page, kind: str) -> Any:
    return page.locator(f".ge-node--{kind}")


def test_a_tool_that_did_its_work_is_green_a_failed_one_red_and_one_never_asked_stays_dim(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm, github: str
) -> None:
    pipeline = _flow(
        api,
        llm,
        [
            ("mcp_tool", "Issues", _mcp(github, "get_issue")),
            ("mcp_tool", "Broken", _mcp(github, "explode")),
            ("http_tool", "Web", {"tool_name": "web", "url": "https://example.org/"}),
        ],
    )
    llm.script = [
        (
            200,
            _asks(
                ("c1", "get_issue", {"number": 7}),
                ("c2", "explode", {}),
                ("c3", "get_issue", {"number": 8}),
            ),
        ),
        (200, completion("Done.")),
    ]
    task = _start(api, pipeline)
    run = _run(api, task, ("done", "failed"))
    assert run["status"] == "done", run
    page = signed_in
    page.goto(f"{agents_url}/artifacts/{task['number']}/executions/{run['execution_id']}?visit=1")
    cards = {name: page.locator(".ge-node", has_text=name) for name in ("Issues", "Broken", "Web")}
    expect(cards["Issues"]).to_have_class(re.compile(r"ef-state-pass"))
    ok, broken, unused = cards["Issues"], cards["Broken"], cards["Web"]
    expect(ok).to_have_class(re.compile(r"ef-tool"))
    expect(ok).not_to_have_class(re.compile(r"is-dim"))
    expect(ok.locator(".ef-badge")).to_contain_text("\u00d72")  # two calls went through it
    expect(ok).to_have_attribute("title", "2 calls")
    expect(broken).to_have_class(re.compile(r"ef-state-fail"))
    expect(broken).to_have_attribute("title", "1 call, 1 failed")
    expect(unused).to_have_class(re.compile(r"is-dim"))
    expect(unused).not_to_have_class(re.compile(r"ef-tool"))
    # the line that ties a tool to its agent says the same: green, red, faint
    lines = page.locator(".ge-edge--attachment")
    expect(lines).to_have_count(3)
    expect(page.locator(".ge-edge--attachment.is-tool-pass")).to_have_count(1)
    expect(page.locator(".ge-edge--attachment.is-tool-fail")).to_have_count(1)
    expect(page.locator(".ge-edge--attachment.is-idle")).to_have_count(1)
    # the colours come from the state tokens, not from the old dim look
    border = ok.evaluate("el => getComputedStyle(el).borderTopColor")
    assert border != broken.evaluate("el => getComputedStyle(el).borderTopColor")
    assert ok.evaluate("el => getComputedStyle(el).opacity") == "1"
    assert unused.evaluate("el => getComputedStyle(el).opacity") != "1"


def test_while_a_call_is_in_progress_the_tool_works_with_bubbles_from_the_agent_and_turns_green_after(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    sleeper = {
        "tool_name": "sleeper",
        "description": "Waits a little",
        "language": "python",
        "code": "import time\ntime.sleep(4)\nprint('rested')",
    }
    pipeline = _flow(api, llm, [("code_tool", "Sleeper", sleeper)])
    # the model takes its time to ask, so the page is open (and listening) before the call starts
    llm.script = [(200, _asks(("c1", "sleeper", {})), {}, 5.0), (200, completion("Rested."))]
    task = _start(api, pipeline)
    run = _run(api, task, ("running", "done", "failed"))
    page = signed_in
    page.goto(f"{agents_url}/artifacts/{task['number']}/executions/{run['execution_id']}?visit=1")
    tool = _card(page, "code_tool")
    expect(tool).to_have_class(re.compile(r"ef-state-running"), timeout=15000)
    expect(tool).to_have_class(re.compile(r"ef-tool"))
    expect(page.locator(".ge-edge--attachment.is-tool-running .ef-bubbles")).to_have_count(1)
    expect(
        page.locator(".ge-edge--attachment.is-tool-running animateMotion").first
    ).to_have_attribute("keyPoints", "1;0")
    _run(api, task, ("done",))
    expect(tool).to_have_class(re.compile(r"ef-state-pass"), timeout=15000)
    expect(page.locator(".ge-edge--attachment.is-tool-pass")).to_have_count(1)
    expect(page.locator(".ge-edge--attachment .ef-bubbles")).to_have_count(
        0
    )  # nothing moves any more
