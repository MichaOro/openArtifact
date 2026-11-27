"""The cards of the pipeline view (the owner's decision B+D): an action card is 228 x 76, the title of an action, an agent and the other flow cards reserves two
lines always, so a card does not change its height with its name, and the kind label under it has air."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_guard_scopes import _attach_to
from tests.e2e.test_guards import _guard
from tests.helpers import connect, graph_url, node, post

pytestmark = pytest.mark.e2e

SHORT = "Hi"
LONG = "Summarise the customer feedback of the last quarter and decide what to do next"
BOXES = """(card) => {
  const box = (el) => { const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height, b: r.y + r.height, r: r.x + r.width}; };
  const name = card.querySelector('.ge-node__name');
  const kind = card.querySelector('.ge-node__kind');
  const line = parseFloat(getComputedStyle(name).lineHeight);
  return {card: box(card), name: box(name), kind: box(kind), line, scrollH: name.scrollHeight, clientH: name.clientHeight,
          ports: [...card.querySelectorAll(':scope > .ge-port:not([hidden])')].map((p) => ({port: p.dataset.port, ...box(p)})),
          icons: card.querySelector('.ge-node__icons') ? box(card.querySelector('.ge-node__icons')) : null};
}"""


def _pipeline(api: httpx.Client) -> dict[str, Any]:
    pipeline = post(api, "/api/pipelines", name="Titles")
    stage = node(api, pipeline, "stage", name="Stage", x=20, y=20)
    api.patch(
        f"{graph_url(pipeline)}/nodes/{stage['id']}", json={"width": 640, "height": 260}
    ).raise_for_status()
    placed = []
    for index, name in enumerate((SHORT, LONG)):
        definition = post(api, "/api/actions", name=name)
        card = node(
            api, pipeline, "action", stage_id=stage["id"], x=24 + index * 292, y=24 + index * 20
        )
        api.patch(
            f"{graph_url(pipeline)}/nodes/{card['id']}", json={"definition_id": definition["id"]}
        ).raise_for_status()
        placed.append(card)
    connect(api, pipeline, placed[0], "pass", placed[1], "in")
    pipeline["placed"] = placed
    return pipeline


def _cards(page: Page, selector: str) -> list[dict[str, Any]]:
    cards = page.locator(selector)
    return [cards.nth(i).evaluate(BOXES) for i in range(cards.count())]


def test_an_action_card_keeps_its_height_whatever_its_name_and_the_kind_label_has_air(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    expect(page.locator(".ge-node--action")).to_have_count(2)
    page.click("[data-zoom-fit]")
    short, long = _cards(page, ".ge-node--action")
    # the card keeps its height: a one-line and a two-line name give the same box, 228 x 76 in the model, scaled by the zoom
    assert abs(short["card"]["h"] - long["card"]["h"]) < 0.5, (short["card"], long["card"])
    assert abs(short["card"]["w"] - long["card"]["w"]) < 0.5
    assert abs(short["card"]["w"] / short["card"]["h"] - 228 / 76) < 0.02, short["card"]
    # the title reserves two lines in both: the short name leaves the second empty, nothing moves
    assert abs(short["name"]["h"] - long["name"]["h"]) < 0.5, (short["name"], long["name"])
    assert abs(short["name"]["h"] / short["line"] - 2) < 0.1, short
    assert (
        abs((short["name"]["y"] - short["card"]["y"]) - (long["name"]["y"] - long["card"]["y"]))
        < 0.5
    ), "the title starts at the same place"
    assert (
        abs((short["kind"]["y"] - short["card"]["y"]) - (long["kind"]["y"] - long["card"]["y"]))
        < 0.5
    ), "and so does the kind label"
    # air: the kind label starts below the end of the second title line, by a gap (0.3 rem, scaled by the zoom: at least 3 px at the fit zoom)
    for card in (short, long):
        assert card["kind"]["y"] - card["name"]["b"] >= 3, card
    # a long name is cut at the end of the second line
    assert long["scrollH"] > long["clientH"] + 1, (
        "the long name needs more than its two lines and is cut"
    )
    # the ports sit at the same relative place on both cards
    for p_short, p_long in zip(short["ports"], long["ports"], strict=True):
        assert p_short["port"] == p_long["port"]
        assert abs((p_short["y"] - short["card"]["y"]) - (p_long["y"] - long["card"]["y"])) < 0.5, (
            p_short,
            p_long,
        )
        assert abs((p_short["x"] - short["card"]["x"]) - (p_long["x"] - long["card"]["x"])) < 0.5, (
            p_short,
            p_long,
        )


def test_an_edge_ends_at_the_port_of_the_wider_card(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    expect(page.locator(".ge-node--action")).to_have_count(2)
    page.click("[data-zoom-fit]")
    first, second = page.locator(".ge-node--action").nth(0), page.locator(".ge-node--action").nth(1)
    out = first.locator(".ge-port--pass").bounding_box()
    into = second.locator(".ge-port--in").bounding_box()
    assert out and into
    # one of the pass edges starts at the middle of the first card's On Pass and ends at the middle of the second card's input
    lines = page.locator(".ge-edge--pass .ge-edge__line")
    ends = []
    for i in range(lines.count()):
        box = lines.nth(i).bounding_box()
        assert box
        ends.append(box)
    start = (out["x"] + out["width"] / 2, out["y"] + out["height"] / 2)
    end = (into["x"] + into["width"] / 2, into["y"] + into["height"] / 2)
    found = [
        box
        for box in ends
        if abs(box["x"] - start[0]) <= 8
        and abs(box["x"] + box["width"] - end[0]) <= 8
        and min(abs(box["y"] - start[1]), abs(box["y"] + box["height"] - start[1])) <= 8
    ]
    assert found, (ends, start, end)


def test_the_flow_cards_share_the_two_reserved_lines_and_the_icon_list_stays_off_the_title(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = post(api, "/api/actions", name="Agents")
    node(api, action, "agent", name="Plain agent", x=40, y=40)
    marked = node(api, action, "agent", name=LONG, x=40, y=200)
    api.patch(
        f"{graph_url(action)}/nodes/{marked['id']}",
        json={
            "mock": {"enabled": True, "outcome": "pass", "output": "x", "data": {}, "reason": ""}
        },
    ).raise_for_status()
    _attach_to(api, _guard(api, "Agent guard"), action, "node", marked["id"])
    page.goto(f"{base_url}/actions/{action['slug']}")
    expect(page.locator(".ge-node--agent")).to_have_count(2)
    page.click("[data-zoom-fit]")
    both = _cards(page, ".ge-node--agent")
    assert len(both) == 2
    first, second = both
    assert abs(first["card"]["h"] - second["card"]["h"]) < 0.5, (
        "the same height for a short and a long name"
    )
    assert abs(first["name"]["h"] - second["name"]["h"]) < 0.5, "two reserved lines each"
    assert abs(first["name"]["h"] / first["line"] - 2) < 0.1
    for card in both:
        assert card["kind"]["y"] - card["name"]["b"] >= 3, card
    # the card with the pin and the shield: the icon list lies beside the title, not over its text
    marked_card = next(c for c in both if c["icons"])
    icons, name = marked_card["icons"], marked_card["name"]
    overlap_x = min(icons["r"], name["r"]) - max(icons["x"], name["x"])
    overlap_y = min(icons["b"], name["b"]) - max(icons["y"], name["y"])
    assert not (overlap_x > 0 and overlap_y > 0), (icons, name)
