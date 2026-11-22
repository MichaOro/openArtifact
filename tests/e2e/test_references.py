"""Artifact numbers, the `#` menu in the body and reference links in the read view."""

from __future__ import annotations

from playwright.sync_api import expect

from tests.e2e.helpers import Board


def test_hash_opens_a_menu_with_the_other_artifacts(board: Board) -> None:
    board.create("Login page")
    board.create("Database schema")
    me = board.create("Write docs", body="see ")
    dialog = board.open().open_card("Write docs").edit()
    dialog.body_input.focus()
    board.page.keyboard.press("End")
    board.page.keyboard.type(" #")
    options = dialog.root.locator(".popover--reference:not([hidden]) [role=option]")
    expect(options).to_have_count(2)  # not the artifact itself
    assert f"#{me['number']}" not in " ".join(options.all_inner_texts())


def test_typing_filters_and_enter_inserts_the_number(board: Board) -> None:
    login = board.create("Login page")
    board.create("Database schema")
    board.create("Write docs", body="start see ")
    dialog = board.open().open_card("Write docs").edit()
    dialog.body_input.focus()
    board.page.keyboard.press("End")
    board.page.keyboard.type(" #da")
    options = dialog.root.locator(".popover--reference:not([hidden]) [role=option]")
    expect(options).to_have_text(
        ["#" + str(board.stored()["Database schema"]["number"]) + "Database schema"]
    )
    board.page.keyboard.press("Backspace")
    board.page.keyboard.press("Backspace")
    board.page.keyboard.type(str(login["number"]))
    board.page.keyboard.press("Enter")
    expect(dialog.body_input).to_have_value(f"start see #{login['number']} ")
    expect(options).to_have_count(0)
    expect(dialog.root).to_be_visible()  # Enter did not submit


def test_escape_closes_only_the_menu(board: Board) -> None:
    board.create("Other")
    board.create("Plan", body="x ")
    dialog = board.open().open_card("Plan").edit()
    dialog.body_input.focus()
    board.page.keyboard.press("End")
    board.page.keyboard.type(" #")
    board.page.keyboard.press("Escape")
    expect(dialog.root.locator(".popover--reference")).to_be_hidden()
    expect(dialog.root).to_be_visible()


def test_a_hash_inside_a_word_opens_no_menu(board: Board) -> None:
    board.create("Other")
    board.create("Plan")
    dialog = board.open().open_card("Plan").edit()
    dialog.body_input.focus()
    board.page.keyboard.type("C#")
    expect(dialog.root.locator(".popover--reference")).to_be_hidden()


def test_references_are_links_in_the_read_view_and_back_returns(board: Board) -> None:
    base = board.create("Base work", body="the foundation")
    board.create("Main task", body=f"Depends on #{base['number']}, ignores #999 and C#3.")
    dialog = board.open().open_card("Main task")
    links = dialog.view_body.locator("a.ref")
    expect(links).to_have_text([f"#{base['number']}"])
    expect(dialog.view_body.locator(".ref--missing")).to_have_text(["#999"])
    links.click()
    expect(dialog.view_title).to_have_text("Base work")
    back = dialog.root.locator("[data-view-back]")
    expect(back).to_be_visible()
    back.click()
    expect(dialog.view_title).to_have_text("Main task")
    expect(back).to_be_hidden()


def test_reference_to_a_deleted_artifact_is_shown_as_missing(board: Board) -> None:
    gone = board.create("Gone")
    board.create("Main task", body=f"see #{gone['number']}")
    board.api.delete(f"/api/tasks/{gone['id']}")
    dialog = board.open().open_card("Main task")
    expect(dialog.view_body.locator("a.ref")).to_have_count(0)
    expect(dialog.view_body.locator(".ref--missing")).to_have_count(1)


def test_a_new_artifact_never_reuses_a_deleted_number(board: Board) -> None:
    first = board.create("First")
    board.api.delete(f"/api/tasks/{first['id']}")
    assert board.create("Second")["number"] > first["number"]
