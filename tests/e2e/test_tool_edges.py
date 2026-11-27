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


# ── the tool connection is an ordinary connection: the same bar, the same styles, the same delete (ADR-093) ──

#: A point on the line of an edge (page coordinates), measured once the line has stopped moving.
POINT_ON = """([id, fraction]) => new Promise((resolve) => {
  const measure = () => {
    const path = document.querySelector(`.ge-edge[data-edge-id="${id}"] .ge-edge__line`);
    const at = path.getPointAtLength(path.getTotalLength() * fraction);
    const m = path.getScreenCTM();
    return [at.x * m.a + at.y * m.c + m.e, at.x * m.b + at.y * m.d + m.f];
  };
  let last = measure(), still = 0;
  const frame = () => {
    const now = measure();
    still = Math.hypot(now[0] - last[0], now[1] - last[1]) < 0.5 ? still + 1 : 0;
    last = now;
    if (still >= 3) resolve(now); else requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
})"""


def _edges(api: httpx.Client, action: dict[str, Any]) -> list[dict[str, Any]]:
    return list(api.get(f"/api/actions/{action['id']}").json()["edges"])


def _tool_and_flow_scene(
    api: httpx.Client,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """An action with a flow edge (trigger to agent) and a tool hanging below the agent."""
    action = post(api, "/api/actions", name="Same bar")
    trigger = next(
        n for n in api.get(f"/api/actions/{action['id']}").json()["nodes"] if n["kind"] == "trigger"
    )
    agent = node(api, action, "agent", name="Agent", x=480, y=260)
    tool = node(api, action, "code_tool", x=470, y=520)
    connect(api, action, trigger, "out", agent, "in")
    connect(api, action, tool, "tool", agent, "tools")
    edges = _edges(api, action)
    tool_edge = next(e for e in edges if e["target_port"] == "tools")
    flow_edge = next(e for e in edges if e["target_port"] != "tools")
    return action, flow_edge, tool_edge


def _hover(page: Page, edge_id: str, fraction: float = 0.3) -> None:
    page.mouse.move(*page.evaluate(POINT_ON, [edge_id, fraction]))


def _bar_buttons(page: Page) -> list[str]:
    """The names of the buttons the bar of a connection shows, with its style choices opened."""
    bar = page.locator(".ge-edge-bar")
    expect(bar).to_be_visible()
    names = [
        b.get_attribute("aria-label") or "" for b in bar.locator("> button").all() if b.is_visible()
    ]
    bar.get_by_role("button", name="Change line style").click()
    names += [
        b.get_attribute("aria-label") or ""
        for b in bar.locator(".ge-edge-bar__style").all()
        if b.is_visible()
    ]
    return names


def test_a_tool_connection_shows_the_same_bar_as_a_flow_connection(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action, flow_edge, tool_edge = _tool_and_flow_scene(api)
    page.set_viewport_size({"width": 1500, "height": 950})
    page.goto(f"{base_url}/actions/{action['slug']}")
    expect(page.locator(".ge-edge")).to_have_count(2)
    _hover(page, flow_edge["id"])
    on_flow = _bar_buttons(page)
    page.mouse.move(5, 5)
    expect(page.locator(".ge-edge-bar")).to_be_hidden()
    _hover(page, tool_edge["id"])
    on_tool = _bar_buttons(page)
    assert on_tool == on_flow, (on_flow, on_tool)
    assert "Delete connection" in on_tool and "Change line style" in on_tool
    assert {"Curved", "Straight", "Elbow"} <= set(on_tool), on_tool


def test_an_agent_copied_with_its_tool_keeps_the_connection_and_its_style(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action, _flow, tool_edge = _tool_and_flow_scene(api)
    assert (
        api.patch(
            f"/api/actions/{action['id']}/edges/{tool_edge['id']}", json={"style": "elbow"}
        ).status_code
        == 200
    )
    page.set_viewport_size({"width": 1500, "height": 950})
    page.goto(f"{base_url}/actions/{action['slug']}")
    expect(page.locator(".ge-edge--attachment")).to_have_count(1)
    page.locator(".ge-node--agent").click(position={"x": 30, "y": 5})
    page.locator(".ge-node--code_tool").click(position={"x": 30, "y": 5}, modifiers=["Shift"])
    page.keyboard.press("Control+c")
    page.keyboard.press("Control+v")
    expect(page.locator(".ge-node--agent")).to_have_count(2)
    expect(page.locator(".ge-node--code_tool")).to_have_count(2)
    eventually(lambda: len([e for e in _edges(api, action) if e["target_port"] == "tools"]), 2)
    pasted = [
        e for e in _edges(api, action) if e["target_port"] == "tools" and e["id"] != tool_edge["id"]
    ]
    assert [e["style"] for e in pasted] == ["elbow"], (
        "the copy of a connection keeps its style, like any connection"
    )


def test_the_line_style_of_a_tool_connection_is_chosen_stored_and_drawn(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action, _flow, tool_edge = _tool_and_flow_scene(api)
    page.set_viewport_size({"width": 1500, "height": 950})
    page.goto(f"{base_url}/actions/{action['slug']}")
    line = page.locator(f'.ge-edge[data-edge-id="{tool_edge["id"]}"] .ge-edge__line')
    expect(line).to_have_count(1)
    assert " C " in (line.get_attribute("d") or ""), "curved is the default"
    seen = {"curved": line.get_attribute("d")}
    for style in ("straight", "elbow"):
        _hover(page, tool_edge["id"])
        page.get_by_role("button", name="Change line style").click()
        page.locator(f".ge-edge-bar__style[data-style={style}]").click()
        eventually(
            lambda: next(e["style"] for e in _edges(api, action) if e["id"] == tool_edge["id"]),
            style,
        )
        seen[style] = line.get_attribute("d")
        page.mouse.move(5, 5)
    assert len(set(seen.values())) == 3, seen  # three different lines
    assert " C " not in (seen["straight"] or "") and " Q " not in (seen["straight"] or "")
    assert " Q " in (seen["elbow"] or "") and " C " not in (seen["elbow"] or "")
    page.reload()
    expect(line).to_have_count(1)
    assert line.get_attribute("d") == seen["elbow"], "the style is stored on the connection"


def test_a_tool_connection_is_deleted_from_the_bar_and_by_the_keyboard(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action, _flow, tool_edge = _tool_and_flow_scene(api)
    second_tool = node(api, action, "http_tool", x=760, y=520)
    agent = next(
        n for n in api.get(f"/api/actions/{action['id']}").json()["nodes"] if n["kind"] == "agent"
    )
    connect(api, action, second_tool, "tool", agent, "tools")
    page.set_viewport_size({"width": 1500, "height": 950})
    page.goto(f"{base_url}/actions/{action['slug']}")
    expect(page.locator(".ge-edge--attachment")).to_have_count(2)
    _hover(page, tool_edge["id"])
    page.get_by_role("button", name="Delete connection").click()
    expect(page.locator(".ge-edge--attachment")).to_have_count(1)
    remaining = page.locator(".ge-edge--attachment").first.get_attribute("data-edge-id")
    assert remaining and remaining != tool_edge["id"]
    page.mouse.click(*page.evaluate(POINT_ON, [remaining, 0.3]))  # select it, then the key
    page.keyboard.press("Delete")
    expect(page.locator(".ge-edge--attachment")).to_have_count(0)
    # the canvas drops the line at once, the server's delete follows: wait for it, as for the two lines above (line 231)
    eventually(lambda: [e for e in _edges(api, action) if e["target_port"] == "tools"], [])


def test_the_flow_page_draws_a_tool_connection_in_its_chosen_style(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action, _flow, tool_edge = _tool_and_flow_scene(api)
    styled = api.patch(
        f"/api/actions/{action['id']}/edges/{tool_edge['id']}", json={"style": "straight"}
    )
    assert styled.status_code == 200, styled.text
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
    line = page.locator(".ge-edge--attachment .ge-edge__line")
    expect(line).to_have_count(1)
    path = line.get_attribute("d") or ""
    assert " C " not in path and " Q " not in path, path  # straight, as chosen in the editor
