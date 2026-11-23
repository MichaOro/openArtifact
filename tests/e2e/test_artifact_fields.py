"""Artifact fields in the browser (ADR-044): the board's menu opens the field editor, and the rail of an
artifact shows every field below "Fields" and saves a change at once."""

from __future__ import annotations

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
    editor.locator("[data-add-field]").click()
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
    toggle = rail.locator("[data-field-rail-toggle]")
    expect(toggle).to_be_visible()
    if rail.get_attribute("data-state") == "expanded":  # start from the collapsed rail
        rail.locator("[data-card-nav-toggle]").click()
    toggle.click()  # the icon of the collapsed rail opens it, with the fields
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
    rail.locator("[data-field-rail-toggle]").click()
    if not rail.locator("#card-field-estimate").is_visible():
        rail.locator("[data-field-rail-toggle]").click()
    rail.locator("#card-field-estimate").fill("50")
    rail.locator("#card-field-estimate").press("Enter")
    expect(rail.locator("#card-field-estimate-error")).to_have_text("50 is above the maximum 10")
    assert _fields_of(board, task) == {}


def test_without_fields_the_rail_has_no_fields_entry(board: Board) -> None:
    board.create("Card")
    board.open()
    dialog = board.open_card("Card")
    expect(dialog.root.locator("[data-field-rail]")).to_be_hidden()
