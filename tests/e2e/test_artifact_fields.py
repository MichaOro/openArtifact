"""Artifact fields in the browser (ADR-044): the board's menu opens the field editor, and the rail of an
artifact shows every field below "Fields" and saves a change at once."""

from __future__ import annotations

import re
from typing import Any

from playwright.sync_api import expect

from tests.e2e.helpers import Board, eventually

FIELDS = [
    {"name": "size", "label": "Size", "kind": "choice", "options": ["S", "M", "L"], "default": "M"},
    {"name": "estimate", "label": "Estimate", "kind": "number"},
    {"name": "summary", "label": "Summary", "kind": "text"},
    {"name": "urgent", "label": "Urgent", "kind": "boolean"},
]


def _define(board: Board, fields: list[dict[str, Any]]) -> None:
    board.api.put("/api/artifact-fields", json={"fields": fields}).raise_for_status()


def _fields_of(board: Board, task: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = board.api.get(f"/api/tasks/{task['id']}").json()["fields"]
    return result


def test_the_board_menu_opens_the_field_editor_and_a_new_field_is_saved(board: Board) -> None:
    board.open()
    page = board.page
    expect(page.locator(".sidebar a[href='/artifact-types']")).to_have_count(
        0
    )  # not in the navigation
    page.locator("[data-board-menu]").click()
    page.get_by_role("menuitem", name="Artifact fields").click()
    editor = page.locator("#fields-modal")
    expect(editor).to_be_visible()
    expect(editor.locator(".modal__title")).to_have_text("Artifact fields")
    editor.locator("[data-add-first]").click()  # nothing defined yet: the one invitation
    editor.locator("[data-key=label]").fill("Target date")
    expect(editor.locator("[data-key=name]")).to_have_value("target_date")
    expect(editor.locator("[data-key=required]")).to_have_count(0)  # no required setting
    editor.locator("[data-submit]").click()
    expect(editor).to_be_hidden()
    names = [f["name"] for f in board.api.get("/api/artifact-fields").json()["fields"]]
    assert names == ["target_date"]


def test_removing_a_field_with_values_says_what_is_lost(board: Board) -> None:
    _define(board, FIELDS[:1])
    board.create("Card", fields={"size": "L"})
    board.open()
    page = board.page
    page.locator("[data-board-menu]").click()
    page.get_by_role("menuitem", name="Artifact fields").click()
    editor = page.locator("#fields-modal")
    editor.get_by_role("button", name="Remove field").click()
    expect(editor.locator("[data-removal-note]")).to_have_text(
        'Saving removes the values of "Size" (1 artifact).'
    )


def test_the_fields_hang_below_fields_in_the_rail_and_a_change_is_saved_at_once(
    board: Board,
) -> None:
    _define(board, FIELDS)
    task = board.create("Card")
    board.open()
    dialog = board.open_card("Card")
    page = board.page
    rail = dialog.root.locator("[data-card-nav]")
    page.evaluate("() => localStorage.clear()")
    toggle = rail.locator("[data-nav-group-toggle]")
    expect(toggle).to_be_visible()
    if (
        rail.get_attribute("data-state") != "expanded"
    ):  # the open rail: the fields hang below the entry
        rail.locator("[data-card-nav-toggle]").click()
    toggle.click()
    expect(rail).to_have_attribute("data-state", "expanded")
    items = rail.locator(".card-field")
    expect(items).to_have_count(4)
    expect(items.locator(".card-field__label")).to_have_text(
        ["Size", "Estimate", "Summary", "Urgent"]
    )
    expect(rail.locator("#card-field-size")).to_have_value("M")  # the default shows
    # the list is indented under the entry, like the sub-entries of the main navigation
    entry, first = toggle.bounding_box(), items.first.bounding_box()
    assert entry and first and first["x"] > entry["x"] + 12
    rail.locator("#card-field-size").select_option("L")
    rail.locator("#card-field-estimate").fill("8")
    rail.locator("#card-field-estimate").press("Enter")
    rail.locator("#card-field-summary").fill("Ship it")
    rail.locator("#card-field-summary").press("Enter")
    switch = rail.locator("#card-field-urgent")
    expect(switch).to_have_attribute("aria-checked", "false")
    switch.click()
    expect(rail.locator("#card-field-urgent")).to_have_attribute("aria-checked", "true")
    expected = {"size": "L", "estimate": 8, "summary": "Ship it", "urgent": True}
    eventually(lambda: _fields_of(board, task), expected)


def test_a_wrong_value_is_shown_under_its_field(board: Board) -> None:
    _define(board, [{"name": "estimate", "label": "Estimate", "kind": "number", "max_value": 10}])
    task = board.create("Card")
    board.open()
    dialog = board.open_card("Card")
    rail = dialog.root.locator("[data-card-nav]")
    rail.locator("[data-nav-group-toggle]").click()
    popover = dialog.root.locator(".nav-popover")
    popover.locator("#card-field-estimate").fill("50")
    popover.locator("#card-field-estimate").press("Enter")
    expect(popover.locator("#card-field-estimate-error")).to_have_text("50 is above the maximum 10")
    assert _fields_of(board, task) == {}


def _many(count: int) -> list[dict[str, Any]]:
    return [{"name": f"f{i}", "label": f"Field {i}", "kind": "text"} for i in range(count)]


def test_the_dialog_grows_with_its_navigation_and_shrinks_again(board: Board) -> None:
    """The fields below "Fields" make the rail taller: the dialog takes the height instead of scrolling the rail."""
    _define(board, _many(4))
    board.create("Card")
    board.open()
    page = board.page
    page.set_viewport_size({"width": 1400, "height": 1100})
    dialog = board.open_card("Card")
    rail = dialog.root.locator("[data-card-nav]")
    panel = dialog.root.locator(".modal__panel")
    page.evaluate("() => localStorage.clear()")
    if rail.get_attribute("data-state") != "expanded":
        rail.locator("[data-card-nav-toggle]").click()
    closed = panel.bounding_box()
    assert closed
    rail.locator("[data-nav-group-toggle]").click()
    expect(rail.locator(".card-field")).to_have_count(4)
    page.wait_for_timeout(300)
    opened = panel.bounding_box()
    assert opened and opened["height"] > closed["height"] + 20  # it grew
    assert rail.evaluate(
        "e => e.scrollHeight <= e.clientHeight + 1"
    )  # and the rail has no scroll bar
    rail.locator("[data-nav-group-toggle]").click()  # closed again: it shrinks back
    page.wait_for_timeout(300)
    shrunk = panel.bounding_box()
    assert shrunk and abs(shrunk["height"] - closed["height"]) < 2


def test_beyond_the_window_the_dialog_stops_growing_and_the_rail_scrolls(board: Board) -> None:
    _define(board, _many(14))
    board.create("Card")
    board.open()
    page = board.page
    page.set_viewport_size({"width": 1400, "height": 800})
    dialog = board.open_card("Card")
    rail = dialog.root.locator("[data-card-nav]")
    if rail.get_attribute("data-state") != "expanded":
        rail.locator("[data-card-nav-toggle]").click()
    rail.locator("[data-nav-group-toggle]").click()
    page.wait_for_timeout(300)
    box = dialog.root.locator(".modal__panel").bounding_box()
    assert box and box["height"] <= 800 * 0.9 + 2  # never more than the window allows
    assert rail.evaluate("e => e.scrollHeight > e.clientHeight")  # the rest scrolls


def test_with_the_rail_collapsed_the_fields_open_beside_the_icon_like_the_other_entries(
    board: Board,
) -> None:
    _define(board, FIELDS[:2])
    board.create("Card")
    board.open()
    dialog = board.open_card("Card")
    rail = dialog.root.locator("[data-card-nav]")
    page = board.page
    page.evaluate("() => localStorage.clear()")
    if rail.get_attribute("data-state") == "expanded":
        rail.locator("[data-card-nav-toggle]").click()
    toggle = rail.locator("[data-nav-group-toggle]")
    toggle.click()
    popover = dialog.root.locator(".nav-popover")
    expect(popover).to_be_visible()
    expect(rail).to_have_attribute("data-state", "collapsed")  # the rail does not move
    box, entry = popover.bounding_box(), toggle.bounding_box()
    assert (
        box and entry and box["x"] + box["width"] <= entry["x"] + 1
    )  # beside the icon, to its left
    expect(popover.locator(".card-field__label")).to_have_text(["Size", "Estimate"])
    expect(popover.locator(".card-field__reference")).to_have_text(
        ["${card.size}", "${card.estimate}"]
    )
    page.keyboard.press("Escape")  # closes the list, not the dialog
    expect(popover).to_be_hidden()
    expect(dialog.root).to_be_visible()
    toggle.click()
    expect(popover).to_be_visible()
    page.mouse.click(5, 5)  # a click elsewhere closes it, as for the other lists
    expect(popover).to_be_hidden()


def test_a_field_is_offered_as_a_reference_while_a_node_is_edited(board: Board) -> None:
    _define(board, FIELDS[:2])
    pipeline = board.api.post("/api/actions", json={"name": "Refs"}).json()
    from tests.helpers import node as make_node

    make_node(board.api, pipeline, "http", name="Call", config={"url": "http://127.0.0.1:1/"})
    board.page.goto(f"{board.base_url}/actions/{pipeline['slug']}")
    board.page.locator(".ge-node--http").dblclick(
        position={"x": 30, "y": 5}
    )  # a double click opens the settings, one click only selects
    url = board.page.get_by_label("URL")
    url.click()
    board.page.wait_for_timeout(500)  # the fields are fetched when the field gets focus
    url.fill("http://127.0.0.1:1/")
    url.press_sequentially("${card.si")  # the built-ins come first (ADR-064): narrow to the field
    options = board.page.locator("[role=listbox] [role=option]")
    expect(options.first).to_contain_text("card.size")
    expect(options.first).to_contain_text("Size: field of the artifact")
    url.press("Enter")
    expect(url).to_have_value("http://127.0.0.1:1/${card.size}")


def test_without_fields_the_rail_has_no_fields_entry(board: Board) -> None:
    board.create("Card")
    board.open()
    dialog = board.open_card("Card")
    expect(dialog.root.locator("[data-field-rail]")).to_be_hidden()


# ── the two panes, options, multi select, order (ADR-050) ────────────


def _open_editor(board: Board) -> Any:
    page = board.page
    page.locator("[data-board-menu]").click()
    page.get_by_role("menuitem", name="Artifact fields").click()
    editor = page.locator("#fields-modal")
    expect(editor).to_be_visible()
    return editor


def test_the_fields_are_a_list_and_the_chosen_one_is_shown_beside_it(board: Board) -> None:
    _define(board, FIELDS[:2])
    board.open()
    editor = _open_editor(board)
    items = editor.locator("[data-field-list] .af-item")
    expect(items.locator(".af-item__label")).to_have_text(["Size", "Estimate"])
    expect(items.nth(0)).to_have_class(re.compile(r"\bis-selected\b"))
    expect(editor.locator("[data-key=label]")).to_have_value("Size")
    expect(editor.locator("[data-key=name]")).to_have_js_property(
        "readOnly", True
    )  # pipelines read it
    items.nth(1).locator(".af-item__main").click()
    expect(editor.locator("[data-key=label]")).to_have_value("Estimate")
    expect(editor.locator("[data-unsaved]")).to_be_hidden()
    editor.locator("[data-key=label]").fill("Effort")
    expect(items.nth(1).locator(".af-item__label")).to_have_text("Effort")
    expect(editor.locator("[data-unsaved]")).to_be_visible()
    # Cancel with unsaved changes asks first; Keep editing keeps them, Discard throws them away
    editor.locator("[data-cancel]").click()
    expect(editor.locator("[data-discard-confirm]")).to_be_visible()
    editor.locator("[data-discard-keep]").click()
    expect(editor).to_be_visible()
    board.page.keyboard.press("Escape")  # closing asks, too
    expect(editor.locator("[data-discard-confirm]")).to_be_visible()
    editor.locator("[data-discard-go]").click()
    expect(editor).to_be_hidden()
    labels = [f["label"] for f in board.api.get("/api/artifact-fields").json()["fields"]]
    assert labels == ["Size", "Estimate"]  # nothing was saved


def test_a_select_gets_options_that_are_renamed_deleted_and_kept_apart(board: Board) -> None:
    board.open()
    editor = _open_editor(board)
    editor.locator("[data-add-first]").click()
    editor.locator("[data-key=label]").fill("Area")
    editor.locator("[data-key=type]").select_option("single")
    for text in ("Bug", "UI", "API"):
        editor.locator("[data-add-option]").click()
        field = editor.locator(".af-option .inline-name__input").last
        field.fill(text)
        field.press("Enter")
    editor.locator("[data-add-option]").click()
    duplicate = editor.locator(".af-option .inline-name__input").last
    duplicate.fill("bug")
    duplicate.press("Enter")
    expect(editor.locator(".inline-name__error")).to_have_text('"bug" is already an option.')
    duplicate.press("Escape")
    expect(editor.locator(".af-option")).to_have_count(3)  # the empty one went again
    # rename through the menu, delete through the menu
    editor.get_by_role("button", name="Option actions: UI").click()
    board.page.get_by_role("menuitem", name="Rename").click()
    renamed = editor.locator(".af-option .inline-name__input")
    renamed.fill("Frontend")
    renamed.press("Enter")
    editor.get_by_role("button", name="Option actions: API").click()
    board.page.get_by_role("menuitem", name="Delete").click()
    expect(editor.locator(".af-option__text")).to_have_text(["Bug", "Frontend"])
    expect(editor.locator(".af-item__type")).to_have_text("Single select · 2 options")
    editor.locator("[data-submit]").click()
    expect(editor).to_be_hidden()
    (area,) = board.api.get("/api/artifact-fields").json()["fields"]
    assert (area["name"], area["kind"], area["multiple"], area["options"]) == (
        "area",
        "choice",
        False,
        ["Bug", "Frontend"],
    )


def test_a_renamed_option_keeps_the_values_of_the_artifacts(board: Board) -> None:
    _define(board, FIELDS[:1])  # Size: S, M, L
    task = board.create("Card", fields={"size": "M"})
    board.open()
    editor = _open_editor(board)
    editor.get_by_role("button", name="Option actions: M").click()
    board.page.get_by_role("menuitem", name="Rename").click()
    field = editor.locator(".af-option .inline-name__input")
    field.fill("Medium")
    field.press("Enter")
    editor.locator("[data-submit]").click()
    expect(editor).to_be_hidden()
    assert _fields_of(board, task) == {"size": "Medium"}


def test_a_multi_select_holds_several_values_on_the_card(board: Board) -> None:
    _define(
        board,
        [
            {
                "name": "tags",
                "label": "Tags",
                "kind": "choice",
                "multiple": True,
                "options": ["bug", "ui", "api"],
            }
        ],
    )
    task = board.create("Card")
    board.open()
    editor = _open_editor(board)
    expect(editor.locator("[data-key=type]")).to_have_value("multi")
    expect(editor.locator(".af-default-multi input")).to_have_count(3)
    board.page.keyboard.press("Escape")
    dialog = board.open_card("Card")
    rail = dialog.root.locator("[data-card-nav]")
    rail.locator("[data-nav-group-toggle]").click()  # collapsed rail: a popover beside the icon
    popover = dialog.root.locator(".nav-popover")
    expect(popover).to_be_visible()
    popover.get_by_label("bug").check()
    eventually(lambda: _fields_of(board, task), {"tags": ["bug"]})
    popover.get_by_label("api").check()
    eventually(lambda: _fields_of(board, task), {"tags": ["bug", "api"]})


def test_the_order_of_the_fields_is_changed_by_their_grip_and_kept(board: Board) -> None:
    _define(board, FIELDS[:3])
    board.open()
    editor = _open_editor(board)
    labels = editor.locator("[data-field-list] .af-item__label")
    expect(labels).to_have_text(["Size", "Estimate", "Summary"])
    # with the keyboard: the grip of Size, ArrowDown
    editor.get_by_role("button", name="Move Size").focus()
    board.page.keyboard.press("ArrowDown")
    expect(labels).to_have_text(["Estimate", "Size", "Summary"])
    # with the pointer: Summary to the top
    grip = editor.get_by_role("button", name="Move Summary").bounding_box()
    top = editor.locator("[data-field-list] .af-item").first.bounding_box()
    assert grip and top
    mouse = board.page.mouse
    mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
    mouse.down()
    mouse.move(grip["x"] + grip["width"] / 2, top["y"] + 2, steps=12)
    mouse.up()
    expect(labels).to_have_text(["Summary", "Estimate", "Size"])
    # a click on the entry itself still only chooses it
    editor.locator("[data-field-list] .af-item__main").nth(2).click()
    expect(editor.locator("[data-key=label]")).to_have_value("Size")
    editor.locator("[data-submit]").click()
    expect(editor).to_be_hidden()
    names = [f["name"] for f in board.api.get("/api/artifact-fields").json()["fields"]]
    assert names == ["summary", "estimate", "size"]
