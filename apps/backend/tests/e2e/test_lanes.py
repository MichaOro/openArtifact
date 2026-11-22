"""Renaming the board lanes in the lane header; the sidebar entry is called Board."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from tests.e2e.helpers import Board


def _rename_dialog(page: Page):  # type: ignore[no-untyped-def]
    return page.locator("#rename-lane-modal")


def _pencil(board: Board, status: str):  # type: ignore[no-untyped-def]
    return board.lane(status).locator("[data-rename-lane]")


def _title(board: Board, status: str):  # type: ignore[no-untyped-def]
    return board.lane(status).locator(".lane__title")


def _rename(board: Board, status: str, title: str) -> None:
    _pencil(board, status).click()
    field = _rename_dialog(board.page).locator("#rename-lane-modal-field-title")
    field.fill(title)
    field.press("Enter")


def test_the_sidebar_entry_is_called_board(board: Board) -> None:
    board.open()
    link = board.page.locator('.sidebar a[href="/"], nav a[href="/"]').first
    expect(link).to_contain_text("Board")
    expect(link).to_have_attribute("aria-current", "page")
    expect(board.page).to_have_title("Board · OpenArtifact")
    expect(board.page.locator(".app-header__title")).to_have_text("Board")
    expect(board.page.get_by_text("Projects")).to_have_count(0)


def test_a_lane_is_renamed_through_the_header_and_stays_after_a_reload(board: Board) -> None:
    board.create("Card", status="in_progress")
    board.open()
    _rename(board, "in_progress", "Review")
    expect(_rename_dialog(board.page)).not_to_be_visible()
    expect(_title(board, "in_progress")).to_have_text("Review", use_inner_text=False)
    expect(_pencil(board, "in_progress")).to_have_attribute("aria-label", "Rename lane Review")
    expect(board.lane("in_progress").locator("[data-create-task]")).to_have_attribute(
        "aria-label", "Add artifact to Review"
    )
    expect(board.page.locator("[data-live-region]")).to_have_text("Lane renamed to Review")
    # the artifact API keeps its status codes
    assert board.stored()["Card"]["status"] == "in_progress"
    board.page.reload()
    expect(_title(board, "in_progress")).to_have_text("Review", use_inner_text=False)


def test_the_dialog_chip_and_the_lane_picker_use_the_new_name(board: Board) -> None:
    board.create("Card")
    board.open()
    _rename(board, "done", "Shipped")
    expect(_title(board, "done")).to_have_text("Shipped", use_inner_text=False)
    dialog = board.open_card("Card")
    expect(dialog.lane_chip).to_have_text("In Backlog")
    dialog.lane_chip.click()
    expect(
        dialog.root.locator("[data-lane-chips] [role=option]").filter(has_text="Shipped")
    ).to_be_visible()
    dialog.lane_chip.click()
    dialog.rail("lane").click()
    expect(dialog.option("Shipped")).to_be_visible()
    dialog.option("Shipped").click()
    expect(dialog.lane_chip).to_have_text("In Shipped")
    board.expect_field("Card", "status", "done")
    expect(board.page.locator("[data-live-region]")).to_have_text("Card moved to Shipped")


def test_a_second_tab_follows_a_rename_and_an_open_dialog_chip_too(board: Board) -> None:
    board.create("Card")
    board.open()
    other = Board(board.page.context.new_page(), board.base_url, board.api)
    other.open()
    dialog = other.open_card("Card")
    expect(dialog.lane_chip).to_have_text("In Backlog")
    board.page.bring_to_front()
    _rename(board, "backlog", "Ideas")
    expect(_title(other, "backlog")).to_have_text("Ideas", use_inner_text=False)
    expect(dialog.lane_chip).to_have_text("In Ideas")
    # a change through the API reaches the open tabs as well
    board.api.put("/api/lanes/backlog", json={"title": None}).raise_for_status()
    expect(_title(board, "backlog")).to_have_text("Backlog", use_inner_text=False)
    expect(dialog.lane_chip).to_have_text("In Backlog")


def test_a_duplicate_name_is_refused_inline_and_keeps_the_typed_text(board: Board) -> None:
    board.open()
    _rename(board, "in_progress", "done")
    dialog = _rename_dialog(board.page)
    expect(dialog).to_be_visible()
    expect(dialog.locator("[data-form-error]")).to_contain_text("already called")
    expect(dialog.locator("#rename-lane-modal-field-title")).to_have_value("done")
    expect(_title(board, "in_progress")).to_have_text("In Progress", use_inner_text=False)


def test_reset_to_default_is_offered_only_for_a_custom_title(board: Board) -> None:
    board.open()
    _pencil(board, "done").click()
    reset = _rename_dialog(board.page).locator("[data-reset]")
    expect(reset).to_be_hidden()
    board.page.keyboard.press("Escape")
    _rename(board, "done", "Shipped")
    expect(_title(board, "done")).to_have_text("Shipped", use_inner_text=False)
    _pencil(board, "done").click()
    expect(reset).to_be_visible()
    reset.click()
    expect(_rename_dialog(board.page)).not_to_be_visible()
    expect(_title(board, "done")).to_have_text("Done", use_inner_text=False)
    expect(board.page.locator("[data-live-region]")).to_have_text("Lane renamed to Done")


def test_keyboard_enter_saves_escape_cancels_and_focus_returns_to_the_pencil(board: Board) -> None:
    board.open()
    pencil = _pencil(board, "backlog")
    pencil.focus()
    board.page.keyboard.press("Enter")
    field = _rename_dialog(board.page).locator("#rename-lane-modal-field-title")
    expect(field).to_be_focused()
    field.fill("Ideas")
    board.page.keyboard.press("Escape")
    expect(_rename_dialog(board.page)).not_to_be_visible()
    expect(pencil).to_be_focused()
    expect(_title(board, "backlog")).to_have_text("Backlog", use_inner_text=False)
    board.page.keyboard.press("Enter")
    field.fill("Ideas")
    board.page.keyboard.press("Enter")
    expect(_title(board, "backlog")).to_have_text("Ideas", use_inner_text=False)
    expect(pencil).to_be_focused()


def test_the_rename_button_is_reachable_at_phone_width(board: Board) -> None:
    board.page.set_viewport_size({"width": 390, "height": 800})
    board.open()
    pencil = _pencil(board, "backlog")
    expect(pencil).to_be_visible()
    _rename(board, "backlog", "A rather long lane name here")
    expect(_title(board, "backlog")).to_have_text(
        "A rather long lane name here", use_inner_text=False
    )
    box = board.lane("backlog").locator(".lane__header").bounding_box()
    assert box is not None
    pencil_box = pencil.bounding_box()
    add_box = board.lane("backlog").locator("[data-create-task]").bounding_box()
    assert pencil_box is not None and add_box is not None
    assert (
        pencil_box["x"] + pencil_box["width"] <= add_box["x"] + 1
    )  # no overlap with the add button
    assert add_box["x"] + add_box["width"] <= box["x"] + box["width"] + 1  # nothing pushed out
    assert re.search(r"Rename lane", pencil.get_attribute("aria-label") or "")
