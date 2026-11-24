"""The edges of the menu of a released line (tests/e2e/test_connect_menu.py has the main flows): a connection the server
refuses takes the new node back and leaves the old connection alone, and a read-only flow neither draws nor opens anything."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import (
    centre,
    echo_pipeline,
    eventually,
    execution_of,
    flow_url,
    start,
    wait_executions,
)
from tests.helpers import connect, graph_url, node

MENU = ".ge-add__menu.is-anchored"


def _release(page: Page, port: Locator, dx: float, dy: float) -> None:
    x, y = centre(port)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=10)
    page.mouse.up()


def _state(
    api: httpx.Client, graph: dict[str, Any]
) -> tuple[set[str], list[tuple[str, str, str, str]]]:
    body = api.get(graph_url(graph)).json()
    edges = sorted(
        (e["source_id"], e["source_port"], e["target_id"], e["target_port"]) for e in body["edges"]
    )
    return {n["id"] for n in body["nodes"]}, edges


def test_a_refused_connection_takes_the_new_node_back_and_keeps_the_old_connection(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    graph: dict[str, Any] = api.post("/api/actions", json={"name": "Refused"}).json()
    code = node(api, graph, "code", x=100, y=40)
    gate = node(api, graph, "http", name="Goal Gate", x=560, y=40)
    connect(api, graph, code, "pass", gate, "in")
    page.set_viewport_size({"width": 1400, "height": 1100})
    page.goto(f"{base_url}/actions/{graph['slug']}")
    expect(page.locator(".ge-node").first).to_be_visible()
    kept = _state(api, graph)
    page.route(
        "**/edges",
        lambda route: (
            route.fulfill(
                status=422,
                content_type="application/json",
                body='{"detail": "That connection is not allowed."}',
            )
            if route.request.method == "POST"
            else route.continue_()
        ),
    )
    _release(page, page.locator(f'[data-node-id="{code["id"]}"] .ge-port--pass'), 60, 230)
    page.fill(f"{MENU} .ge-add__search", "set")
    page.click(f"{MENU} [data-add=set]")
    expect(page.locator("[data-alert]")).to_contain_text("That connection is not allowed.")
    eventually(lambda: _state(api, graph), kept)
    expect(page.locator(".ge-node")).to_have_count(len(kept[0]))


def test_a_read_only_flow_does_not_draw_or_open_anything_from_a_port(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    task = api.post("/api/tasks", json={"title": "Item"}).json()
    start(api, task, echo_pipeline(api))
    wait_executions(api, task, ["done"])
    page.goto(flow_url(base_url, task, execution_of(api, task)))
    port = page.locator(".ge-port").first
    expect(port).to_be_visible()
    _release(page, port, 120, 160)
    expect(page.locator(MENU)).to_have_count(0)
    expect(page.locator(".ge-edge__line--draft")).to_have_count(0)
