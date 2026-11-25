"""The archive in the browser (ADR-071): the board's menu shows and hides it, it lists only archived cards read only with a panel of
four tabs, "Remove from archive" puts a card back on top of its lane, and a card is archived by hand from the rail of its dialog."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import Board, eventually


@pytest.fixture(autouse=True)
def _empty_archive(board: Board) -> Iterator[None]:
    """The shared clean-up only sees the board's cards and an archived one cannot be deleted (409): take them out first."""
    yield
    for task in board.api.get("/api/tasks?archived=only").json():
        board.api.post(f"/api/tasks/{task['id']}/unarchive").raise_for_status()


def _menu(board: Board, label: str) -> None:
    board.page.locator("[data-board-menu]").click()
    board.page.get_by_role("menuitem", name=label).click()


def _archive(board: Board, task: dict) -> None:
    board.api.post(f"/api/tasks/{task['id']}/archive").raise_for_status()


def test_the_menu_shows_the_archive_with_archived_cards_only_and_hides_it_again(
    board: Board,
) -> None:
    kept = board.create("Stays on the board")
    gone = board.create("Old one")
    board.api.post(
        f"/api/tasks/{gone['id']}/comments", json={"body": "a comment"}
    ).raise_for_status()
    _archive(board, gone)
    board.open()
    expect(board.card("Stays on the board")).to_be_visible()
    expect(board.card("Old one")).to_have_count(0)  # an archived card is not on the board
    _menu(board, "Show archive")
    archive = board.page.locator("[data-archive-view]")
    expect(archive).to_be_visible()
    expect(board.page.locator(".board")).to_be_hidden()  # no lanes in the archive
    tiles = archive.locator(".mg-card")
    expect(tiles).to_have_count(1)
    expect(tiles.first).to_contain_text("Old one")
    expect(tiles.first.locator("[data-edit], .is-danger")).to_have_count(0)  # read only
    tiles.first.click()
    panel = archive.locator(".mg__panel")
    expect(panel.locator(".mg-tabs__tab")).to_have_text(
        ["Details", "Comments", "History", "Context"]
    )
    panel.get_by_role("tab", name="Comments").click()
    expect(panel).to_contain_text("a comment")
    panel.get_by_role("tab", name="History").click()
    expect(panel).to_contain_text("moved it to the archive")
    panel.get_by_role("tab", name="Context").click()
    expect(panel).to_contain_text("Backlog")
    expect(panel).not_to_contain_text("Pipeline")
    _menu(board, "Hide archive")
    expect(archive).to_be_hidden()
    expect(board.card(kept["title"])).to_be_visible()


def test_remove_from_archive_puts_the_card_on_top_of_its_lane(board: Board) -> None:
    board.create("First in lane")
    back = board.create("Coming back")
    _archive(board, back)
    board.open()
    _menu(board, "Show archive")
    archive = board.page.locator("[data-archive-view]")
    archive.locator(".mg-card").first.click()
    archive.get_by_role("button", name="Remove from archive").click()
    expect(archive.locator(".mg-card")).to_have_count(0)
    eventually(lambda: board.api.get(f"/api/tasks/{back['id']}").json()["archived_at"], None)
    _menu(board, "Hide archive")
    expect(board.lane("backlog").locator(".task-card__title").first).to_have_text("Coming back")


def test_a_card_is_archived_by_hand_from_the_rail_of_its_dialog(board: Board) -> None:
    board.create("Archive me")
    board.open()
    dialog = board.open_card("Archive me")
    dialog.root.locator("[data-card-nav-toggle]").click()
    dialog.root.locator('[data-card-action="archive"]').click()
    expect(board.card("Archive me")).to_have_count(0)
    task = next(
        t for t in board.api.get("/api/tasks?archived=only").json() if t["title"] == "Archive me"
    )
    assert task["archived_at"] is not None
