"""How the graph editors are handled with the mouse: the right button pans, the left one selects (a click, or a
frame drawn on the background), selected nodes move together, and a double click opens the node's settings in an
overlay instead of a panel beside the canvas."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import eventually
from tests.helpers import graph_url


def _action_with_two_code_nodes(page: Page, base_url: str, api: httpx.Client) -> dict[str, Any]:
    definition: dict[str, Any] = api.post("/api/actions", json={"name": "Handling"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    for _ in range(2):
        page.click("[data-add-menu]")
        page.click("[data-add=code]")
    expect(page.locator(".ge-node--code")).to_have_count(2)
    page.click("[data-zoom-fit]")
    return definition


def _positions(api: httpx.Client, definition: dict[str, Any]) -> dict[str, tuple[int, int]]:
    nodes = api.get(graph_url(definition)).json()["nodes"]
    return {n["id"]: (n["x"], n["y"]) for n in nodes}


def _empty_spot(page: Page) -> tuple[float, float]:
    box = page.locator("[data-viewport]").bounding_box()
    assert box is not None
    return box["x"] + 12, box["y"] + box["height"] - 12


def test_the_right_button_pans_and_the_left_button_on_the_background_does_not(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _action_with_two_code_nodes(page, base_url, api)
    node = page.locator(".ge-node--trigger")
    before = node.bounding_box()
    assert before is not None
    x, y = _empty_spot(page)
    page.mouse.move(x, y)
    page.mouse.down(button="right")
    page.mouse.move(x + 90, y - 40, steps=8)
    page.mouse.up(button="right")
    after = node.bounding_box()
    assert after is not None
    assert (round(after["x"] - before["x"]), round(after["y"] - before["y"])) == (90, -40)
    assert (
        page.locator(".ge-contextmenu, [role=menu]:visible").count() == 0
    )  # no browser menu either

    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 60, y - 20, steps=5)
    page.mouse.up()
    still = node.bounding_box()
    assert still is not None and (still["x"], still["y"]) == (after["x"], after["y"])


def test_a_frame_on_the_background_selects_the_nodes_it_touches_and_they_move_together(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _action_with_two_code_nodes(page, base_url, api)
    codes = page.locator(".ge-node--code")
    first, second = codes.nth(0), codes.nth(1)
    a, b = first.bounding_box(), second.bounding_box()
    assert a is not None and b is not None
    left = min(a["x"], b["x"]) - 10
    top = min(a["y"], b["y"]) - 10
    right = max(a["x"] + a["width"], b["x"] + b["width"]) + 10
    bottom = max(a["y"] + a["height"], b["y"] + b["height"]) + 10
    page.mouse.move(right, bottom)  # from the lower right to the upper left, across both
    page.mouse.down()
    page.mouse.move(left, top, steps=8)
    expect(page.locator(".ge-marquee")).to_be_visible()
    page.mouse.up()
    expect(page.locator(".ge-marquee")).to_have_count(0)
    expect(page.locator(".ge-node.is-selected")).to_have_count(2)
    expect(page.locator(".ge-node--trigger.is-selected")).to_have_count(0)

    before = _positions(api, definition)
    grip = first.bounding_box()
    assert grip is not None
    sx, sy = (
        grip["x"] + 30,
        grip["y"] + 5,
    )  # the top edge of the card: the line between the nodes crosses its middle
    page.mouse.move(sx, sy)
    page.mouse.down()
    page.mouse.move(sx + 70, sy + 50, steps=8)
    page.mouse.up()

    def moved() -> bool:
        now = _positions(api, definition)
        shifts = {
            (now[i][0] - before[i][0], now[i][1] - before[i][1]) for i in now if now[i] != before[i]
        }
        changed = [i for i in now if now[i] != before[i]]
        # exactly the two selected nodes, both by the same distance (to the right and down)
        return (
            len(changed) == 2
            and len(shifts) == 1
            and next(iter(shifts))[0] > 0
            and next(iter(shifts))[1] > 0
        )

    eventually(moved, True)


def test_a_click_selects_one_node_and_a_click_on_the_background_clears_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _action_with_two_code_nodes(page, base_url, api)
    codes = page.locator(".ge-node--code")
    codes.nth(0).click(position={"x": 30, "y": 5})
    expect(page.locator(".ge-node.is-selected")).to_have_count(1)
    expect(page.locator("#node-modal")).not_to_be_visible()  # a click opens nothing
    page.mouse.click(*_empty_spot(page))
    expect(page.locator(".ge-node.is-selected")).to_have_count(0)


def test_a_double_click_opens_the_settings_in_an_overlay_and_there_is_no_side_panel(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _action_with_two_code_nodes(page, base_url, api)
    expect(page.locator("aside.ge-inspector")).to_have_count(0)
    node: Locator = page.locator(".ge-node--code").first
    node.dblclick(position={"x": 30, "y": 5})
    dialog = page.locator("#node-modal")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_label("Code", exact=True)).to_be_visible()
    dialog.get_by_label("Code", exact=True).fill("echo changed")
    dialog.get_by_label("Code", exact=True).press("Escape")  # leaves the code field only
    expect(dialog).to_be_visible()
    page.keyboard.press("Escape")  # the next one closes the dialog
    expect(dialog).not_to_be_visible()


def test_the_add_menu_is_clustered_and_a_search_narrows_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition: dict[str, Any] = api.post("/api/actions", json={"name": "Menu"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    page.click("[data-add-menu]")
    menu = page.locator("[data-add-list]")
    expect(page.locator(".ge-add__search")).to_be_focused()  # type straight away
    expect(menu.locator(".ge-add__group")).to_have_text(
        ["AI", "Agent tools", "Apps and data", "Core", "Data", "Flow"]
    )
    page.keyboard.type("git")
    expect(menu.locator("[data-add]")).to_have_text(["GitHub"])
    expect(menu.locator(".ge-add__group")).to_have_text(
        ["Apps and data"]
    )  # empty clusters are gone
    page.keyboard.press("Control+A")
    page.keyboard.type("tool")  # the cluster's name matches too
    expect(menu.locator("[data-add]")).to_have_count(4)
    page.keyboard.press("Control+A")
    page.keyboard.type("nothing like this")
    expect(menu.locator(".ge-add__empty")).to_be_visible()
    page.keyboard.press("Control+A")
    page.keyboard.type("timer")
    page.keyboard.press("Enter")  # adds the first match
    expect(page.locator(".ge-node--timer")).to_have_count(1)
    expect(menu).to_be_hidden()
    page.click("[data-add-menu]")  # opened again: a clean list
    expect(page.locator(".ge-add__search")).to_have_value("")
    expect(menu.locator("[data-add]")).to_have_count(13)
