"""The small icons on a node card (components/card-icons.js): the mock pin and the shield of the guards are ONE flexible list in the top right corner, with the rule
of every such list (the status bar of the canvas corner has it too): fixed places in the order, only the active entries are there, no gap, anchored at the right edge
and growing to the left, one hover for all of them."""

from __future__ import annotations

from typing import Any, cast

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_guard_scopes import _action, _attach_to
from tests.e2e.test_guards import _guard, _open
from tests.helpers import graph_url

NAME = "Summarise code"
MOCK = {"enabled": True, "outcome": "pass", "output": "stored", "data": {}, "reason": ""}


def _box(el: Locator) -> dict[str, float]:
    box = el.bounding_box()
    assert box is not None
    return cast(dict[str, float], box)


def _node_id(api: httpx.Client, action: dict[str, Any]) -> str:
    nodes = api.get(graph_url(action)).json()["nodes"]
    return str(next(n for n in nodes if n["name"] == NAME)["id"])


def _set_mock(api: httpx.Client, action: dict[str, Any], node_id: str) -> None:
    api.patch(f"{graph_url(action)}/nodes/{node_id}", json={"mock": MOCK}).raise_for_status()


def _card(page: Page) -> Locator:
    return page.locator(".ge-node", has_text=NAME).first


def test_the_pin_sits_left_of_the_shield_with_no_gap_and_not_over_the_port_labels(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _action(api)
    node_id = _node_id(api, action)
    _set_mock(api, action, node_id)
    _attach_to(api, _guard(api, "Stall guard"), action, "node", node_id)
    _open(page, base_url, f"/actions/{action['slug']}")
    card = _card(page)
    pin, shield = card.locator("[data-mock-pin]"), card.locator("[data-guard-shield]")
    expect(pin).to_be_visible()
    expect(shield).to_be_visible()
    cb, pb, sb = _box(card), _box(pin), _box(shield)
    assert pb["x"] + pb["width"] <= sb["x"] + 1, "the pin is on the left of the shield"
    assert sb["x"] - (pb["x"] + pb["width"]) <= 4, "side by side, no gap"
    assert abs(pb["y"] - sb["y"]) <= 1 and pb["height"] == sb["height"], "one row, one size"
    assert sb["x"] + sb["width"] > cb["x"] + cb["width"] - 10, "the shield is at the right edge"
    assert pb["y"] >= cb["y"] and sb["y"] >= cb["y"], "inside the card: nothing sticks out above it"
    port = _box(page.locator(f".ge-port[data-node-id='{node_id}'][data-direction='output']").first)
    label_middle = port["y"] + port["height"] / 2
    assert pb["y"] + pb["height"] <= label_middle and sb["y"] + sb["height"] <= label_middle, (
        "the icons end above the middle of the first output port and its label"
    )
    assert pb["y"] - cb["y"] <= 4 and sb["y"] - cb["y"] <= 4, (
        "in the top strip of the card, where the shield always was"
    )
    assert card.locator(".ge-node__icons > *").evaluate_all(
        "els => els.map(e => e.dataset.cardIcon)"
    ) == ["mock", "guard"]


def test_with_only_the_pin_it_sits_at_the_right_edge_and_with_only_the_shield_where_it_always_was(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _action(api)
    node_id = _node_id(api, action)
    _set_mock(api, action, node_id)
    _open(page, base_url, f"/actions/{action['slug']}")
    card = _card(page)
    cb, pb = _box(card), _box(card.locator("[data-mock-pin]"))
    assert pb["x"] + pb["width"] > cb["x"] + cb["width"] - 10, (
        "the pin takes the right anchor when it is alone"
    )
    expect(card.locator("[data-guard-shield]")).to_have_count(0)
    # the guard comes (attached through the API, the page follows on reload): the pin moves left, the shield takes the anchor
    _attach_to(api, _guard(api, "Stall guard"), action, "node", node_id)
    page.reload()
    card = _card(page)
    expect(card.locator("[data-guard-shield]")).to_be_visible()
    cb, pb, sb = (
        _box(card),
        _box(card.locator("[data-mock-pin]")),
        _box(card.locator("[data-guard-shield]")),
    )
    assert sb["x"] + sb["width"] > cb["x"] + cb["width"] - 10
    assert pb["x"] < sb["x"]
    api.patch(
        f"{graph_url(action)}/nodes/{node_id}", json={"mock": {**MOCK, "enabled": False}}
    ).raise_for_status()
    page.reload()
    card = _card(page)
    expect(card.locator("[data-mock-pin]")).to_have_count(0)
    cb, sb = _box(card), _box(card.locator("[data-guard-shield]"))
    assert sb["x"] + sb["width"] > cb["x"] + cb["width"] - 10, "the shield alone is where it was"
    expect(card.locator(".ge-node__icons")).to_have_count(1)


def test_both_icons_have_the_same_hover_and_the_pin_opens_the_mock_tab_and_the_keyboard_goes_pin_then_shield(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _action(api)
    node_id = _node_id(api, action)
    _set_mock(api, action, node_id)
    _attach_to(api, _guard(api, "Stall guard"), action, "node", node_id)
    _open(page, base_url, f"/actions/{action['slug']}")
    card = _card(page)
    pin, shield = card.locator("[data-mock-pin]"), card.locator("[data-guard-shield]")
    read = "el => getComputedStyle(el).backgroundColor"
    for icon in (pin, shield):
        before = icon.evaluate(read)
        icon.hover()
        page.wait_for_timeout(250)
        assert icon.evaluate(read) != before, "a hover tint shows that the icon can be clicked"
    page.mouse.move(5, 5)
    page.wait_for_timeout(250)
    tints = []
    for icon in (pin, shield):
        icon.hover()
        page.wait_for_timeout(700)  # the hover is a transition: read the end of it
        tints.append(icon.evaluate(read))
    assert tints[0] == tints[1], "one hover rule for all the icons of a card"
    # keyboard: the pin comes first, then the shield
    pin.focus()
    page.keyboard.press("Tab")
    assert shield.evaluate("el => el === document.activeElement")
    pin.click()
    dialog = page.locator("#node-modal")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("tab", name="Mock")).to_have_attribute("aria-selected", "true")
