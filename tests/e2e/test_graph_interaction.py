"""How the graph editors are handled with the mouse: the right button pans, the left one selects (a click, or a
frame drawn on the background), selected nodes move together, and a double click opens the node's settings in an
overlay instead of a panel beside the canvas."""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import eventually, pick_node
from tests.helpers import graph_url


def _action_with_two_code_nodes(page: Page, base_url: str, api: httpx.Client) -> dict[str, Any]:
    definition: dict[str, Any] = api.post("/api/actions", json={"name": "Handling"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    for _ in range(2):
        page.click("[data-add-menu]")
        pick_node(page, "code")
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


def test_the_add_menu_has_closed_clusters_to_find_your_way_and_a_search_over_the_nodes(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition: dict[str, Any] = api.post("/api/actions", json={"name": "Menu"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    page.click("[data-add-menu]")
    menu = page.locator("[data-add-list]")
    expect(page.locator(".ge-add__search")).to_be_focused()  # type straight away
    groups = menu.locator(".ge-add__group")
    expect(groups).to_have_text(
        ["Structure1", "AI1", "Agent tools7", "Apps and data2", "Core2", "Data3", "Flow3"]
    )  # Structure holds only the Guard here: nothing else of it can be added to an action (ADR-060)
    expect(menu.locator("[data-add]")).to_have_count(0)  # closed: the list stays short

    groups.nth(2).click()  # a cluster opens...
    expect(groups.nth(2)).to_have_attribute("aria-expanded", "true")
    expect(menu.locator("[data-add]")).to_have_count(
        7
    )  # the agent tools: GitHub MCP, the OpenArtifact MCP Tool (ADR-079) and the Hand Over Tool (ADR-080) joined
    groups.nth(6).click()  # ...and the one before closes: one at a time
    expect(groups.nth(2)).to_have_attribute("aria-expanded", "false")
    expect(menu.locator("[data-add]")).to_have_text(["If", "Switch", "Timer"])
    groups.nth(6).click()
    expect(menu.locator("[data-add]")).to_have_count(0)

    page.locator(".ge-add__search").fill(
        "git"
    )  # the search looks at the nodes, as one list with their cluster
    expect(menu.locator("[data-add]")).to_have_text(
        ["GitHub MCPAgent tools", "GitHubApps and data"]
    )  # the search reaches the new GitHub MCP tool too
    expect(groups).to_have_count(0)
    page.locator(".ge-add__search").fill("tool")
    expect(menu.locator("[data-add]")).to_have_count(
        7
    )  # by their names (GitHub MCP, the OpenArtifact MCP Tool and the Hand Over Tool are tools too)
    page.locator(".ge-add__search").fill("flow")  # a cluster's name is no search term
    expect(menu.locator(".ge-add__empty")).to_be_visible()
    page.locator(".ge-add__search").fill("nothing like this")
    expect(menu.locator(".ge-add__empty")).to_be_visible()
    page.locator(".ge-add__search").fill("timer")
    page.keyboard.press("Enter")  # adds the first match
    expect(page.locator(".ge-node--timer")).to_have_count(1)
    expect(menu).to_be_hidden()
    page.click("[data-add-menu]")  # opened again: a clean list, every cluster closed
    expect(page.locator(".ge-add__search")).to_have_value("")
    expect(groups).to_have_count(7)  # with Structure, which holds the Guard
    expect(menu.locator("[data-add]")).to_have_count(0)


# ── the bar under a node, its menu and the keys ───────────────────────


def _code_nodes(api: httpx.Client, definition: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = api.get(graph_url(definition)).json()["nodes"]
    return sorted((n for n in nodes if n["kind"] == "code"), key=lambda n: n["name"])


def test_the_bar_under_a_node_edits_deletes_and_opens_the_menu(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _action_with_two_code_nodes(page, base_url, api)
    node = page.locator(".ge-node--code").first
    bar = node.locator(".ge-node-bar")
    expect(bar).to_be_hidden()  # nothing hovered, nothing selected
    node.hover(position={"x": 30, "y": 5})
    expect(bar).to_be_visible()
    box, bar_box = node.bounding_box(), bar.bounding_box()
    assert box and bar_box and bar_box["y"] >= box["y"] + box["height"] - 1  # below the node

    expect(node.get_by_role("button", name="Edit")).to_have_count(
        0
    )  # Edit is a double click, or in the menu
    node.get_by_role("button", name="More actions").click()
    menu = page.get_by_role("menu")
    expect(menu.get_by_role("menuitem")).to_have_text(
        [
            "EditEnter",
            "RenameF2",
            "CopyCtrl+C",
            "CutCtrl+X",
            "DuplicateCtrl+D",
            "Guard",  # a Code node in an action may be watched (ADR-060)
            "DeleteDel",
        ]
    )
    menu.get_by_role("menuitem", name="Edit").click()  # the same as a double click
    expect(page.locator("#node-modal")).to_be_visible()
    page.keyboard.press("Escape")

    node.hover(position={"x": 30, "y": 5})
    node.get_by_role("button", name="Delete").click()
    page.locator("#confirm-modal").get_by_role("button", name="Delete").click()
    expect(page.locator(".ge-node--code")).to_have_count(1)
    assert len(_code_nodes(api, definition)) == 1


def test_a_right_click_on_a_node_opens_its_menu_and_a_drag_with_it_still_pans(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _action_with_two_code_nodes(page, base_url, api)
    node = page.locator(".ge-node--code").first
    page.mouse.click(*_point_on(node), button="right")
    expect(page.get_by_role("menu").get_by_role("menuitem", name="Duplicate")).to_be_visible()
    expect(node).to_have_class(re.compile(r"is-selected"))
    page.keyboard.press("Escape")
    before = node.bounding_box()
    sx, sy = _point_on(node)
    page.mouse.move(sx, sy)
    page.mouse.down(button="right")
    page.mouse.move(sx + 50, sy + 30, steps=5)
    page.mouse.up(button="right")
    after = node.bounding_box()
    assert before and after and round(after["x"] - before["x"]) == 50  # the view moved
    expect(page.get_by_role("menu")).to_be_hidden()  # and no menu


def _point_on(node: Locator) -> tuple[float, float]:
    box = node.bounding_box()
    assert box is not None
    return box["x"] + 30, box["y"] + 5


def test_duplicate_makes_a_copy_with_a_new_name_and_selects_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _action_with_two_code_nodes(page, base_url, api)
    first = page.locator(".ge-node--code").first
    first.click(position={"x": 30, "y": 5})
    page.keyboard.press("Control+d")
    expect(page.locator(".ge-node--code")).to_have_count(3)
    eventually(lambda: len(_code_nodes(api, definition)), 3)
    names = [n["name"] for n in _code_nodes(api, definition)]
    assert names.count("Execute Command copy") == 1, (
        names
    )  # the two nodes made by the add menu were both "Execute Command"
    expect(page.locator(".ge-node.is-selected")).to_have_count(1)


def test_copy_cut_and_paste_keep_settings_and_make_names_unique(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _action_with_two_code_nodes(page, base_url, api)
    first = page.locator(".ge-node--code").first
    first.dblclick(position={"x": 30, "y": 5})
    page.locator("#node-modal").get_by_label("Code", exact=True).fill("echo copied")
    page.locator("#node-modal").get_by_label("Code", exact=True).blur()
    eventually(
        lambda: any(
            (n["config"] or {}).get("code") == "echo copied" for n in _code_nodes(api, definition)
        ),
        True,
    )
    page.keyboard.press("Escape")
    first.click(position={"x": 30, "y": 5})
    page.keyboard.press("Control+c")
    expect(page.locator("[data-alert]")).to_contain_text("1 node copied")
    page.keyboard.press("Control+v")
    page.keyboard.press("Control+v")
    expect(page.locator(".ge-node--code")).to_have_count(4)
    eventually(lambda: len(_code_nodes(api, definition)), 4)
    codes = [n["config"].get("code") for n in _code_nodes(api, definition)]
    assert codes.count("echo copied") == 3  # the original and two pastes
    copies = [n["name"] for n in _code_nodes(api, definition) if "copy" in n["name"]]
    assert sorted(copies) == [
        "Execute Command copy",
        "Execute Command copy 2",
    ]  # the pastes get names of their own

    page.mouse.move(5, 5)  # the bar of the node under the pointer would lie over the one below it
    page.locator(".ge-node.is-selected").first.click(position={"x": 30, "y": 5})
    page.keyboard.press("Control+x")  # cut: gone at once, still on the clipboard
    expect(page.locator(".ge-node--code")).to_have_count(3)
    page.keyboard.press("Control+v")
    expect(page.locator(".ge-node--code")).to_have_count(4)


def test_a_selection_of_several_is_deleted_together_after_one_question(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _action_with_two_code_nodes(page, base_url, api)
    codes = page.locator(".ge-node--code")
    a, b = codes.nth(0).bounding_box(), codes.nth(1).bounding_box()
    assert a and b
    page.mouse.move(
        max(a["x"] + a["width"], b["x"] + b["width"]) + 12,
        max(a["y"] + a["height"], b["y"] + b["height"]) + 12,
    )
    page.mouse.down()
    page.mouse.move(min(a["x"], b["x"]) - 12, min(a["y"], b["y"]) - 12, steps=6)
    page.mouse.up()
    expect(page.locator(".ge-node.is-selected")).to_have_count(2)
    codes.first.hover(position={"x": 30, "y": 5})
    codes.first.get_by_role("button", name="Delete").click()
    dialog = page.locator("#confirm-modal")
    expect(dialog).to_contain_text("Delete 2 nodes?")
    dialog.get_by_role("button", name="Delete").click()
    expect(page.locator(".ge-node--code")).to_have_count(0)
    assert _code_nodes(api, definition) == []


def test_the_fixed_nodes_offer_edit_but_no_delete_copy_or_cut(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _action_with_two_code_nodes(page, base_url, api)
    trigger = page.locator(".ge-node--trigger")
    trigger.hover(position={"x": 30, "y": 5})
    expect(trigger.get_by_role("button", name="Delete")).to_have_count(0)
    trigger.get_by_role("button", name="More actions").click()
    menu = page.get_by_role("menu")
    for name in ("Copy", "Cut", "Duplicate", "Delete"):
        expect(menu.get_by_role("menuitem", name=name)).to_have_attribute("aria-disabled", "true")
    expect(menu.get_by_role("menuitem", name="Edit")).not_to_have_attribute("aria-disabled", "true")


def test_rename_asks_for_the_name_in_a_small_dialog_and_the_settings_have_one_title(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _action_with_two_code_nodes(page, base_url, api)
    node = page.locator(".ge-node--code").first
    node.hover(position={"x": 30, "y": 5})
    node.get_by_role("button", name="More actions").click()
    page.get_by_role("menuitem", name="Rename").click()
    dialog = page.locator("#new-modal")  # the small name dialog, not the node's settings
    expect(dialog).to_be_visible()
    expect(page.locator("#node-modal")).not_to_be_visible()
    expect(dialog.get_by_label("Name")).to_have_value("Execute Command")
    dialog.get_by_label("Name").fill("Fetch user")
    dialog.get_by_role("button", name="Rename").click()
    expect(dialog).not_to_be_visible()
    expect(page.locator(".ge-node__name", has_text="Fetch user")).to_have_count(1)
    eventually(lambda: any(n["name"] == "Fetch user" for n in _code_nodes(api, definition)), True)

    # F2 does the same for the selected node
    page.locator(".ge-node", has_text="Fetch user").click(position={"x": 30, "y": 5})
    page.keyboard.press("F2")
    expect(dialog.get_by_label("Name")).to_have_value("Fetch user")
    page.keyboard.press("Escape")

    # the settings show the name once, as the title that can be clicked to rename it in place
    page.locator(".ge-node", has_text="Fetch user").dblclick(position={"x": 30, "y": 5})
    settings = page.locator("#node-modal")
    expect(settings.locator("h2:visible")).to_have_count(1)
    expect(settings.locator("h2:visible")).to_have_text("Fetch user")
    settings.locator("h2:visible").click()
    field = settings.locator(".ge-inspector input").first
    field.fill("Fetch the user")
    field.press("Enter")
    expect(page.locator(".ge-node__name", has_text="Fetch the user")).to_have_count(1)
