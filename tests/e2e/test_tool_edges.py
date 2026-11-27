"""The line from a tool to its agent never runs through a card (ADR-040, ADR-079): a tool below its agent keeps the short line up, a tool above or
beside it goes round. The rule is the same for every tool kind, in the editor and on the flow page (the same drawing)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import api, base_url, browser_context_args
from tests.e2e.helpers import eventually
from tests.helpers import connect, node, post

__all__ = ["api", "base_url", "browser_context_args"]  # the fixtures of the e2e suite, used by name
pytestmark = pytest.mark.e2e

#: Where each tool sits relative to the agent at (480, 260): the owner's case is the tool above it.
PLACES = {
    "code_tool": (470, 520),  # below
    "http_tool": (470, 80),  # above
    "openartifact_tool": (120, 300),  # left, level with the agent
    "postgres_tool": (900, 300),  # right, level with the agent
}

#: In the browser: sample each attachment path, take it to the page's coordinates and count the points inside the two cards it joins.
INSIDE = """() => {
  const rects = {};
  document.querySelectorAll('.ge-node[data-node-id]').forEach((n) => { rects[n.dataset.nodeId] = n.getBoundingClientRect(); });
  const out = [];
  document.querySelectorAll('.ge-edge--attachment .ge-edge__line').forEach((path) => {
    const m = path.getScreenCTM();
    const length = path.getTotalLength();
    const edge = path.closest('[data-edge-id]').dataset.edgeId;
    let inside = 0;
    const hits = [];
    for (let i = 0; i <= 160; i += 1) {
      const p = path.getPointAtLength((length * i) / 160);
      const x = p.x * m.a + p.y * m.c + m.e;
      const y = p.x * m.b + p.y * m.d + m.f;
      for (const [id, r] of Object.entries(rects)) {
        if (x > r.left + 2 && x < r.right - 2 && y > r.top + 2 && y < r.bottom - 2) { inside += 1; hits.push(id); }
      }
    }
    out.push({ edge, inside, hits: [...new Set(hits)] });
  });
  return out;
}"""


def _scene(api: httpx.Client) -> dict[str, Any]:
    action = post(api, "/api/actions", name="Tool edges")
    agent = node(api, action, "agent", name="Agent", x=480, y=260)
    for kind, (x, y) in PLACES.items():
        tool = node(api, action, kind, x=x, y=y)
        connect(api, action, tool, "tool", agent, "tools")
    return action


def _check(page: Page) -> None:
    expect(page.locator(".ge-edge--attachment")).to_have_count(len(PLACES))
    page.wait_for_timeout(400)
    found = page.evaluate(INSIDE)
    assert len(found) == len(PLACES), found
    for line in found:
        assert line["inside"] == 0, f"a tool line runs through a card: {line}"


def test_no_tool_line_runs_through_a_card_wherever_the_tool_sits_in_the_editor(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _scene(api)
    page.set_viewport_size({"width": 1500, "height": 950})
    page.goto(f"{base_url}/actions/{action['slug']}")
    _check(page)


def test_a_tool_above_its_agent_leaves_upwards_and_reaches_the_agents_port_from_below(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = post(api, "/api/actions", name="Above")
    agent = node(api, action, "agent", name="Agent", x=480, y=260)
    tool = node(api, action, "http_tool", x=470, y=80)
    connect(api, action, tool, "tool", agent, "tools")
    page.set_viewport_size({"width": 1500, "height": 950})
    page.goto(f"{base_url}/actions/{action['slug']}")
    line = page.locator(".ge-edge--attachment .ge-edge__line")
    expect(line).to_have_count(1)
    port = page.locator(f'.ge-port[data-node-id="{agent["id"]}"][data-port="tools"]').bounding_box()
    assert port
    start = page.locator(f'.ge-port[data-node-id="{tool["id"]}"][data-port="tool"]').bounding_box()
    assert start
    ends = page.evaluate(
        """() => { const p = document.querySelector('.ge-edge--attachment .ge-edge__line'); const m = p.getScreenCTM(); const L = p.getTotalLength();
          const at = (t) => { const q = p.getPointAtLength(L * t); return { x: q.x * m.a + q.y * m.c + m.e, y: q.x * m.b + q.y * m.d + m.f }; };
          return { start: at(0), near_end: at(0.97), end: at(1) }; }"""
    )
    # it starts at the tool's port and ends at the agent's port, arriving from underneath
    assert (
        abs(ends["start"]["x"] - (start["x"] + start["width"] / 2)) <= 3
        and abs(ends["start"]["y"] - (start["y"] + start["height"] / 2)) <= 12
    )
    assert abs(ends["end"]["x"] - (port["x"] + port["width"] / 2)) <= 3
    assert ends["near_end"]["y"] > ends["end"]["y"], (
        "the last stretch comes up to the port from below"
    )


def test_the_flow_page_draws_the_same_lines(page: Page, base_url: str, api: httpx.Client) -> None:
    action = _scene(api)
    started = api.post(f"/api/graphs/{action['id']}/dry-run", json={})
    assert started.status_code == 201, started.text
    task_id = started.json()["task_id"]
    eventually(
        lambda: (
            api.get(f"/api/tasks/{task_id}/executions").json()["items"][0]["status"] != "running"
        ),
        True,
    )
    execution = api.get(f"/api/tasks/{task_id}/executions").json()["items"][0]
    number = api.get(f"/api/tasks/{task_id}").json()["number"]
    page.set_viewport_size({"width": 1500, "height": 950})
    page.goto(f"{base_url}/artifacts/{number}/executions/{execution['id']}")
    expect(page.locator(".ge-edge--attachment")).to_have_count(len(PLACES))
    page.wait_for_timeout(400)
    for line in page.evaluate(INSIDE):
        assert line["inside"] == 0, f"a tool line runs through a card on the flow page: {line}"
