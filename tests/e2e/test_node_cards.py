"""One card for every execution node (ADR-054 addendum): the look is keyed by the kind's behaviour and its colour is the manifest's
``ui.color``, so a kind added later looks like the others without a line of CSS. The Artifact node used to draw its icon over its
title because the card rules existed for five kinds only; and the reference picker offered the result of seven kinds only."""

from __future__ import annotations

import re
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import pick_node
from tests.e2e.test_ui_catalog import MEASURE, _theme
from tests.helpers import graph_url

# the execution kinds with a colour of their own (if and switch share the colour of a branch, a timer has no icon)
OWN_COLOUR = ["code", "http", "github", "postgres", "artifact", "set", "agent"]
STEPS = [*OWN_COLOUR, "if", "switch", "timer"]

GEOMETRY = """
(card) => {
  const box = (el) => { const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; };
  const icon = card.querySelector('.ge-node__icon');
  return {
    card: box(card),
    icon: icon ? box(icon) : null,
    text: box(card.querySelector('.ge-node__text')),
    name: box(card.querySelector('.ge-node__name')),
    colour: getComputedStyle(card).borderTopColor,
    behaviour: card.dataset.behaviour,
  };
}
"""


@pytest.fixture
def cards(page: Page, base_url: str, api: httpx.Client) -> dict[str, Any]:
    """An action with one node of every execution kind, and the geometry of each card."""
    definition = api.post("/api/actions", json={"name": "Cards"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    for kind in STEPS:
        page.click("[data-add-menu]")
        pick_node(page, kind)
        expect(page.locator(f".ge-node--{kind}")).to_have_count(1)
    return {"definition": definition}


def _geometry(page: Page, kind: str) -> dict[str, Any]:
    return page.locator(f".ge-node--{kind}").evaluate(GEOMETRY)  # type: ignore[no-any-return]


def test_every_execution_node_draws_its_icon_inline_before_its_name(
    page: Page, cards: dict[str, Any]
) -> None:
    """The icon sits left of the text column, centred on the card and inside it: it never covers the title."""
    for kind in STEPS:
        g = _geometry(page, kind)
        assert g["behaviour"] in ("flow", "switch", "plain"), kind
        if kind == "timer":
            assert g["icon"] is None  # a timer has no icon; it still has the same text column
            continue
        icon, text, card = g["icon"], g["text"], g["card"]
        assert icon, f"{kind} has no icon"
        assert icon["x"] >= card["x"] and icon["x"] + icon["width"] <= card["x"] + card["width"], (
            f"{kind}: icon inside"
        )
        assert icon["x"] + icon["width"] <= text["x"] + 1, (
            f"{kind}: the icon is left of the text, not over the title"
        )
        assert text["x"] - (icon["x"] + icon["width"]) < 24, f"{kind}: a short gap after the icon"
        middle = icon["y"] + icon["height"] / 2
        assert abs(middle - (card["y"] + card["height"] / 2)) < 4, (
            f"{kind}: icon centred on the card"
        )
        assert g["name"]["x"] >= icon["x"] + icon["width"], (
            f"{kind}: the title does not start under the icon"
        )


def test_the_cards_of_the_same_behaviour_have_the_same_size_and_a_colour_each(
    page: Page, cards: dict[str, Any]
) -> None:
    flow = {kind: _geometry(page, kind) for kind in OWN_COLOUR}
    heights = {round(g["card"]["height"]) for g in flow.values()}
    widths = {round(g["card"]["width"]) for g in flow.values()}
    assert len(heights) == 1 and len(widths) == 1, (
        f"the same card for every kind: {heights} x {widths}"
    )
    colours = {kind: g["colour"] for kind, g in flow.items()}
    assert len(set(colours.values())) == len(colours), f"one colour per kind: {colours}"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_text_of_every_card_is_readable_on_its_colour(
    page: Page, cards: dict[str, Any], theme: str
) -> None:
    _theme(page, theme)
    for kind in STEPS:
        card = page.locator(f".ge-node--{kind}")
        for part in (".ge-node__name", ".ge-node__kind"):
            if not card.locator(part).count():
                continue
            ratio = page.evaluate(f"({MEASURE})", card.locator(part).element_handle())["text"]
            assert ratio >= 4.5, f"{kind} {part} in {theme}: contrast {ratio:.2f}"


def test_the_reference_picker_of_an_agent_input_offers_the_result_of_every_kind_that_leaves_one(
    page: Page, base_url: str, api: httpx.Client, cards: dict[str, Any]
) -> None:
    """GitHub, Postgres and Artifact nodes were missing from the list the editor kept; now the kinds say it."""
    for left in api.get(
        "/api/agents"
    ).json():  # the server is shared by the tests of a worker: one agent of this name only
        if left["name"] == "Triage":
            api.delete(f"/api/agents/{left['id']}")
    agent = api.post(
        "/api/agents",
        json={
            "name": "Triage",
            "draft": {
                "user_prompt": "Go: ${input.ticket}",
                "inputs": [{"name": "ticket", "required": True}],
            },
        },
    ).json()
    api.post(f"/api/agents/{agent['id']}/publish")
    nodes = api.get(graph_url(cards["definition"])).json()["nodes"]
    node = next(n for n in nodes if n["kind"] == "agent")
    api.patch(
        f"/api/actions/{cards['definition']['id']}/nodes/{node['id']}",
        json={"config": {"agent_id": agent["id"]}},
    )
    page.reload()
    expect(page.locator(".ge-node--agent")).to_be_visible()
    page.locator(".ge-node--agent").dblclick(position={"x": 30, "y": 5})
    field = page.locator(".ge-inspector").get_by_label("Value for ${input.ticket}")
    field.click()
    field.fill("${")
    popup = page.locator(".popover--suggest")
    expect(popup).to_be_visible()
    offered = " | ".join(popup.locator("[role=option]").all_inner_texts())
    names = {n["kind"]: n["name"] for n in nodes}
    for kind in ("artifact", "github", "postgres", "set", "code", "http", "if", "switch", "timer"):
        assert re.search(rf"\({re.escape(names[kind])}\)\.", offered) or names[kind] in offered, (
            f"{kind} ({names[kind]}) not offered: {offered}"
        )
    # the data a kind declares is offered once its node is chosen
    field.fill(f"${{({names['artifact']}).")
    expect(popup.locator("[role=option]", has_text="data.comments")).to_be_visible()
