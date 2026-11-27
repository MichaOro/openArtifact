"""The search of the board (ADR-091): the title and the number of a card, never its body."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import Board, eventually

pytestmark = pytest.mark.e2e

SEARCH = "[data-board-search]"
STATUS = "[data-board-search-status]"
WEEK = "Zusammenfassung der Woche"


def _cards(board: Board) -> dict[str, dict[str, Any]]:
    """Twelve cards, 8 in Backlog and 4 in Done. The body of 'Plain' says Zusammenfassung but its title does not.
    The numbers come from the server (the test server counts on across the tests), so they are read, not assumed."""
    made: dict[str, dict[str, Any]] = {}
    titles = [WEEK, "Summary of week 3", "Überblick"] + [f"Card {n}" for n in range(1, 6)]
    for title in titles:
        made[title] = board.create(title, status="backlog")
    for title in ("Plain", "Card 6", "Card 7", "Card 8"):
        made[title] = board.create(
            title, status="done", body="Zusammenfassung in the text" if title == "Plain" else ""
        )
    return made


def _opened(board: Board, cards: int) -> Page:
    """The board with all its cards drawn (the lanes appear before the cards are loaded)."""
    page = board.open().page
    expect(page.locator(".board .task-card")).to_have_count(cards)
    return page


def _visible(page: Page) -> list[str]:
    return page.locator(".board .task-card:visible .task-card__title").all_inner_texts()


def _shows(page: Page, titles: list[str]) -> None:
    """The cards that are shown become `titles` (sorted: the search answers at once, polling covers a slow machine)."""
    eventually(lambda: sorted(_visible(page)), sorted(titles))


def test_a_title_query_keeps_the_cards_whose_title_has_it_and_never_looks_at_the_body(
    board: Board,
) -> None:
    _cards(board)
    page = _opened(board, 12)
    search = page.locator(SEARCH)
    search.fill("zusammen")
    _shows(page, [WEEK])  # 'Plain' has the word in its body only
    expect(page.locator(STATUS)).to_have_text("1 card matches")
    search.fill("ZUSAMMEN woche")
    _shows(page, [WEEK])
    search.fill("ueber")
    _shows(page, ["Überblick"])  # ue finds ü


def test_a_number_finds_the_card_and_a_hash_number_finds_only_the_card(board: Board) -> None:
    made = _cards(board)
    page = _opened(board, 12)
    search = page.locator(SEARCH)
    number = made[WEEK]["number"]
    search.fill(f"#{number}")
    _shows(page, [WEEK])  # the card with that number and nothing else
    search.fill(str(number))
    shown = _visible(page)
    assert WEEK in shown, "the number without a hash finds the card as well"
    assert all(title == WEEK or str(number) in title for title in shown), (
        shown
    )  # and the titles that have the digits in their text
    search.fill("#9999999")
    _shows(page, [])


def test_the_badges_say_how_many_match_and_a_lane_without_a_match_says_so(board: Board) -> None:
    _cards(board)
    page = _opened(board, 12)
    page.locator(SEARCH).fill("zusammen")
    backlog = board.lane("backlog")
    done = board.lane("done")
    expect(backlog.locator(".lane__count")).to_have_text("1/8")
    expect(done.locator(".lane__count")).to_have_text("0/4")
    expect(backlog.locator("[data-lane-nomatch]")).to_be_hidden()
    expect(done.locator("[data-lane-nomatch]")).to_be_visible()
    expect(done.locator("[data-lane-nomatch]")).to_have_text("No matching cards")
    expect(done.locator(".task-card:visible")).to_have_count(0)
    # a lane that has no cards at all keeps the look of an empty lane, not 'no match'
    assert board.api.post("/api/lanes", json={"title": "Later"}).status_code == 201
    page.reload()
    expect(page.locator(".lane")).to_have_count(4)
    expect(board.lane("later").locator("[data-lane-nomatch]")).to_be_hidden()
    expect(board.lane("later").locator(".empty-state")).to_be_visible()


def test_the_clear_button_and_escape_bring_everything_back_and_the_query_is_in_the_address(
    board: Board,
) -> None:
    _cards(board)
    page = _opened(board, 12)
    search = page.locator(SEARCH)
    clear = page.locator("[data-board-search-clear]")
    expect(clear).to_be_hidden()
    search.fill("summary")
    assert "q=summary" in page.url
    expect(clear).to_be_visible()
    clear.click()
    expect(search).to_have_value("")
    assert "q=" not in page.url
    expect(page.locator(".board .task-card:visible")).to_have_count(12)
    search.fill("summary")
    search.press("Escape")
    expect(search).to_have_value("")
    expect(page.locator(".board .task-card:visible")).to_have_count(12)
    expect(page.locator(STATUS)).to_have_text("")
    expect(board.lane("backlog").locator(".lane__count")).to_have_text("8")


def test_a_reload_and_a_link_keep_the_query(board: Board) -> None:
    _cards(board)
    page = _opened(board, 12)
    page.locator(SEARCH).fill("woche")
    page.reload()
    expect(page.locator(SEARCH)).to_have_value("woche")
    expect(page.locator(".board .task-card")).to_have_count(12)
    expect(page.locator(".board .task-card:visible")).to_have_count(1)
    page.goto(f"{board.base_url}/?q=%239999999")  # a link with a query that nothing has
    expect(page.locator(SEARCH)).to_have_value("#9999999")
    expect(page.locator(".board .task-card")).to_have_count(12)
    expect(page.locator(".board .task-card:visible")).to_have_count(0)


def test_a_card_made_while_a_query_is_on_stays_shown_until_the_query_changes(board: Board) -> None:
    _cards(board)
    page = _opened(board, 12)
    search = page.locator(SEARCH)
    search.fill("zusammen")
    page.locator('[data-create-task][data-status="backlog"]').click()
    page.locator("#create-task-modal-field-title").fill("Brand new")
    page.locator("#create-task-modal [data-submit]").click()
    expect(board.card("Brand new")).to_be_visible()
    search.fill("zusammen ")  # typed again: the card made by hand no longer stays
    expect(board.card("Brand new")).to_be_hidden()


def test_a_card_that_arrives_or_changes_follows_the_query(board: Board) -> None:
    _cards(board)
    page = _opened(board, 12)
    page.locator(SEARCH).fill("zusammen")
    board.create("Zusammenfassung neu")  # another client makes a card that matches
    expect(board.card("Zusammenfassung neu")).to_be_visible()
    other = board.create("Something else")
    expect(page.locator(".board .task-card")).to_have_count(14)
    expect(board.card("Something else")).to_be_hidden()
    expect(page.locator(STATUS)).to_have_text("2 cards match")
    board.patch(other, title="Zusammenfassung zwei")  # a title that turns into a match
    expect(board.card("Zusammenfassung zwei")).to_be_visible()
    expect(page.locator(STATUS)).to_have_text("3 cards match")


def test_a_card_can_be_reordered_and_dragged_to_another_lane_under_a_query(board: Board) -> None:
    for title in ("Alpha one", "Beta", "Alpha two", "Gamma", "Alpha three"):
        board.create(
            title
        )  # the lane shows the newest first: Alpha three, Gamma, Alpha two, Beta, Alpha one
    page = _opened(board, 5)
    page.locator(SEARCH).fill("alpha")
    eventually(lambda: _visible(page), ["Alpha three", "Alpha two", "Alpha one"])
    board.expect_titles("backlog", ["Alpha three", "Gamma", "Alpha two", "Beta", "Alpha one"])
    # the last one goes above the first: it passes the hidden cards and the order stays right for them
    board.drag(board.card("Alpha one"), board.card("Alpha three"), edge="top")
    board.expect_titles("backlog", ["Alpha one", "Alpha three", "Gamma", "Alpha two", "Beta"])
    # to another lane
    board.drag(board.card("Alpha two"), board.lane("done"))
    board.expect_field("Alpha two", "status", "done")
    page.locator("[data-board-search-clear]").click()
    assert board.stored_titles("backlog") == ["Alpha one", "Alpha three", "Gamma", "Beta"]


def test_the_keyboard_reorder_skips_the_cards_the_query_hides(board: Board) -> None:
    for title in ("Alpha one", "Beta", "Alpha two"):
        board.create(title)  # shown as: Alpha two, Beta, Alpha one
    page = _opened(board, 3)
    page.locator(SEARCH).fill("alpha")
    board.card("Alpha one").focus()
    page.keyboard.press(
        "Alt+ArrowUp"
    )  # one visible place up: over 'Beta', which is hidden, and over 'Alpha two'
    board.expect_titles("backlog", ["Alpha one", "Alpha two", "Beta"])


def test_a_card_that_loses_its_place_to_the_query_gives_the_focus_to_the_field(
    board: Board,
) -> None:
    for title in ("Alpha one", "Beta"):
        board.create(title)
    page = _opened(board, 2)
    page.locator(SEARCH).fill("alpha")
    board.card("Alpha one").focus()
    board.patch(
        board.stored()["Alpha one"], title="Gamma"
    )  # another client renames the focused card: it no longer matches
    expect(page.locator(SEARCH)).to_be_focused()


def test_the_slash_key_focuses_the_field_and_not_while_typing_elsewhere(board: Board) -> None:
    board.create("Alpha one")
    page = _opened(board, 1)
    page.locator("body").click(position={"x": 5, "y": 400})
    page.keyboard.press("/")
    expect(page.locator(SEARCH)).to_be_focused()
    page.locator(SEARCH).fill("")
    page.locator('[data-create-task][data-status="backlog"]').click()
    page.locator("#create-task-modal-field-title").fill("a/b")
    expect(page.locator("#create-task-modal-field-title")).to_have_value("a/b")
    expect(page.locator(SEARCH)).not_to_be_focused()


def test_the_field_is_hidden_with_the_archive_and_comes_back(board: Board) -> None:
    board.create("Alpha one")
    page = _opened(board, 1)
    expect(page.locator("[data-board-search-box]")).to_be_visible()
    page.locator("[data-board-menu]").click()
    page.get_by_role("menuitem", name="Show archive").click()
    expect(page.locator("[data-board-search-box]")).to_be_hidden()
    page.locator("[data-board-menu]").click()
    page.get_by_role("menuitem", name="Hide archive").click()
    expect(page.locator("[data-board-search-box]")).to_be_visible()
