"""The language switch (ADR-056): choosing German translates the page, the choice survives a reload and other pages, a text
German does not have yet stays English, and the comments tab speaks the language too."""

from __future__ import annotations

from playwright.sync_api import expect

from tests.e2e.helpers import Board


def _choose(board: Board, name: str) -> None:
    board.page.get_by_role("button", name="Language", exact=True).or_(
        board.page.get_by_role("button", name="Sprache", exact=True)
    ).click()
    board.page.get_by_role("menuitem", name=name).click()
    board.page.wait_for_load_state()


def test_choosing_german_translates_the_page_and_the_choice_survives_a_reload(board: Board) -> None:
    board.create("Item")
    page = board.open().page
    expect(page.locator("html")).to_have_attribute("lang", "en")
    expect(page.get_by_role("button", name="Add lane")).to_be_visible()
    _choose(board, "Deutsch")
    expect(page.locator("html")).to_have_attribute("lang", "de")
    expect(page.get_by_role("button", name="Spalte hinzufügen")).to_be_visible()
    expect(page.get_by_role("link", name="Ausführungen")).to_be_visible()
    page.reload()
    expect(page.locator("html")).to_have_attribute("lang", "de")
    expect(page.get_by_role("button", name="Spalte hinzufügen")).to_be_visible()


def test_german_reaches_the_dialogs_the_comments_tab_and_the_settings_pages(
    board: Board,
) -> None:
    board.create("Item")
    page = board.open().page
    _choose(board, "Deutsch")
    dialog = board.open_card("Item")
    expect(dialog.tab("comments")).to_have_text("Kommentare")
    dialog.open_comments()
    expect(dialog.comments.locator("[data-comments-empty]")).to_have_text(
        "Noch keine Kommentare. Schreibe unten den ersten."
    )
    dialog.write_comment("Hallo")
    expect(dialog.comment_items).to_have_count(1)
    expect(dialog.comment_items.first.locator(".avatar")).to_have_attribute(
        "aria-label", "Benutzer"
    )
    # German is complete: a settings page is German to the last button (the English fallback for a missing text is
    # tested with a German that has gaps made on purpose, in tests/test_i18n.py)
    page.goto(board.base_url + "/settings/credentials")
    expect(page.locator("html")).to_have_attribute("lang", "de")
    expect(page.get_by_role("button", name="Neues Token")).to_be_visible()
    expect(page.get_by_role("button", name="New token")).to_have_count(0)
    expect(page.get_by_role("heading", name="Zugangsdaten")).to_be_visible()


def test_the_language_can_be_changed_back(board: Board) -> None:
    page = board.open().page
    _choose(board, "Deutsch")
    expect(page.locator("html")).to_have_attribute("lang", "de")
    _choose(board, "English")
    expect(page.locator("html")).to_have_attribute("lang", "en")
    expect(page.get_by_role("button", name="Add lane")).to_be_visible()
