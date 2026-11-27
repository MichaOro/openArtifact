"""The value typed in the Dry run form for a Trigger input reaches the prompt of the agent node, and the node window does not warn about it
(ADR-089 addendum 1). The owner's case: an action with the input ``mield``, an agent node whose User prompt override is ``${input.mield}``."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.agent_support import FakeLlm, completion
from tests.e2e.test_agents import _agent, _provider, agents_url, api, llm, signed_in
from tests.helpers import connect, graph_url, kind_of, node

__all__ = [
    "agents_url",
    "api",
    "llm",
    "signed_in",
]  # the fixtures of the agent browser tests, used by name

TEXT = "let the party start it"


def _greeter(api: httpx.Client, agent: dict[str, Any]) -> dict[str, Any]:
    action = api.post("/api/actions", json={"name": "Greeter"}).json()
    trigger, output = kind_of(api, action, "trigger"), kind_of(api, action, "output")
    api.patch(
        f"{graph_url(action)}/nodes/{trigger['id']}",
        json={"config": {"inputs": [{"name": "mield", "type": "text", "required": True}]}},
    ).raise_for_status()
    for edge in api.get(graph_url(action)).json()["edges"]:
        api.delete(f"{graph_url(action)}/edges/{edge['id']}")
    ask = node(
        api,
        action,
        "agent",
        name="Ask",
        config={
            "agent_id": agent["id"],
            "inputs": "ticket = T-1",
            "user_prompt": "Ticket ${input.ticket}: ${input.mield}",
        },
    )
    connect(api, action, trigger, "out", ask, "in")
    connect(api, action, ask, "pass", output, "pass")
    return dict(action)


def test_the_typed_value_reaches_the_agent_and_its_window_shows_no_false_warning(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    agent = _agent(api)
    action = _greeter(api, agent)
    llm.script = [(200, completion("done"))]
    page = signed_in
    page.goto(f"{agents_url}/actions/{action['slug']}")
    # opening the node asks the server for the preview of its prompts (and their problems): wait for that answer, an empty list before it proves nothing
    with page.expect_response(
        lambda r: "/preview" in r.url and r.request.method == "POST"
    ) as preview:
        page.locator(".ge-node--agent").dblclick(position={"x": 30, "y": 5})
    assert preview.value.ok
    assert preview.value.json()["problems"] == [], (
        "${input.mield} is an input of the Trigger: no 'not a declared input'"
    )
    inspector = page.locator(".ge-inspector")
    expect(inspector).to_be_visible()
    expect(inspector.locator(".ag-problems")).to_have_count(0)
    page.keyboard.press("Escape")

    page.locator(".ge-node--trigger").dblclick(position={"x": 20, "y": 5})
    dialog = page.locator("#node-modal")
    dialog.get_by_role("tab", name="Dry run").click()
    panel = dialog.locator("[data-dry-run]")
    expect(panel).to_be_visible()
    panel.get_by_label("mield").fill(TEXT)
    panel.get_by_role("button", name="Start dry run").click()
    row = panel.locator(".ge-dry__runs .history-row")
    expect(row).to_have_count(1)
    expect(row.locator(".history-chip")).to_have_text("Done")
    (request,) = llm.completions()
    sent = [m["content"] for m in request["json"]["messages"] if m["role"] == "user"]
    assert sent == [f"Ticket T-1: {TEXT}"]
