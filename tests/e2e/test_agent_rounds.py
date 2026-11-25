"""The rounds of an agent while it runs, and a limit that ends in an answer (card #104). The model is the local stand-in; the tool is a
Code Tool that takes a few seconds, so the page is open (and listening) while the agent works."""

from __future__ import annotations

import re

import httpx
from playwright.sync_api import Page, expect

from tests.agent_support import FakeLlm, completion
from tests.e2e.test_agent_tool_state import _asks, _flow, _run, _start
from tests.e2e.test_agents import agents_url, api, llm, signed_in
from tests.helpers import graph_url

__all__ = ["agents_url", "api", "llm", "signed_in"]

SLEEPER = {
    "tool_name": "sleeper",
    "description": "Waits a little",
    "language": "python",
    "code": "import time\ntime.sleep(3)\nprint('rested')",
}


def _limit_iterations(api: httpx.Client, iterations: int) -> None:
    """The agent node of the flow may ask its model only ``iterations`` times with tools."""
    for graph in api.get("/api/actions").json():
        for found in api.get(graph_url(graph)).json()["nodes"]:
            if found["kind"] == "agent" and found["name"] == "Ask":
                api.patch(
                    f"{graph_url(graph)}/nodes/{found['id']}",
                    json={"config": {"max_iterations": iterations}},
                ).raise_for_status()


def test_the_rounds_of_a_running_agent_grow_in_its_panel_and_a_limit_ends_in_an_answer_with_a_note(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    pipeline = _flow(api, llm, [("code_tool", "Sleeper", SLEEPER)])
    _limit_iterations(api, 2)
    # round 1 asks for the tool after a pause (the page is open by then), round 2 asks again: that is the limit, so a final request
    # without tools writes the answer
    llm.script = [
        (200, _asks(("c1", "sleeper", {})), {}, 4.0),
        (200, _asks(("c2", "sleeper", {})), {}, 1.0),
        (200, completion("Partial answer from what was found.")),
    ]
    task = _start(api, pipeline)
    run = _run(api, task, ("running", "done", "failed"))
    page = signed_in
    page.goto(f"{agents_url}/artifacts/{task['number']}/executions/{run['execution_id']}?visit=1")
    page.locator(".ge-node--agent").first.click()
    live = page.locator("[data-live-rounds]")
    expect(live).to_be_visible(timeout=20000)
    expect(live.locator(".live-rounds__round").first).to_contain_text("Round 1")
    # the call shows while it works, with the tool's name and nothing of what it was asked or answered
    expect(live.locator(".live-rounds__call").first).to_contain_text("sleeper", timeout=20000)
    expect(live).not_to_contain_text("rested")
    # the rounds grow: a second round, then the final answer without tools
    expect(live.locator(".live-rounds__round")).not_to_have_count(1, timeout=20000)
    expect(live).to_contain_text("Final answer (the limit of 2 iterations)", timeout=30000)
    done = _run(api, task, ("done", "failed"))
    assert done["status"] == "done", done
    step = next(r for r in done["node_results"] if r["kind"] == "agent")
    assert step["outcome"] == "pass" and step["output"] == "Partial answer from what was found."
    assert re.search(r"the limit of 2 iterations was reached", step["reason"] or "")
    # once it is done the live rounds are gone: the step holds the whole story
    page.reload()
    page.locator(".ge-node--agent").first.click()
    expect(page.locator("[data-live-rounds]")).to_have_count(0)
