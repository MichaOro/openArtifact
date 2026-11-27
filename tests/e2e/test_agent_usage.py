"""Where an agent is used, on the agents page: the card says how many agent nodes use it, the panel has a Usage tab with a row per node
(the kind of place, the action as a link that opens it on the node, what is special), and says so when nothing uses the agent."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.helpers import graph_url, node, post


def _agent(api: httpx.Client, name: str) -> dict[str, Any]:
    response = api.post("/api/agents", json={"name": name, "draft": {"user_prompt": "Say hi."}})
    response.raise_for_status()
    return response.json()  # type: ignore[no-any-return]


def _open_usage(page: Page, base_url: str, name: str) -> Any:
    page.goto(f"{base_url}/agents")
    expect(page.locator(".mg-card").first).to_be_visible()
    page.locator(".mg-card", has_text=name).click()
    panel = page.locator(".mg__panel")
    panel.get_by_role("tab", name="Usage").click()
    return panel


def test_the_usage_tab_lists_the_agent_nodes_with_a_link_that_opens_the_action_on_the_node(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    agent = _agent(api, "Triage")
    action = post(api, "/api/actions", name="Planner")
    placed = node(api, action, "agent", name="Plan", config={"agent_id": agent["id"], "retries": 0})
    page.goto(f"{base_url}/agents")
    card = page.locator(".mg-card", has_text="Triage")
    expect(card).to_contain_text("1 node")
    panel = _open_usage(page, base_url, "Triage")
    rows = panel.locator(".mg-uses li")
    expect(rows).to_have_count(1)
    expect(rows.first.locator(".mg-uses__kind")).to_have_text("Action")
    link = rows.first.get_by_role("link", name="Plan · Planner")
    expect(link).to_have_attribute(
        "href", f"/actions/{action['slug']}?select={placed['id']}&agent={agent['id']}"
    )
    expect(rows.first).to_contain_text("Not published yet")  # its action has no published version
    expect(rows.first).to_contain_text("1 override")
    expect(panel).to_contain_text("always runs the agent's published version")
    link.click()
    expect(page).to_have_url(
        f"{base_url}/actions/{action['slug']}?select={placed['id']}&agent={agent['id']}"
    )


def test_a_node_in_the_published_version_has_no_draft_mark_and_one_only_the_published_version_has_says_so(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    agent = _agent(api, "Scribe")
    api.post(f"/api/agents/{agent['id']}/publish").raise_for_status()
    action = post(api, "/api/actions", name="Planner")
    kept = node(api, action, "agent", name="Kept", config={"agent_id": agent["id"]})
    gone = node(api, action, "agent", name="Gone", config={"agent_id": agent["id"]})
    api.post(f"{graph_url(action)}/publish", json={"acknowledge": True}).raise_for_status()
    api.delete(f"{graph_url(action)}/nodes/{gone['id']}").raise_for_status()
    panel = _open_usage(page, base_url, "Scribe")
    rows = panel.locator(".mg-uses li")
    expect(rows).to_have_count(2)
    kept_row = rows.filter(has_text="Kept")
    gone_row = rows.filter(has_text="Gone")
    expect(kept_row).not_to_contain_text("Not published yet")
    expect(gone_row).to_contain_text("Only in published version v1")
    expect(kept_row.get_by_role("link")).to_have_attribute(
        "href", f"/actions/{action['slug']}?select={kept['id']}&agent={agent['id']}"
    )
    expect(gone_row.get_by_role("link")).to_have_attribute(
        "href", f"/actions/{action['slug']}"
    )  # not in the draft: nothing to select


def test_an_agent_no_node_uses_says_so(page: Page, base_url: str, api: httpx.Client) -> None:
    _agent(api, "Lonely")
    panel = _open_usage(page, base_url, "Lonely")
    expect(panel.locator(".mg-uses li")).to_have_count(1)
    expect(panel.locator(".mg-uses")).to_contain_text("Not used by any agent node yet.")
