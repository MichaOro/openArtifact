"""A connection can be started from any port in the pipeline editor, an input as well as an output.

Dragging from an input port ("in" of an action) to an output draws the same connection as the other way round: it is
stored in the normal direction (source = the output, target = the input), and the node under the press does not move.
"""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import centre, drag, eventually
from tests.helpers import graph_url, node

STAGE_SIZE = {"width": 520, "height": 360}


def _pipeline(client: httpx.Client) -> dict[str, Any]:
    """A stage with two actions side by side and nothing connected."""
    pipeline: dict[str, Any] = client.post("/api/pipelines", json={"name": "Reverse"}).json()
    stage = node(client, pipeline, "stage", name="Gap", x=200, y=40)
    client.patch(f"{graph_url(pipeline)}/nodes/{stage['id']}", json=STAGE_SIZE).raise_for_status()
    first = node(client, pipeline, "action", stage_id=stage["id"], x=40, y=60)
    second = node(client, pipeline, "action", stage_id=stage["id"], x=280, y=160)
    pipeline["stage"], pipeline["first"], pipeline["second"] = stage, first, second
    return pipeline


def _open(page: Page, base_url: str, pipeline: dict[str, Any]) -> None:
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    expect(page.locator(".ge-node--action")).to_have_count(2)
    page.click("[data-zoom-fit]")


def _action(page: Page, node_id: str) -> Locator:
    return page.locator(f'.ge-node--action[data-node-id="{node_id}"]')


def _edges(api: httpx.Client, pipeline: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """The edges between the nodes this test made (a new pipeline brings a trigger and an output of its own)."""
    mine = {pipeline["stage"]["id"], pipeline["first"]["id"], pipeline["second"]["id"]}
    graph = api.get(graph_url(pipeline)).json()
    return sorted(
        (e["source_id"], e["source_port"], e["target_id"], e["target_port"])
        for e in graph["edges"]
        if e["source_id"] in mine or e["target_id"] in mine
    )


def _stored_position(
    api: httpx.Client, pipeline: dict[str, Any], node_id: str
) -> tuple[float, float]:
    nodes = api.get(graph_url(pipeline)).json()["nodes"]
    found = next(n for n in nodes if n["id"] == node_id)
    return found["x"], found["y"]


def test_a_connection_starts_at_an_input_port_and_is_stored_from_the_output(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    first, second = pipeline["first"], pipeline["second"]
    before = _stored_position(api, pipeline, second["id"])
    _open(page, base_url, pipeline)
    drag(
        page,
        _action(page, second["id"]).locator(".ge-port--in"),
        _action(page, first["id"]).locator(".ge-port--pass"),
    )
    eventually(
        lambda: _edges(api, pipeline), [(first["id"], "pass", second["id"], "in")]
    )  # the normal direction, whichever end was pressed
    assert _stored_position(api, pipeline, second["id"]) == before, (
        "pressing a port must not move the node"
    )


def test_a_connection_from_an_input_port_ends_at_a_stage_slot(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    stage, first = pipeline["stage"], pipeline["first"]
    _open(page, base_url, pipeline)
    drag(
        page,
        _action(page, first["id"]).locator(".ge-port--in"),
        page.locator(".ge-node--stage > .ge-port--start[data-slot='0']"),
    )
    eventually(lambda: _edges(api, pipeline), [(stage["id"], "start", first["id"], "in")])


def test_a_drop_that_does_not_fit_creates_nothing_and_the_node_stays(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    first, second = pipeline["first"], pipeline["second"]
    before = _stored_position(api, pipeline, second["id"])
    _open(page, base_url, pipeline)
    # an input onto another input does not fit
    drag(
        page,
        _action(page, second["id"]).locator(".ge-port--in"),
        _action(page, first["id"]).locator(".ge-port--in"),
    )
    # and a drop on empty canvas ends the gesture without a connection
    x, y = centre(_action(page, second["id"]).locator(".ge-port--in"))
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x - 40, y + 120, steps=8)
    page.mouse.up()
    expect(page.locator(".ge-edge__line--draft")).to_have_count(0)
    expect(page.locator(".is-connecting")).to_have_count(0)
    assert _edges(api, pipeline) == []
    assert _stored_position(api, pipeline, second["id"]) == before


def test_the_node_still_moves_when_it_is_pressed_on_its_body(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    second = pipeline["second"]
    before = _stored_position(api, pipeline, second["id"])
    _open(page, base_url, pipeline)
    card = _action(page, second["id"])
    x, y = centre(card.locator(".ge-node__name"))
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 30, y + 20, steps=8)
    page.mouse.up()
    eventually(lambda: _stored_position(api, pipeline, second["id"]) != before, True)
