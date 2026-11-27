"""The archive in the browser (ADR-071): the board's menu shows and hides it, it lists only archived cards read only with a panel of
four tabs, "Remove from archive" puts a card back on top of its lane, and a card is archived by hand from the rail of its dialog."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import Board, Dialog, eventually


@pytest.fixture(autouse=True)
def _empty_archive(board: Board) -> Iterator[None]:
    """The shared clean-up only sees the board's cards and an archived one cannot be deleted (409): take them out first."""
    yield
    for task in board.api.get("/api/tasks?archived=only").json():
        board.api.post(f"/api/tasks/{task['id']}/unarchive").raise_for_status()


def _menu(board: Board, label: str) -> None:
    board.page.locator("[data-board-menu]").click()
    board.page.get_by_role("menuitem", name=label).click()


def _archive(board: Board, task: dict[str, Any]) -> None:
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


def test_show_more_opens_the_card_in_its_dialog_read_only_with_remove_from_archive(
    board: Board,
) -> None:
    body = "\n".join(f"line {n} of a long text" for n in range(1, 41))
    card = board.create("Long and old", body=body)
    _archive(board, card)
    board.open()
    _menu(board, "Show archive")
    archive = board.page.locator("[data-archive-view]")
    archive.locator(".mg-card").first.click()
    archive.get_by_role("button", name="Show more").click()
    dialog = Dialog(board.page)
    expect(dialog.root).to_be_visible()
    expect(dialog.view_title).to_have_text("Long and old")
    expect(dialog.view_body).to_contain_text(
        "line 40 of a long text"
    )  # the whole text, not six lines
    # nothing in the window writes: no Edit, no Run, no comment box or Send, no input in the rail, no Archive, no Delete
    for writes in (
        "[data-view-edit]",
        '[data-card-action="run"]',
        "[data-comments-form]",
        "[data-comments-send]",
        '[data-card-action="delete"]',
    ):
        expect(dialog.root.locator(writes)).to_be_hidden()
    expect(
        dialog.root.locator('[data-card-action="archive"]')
    ).to_be_hidden()  # invisible, but its place stays
    for field in ("lane", "parent", "pipeline", "stage", "action"):
        expect(dialog.root.locator(f'[data-card-field="{field}"]')).to_be_disabled()
    dialog.root.locator("[data-card-nav-toggle]").click()
    remove = dialog.root.locator('[data-card-action="unarchive"]')
    expect(remove).to_be_visible()
    expect(remove).to_contain_text("Remove from archive")
    # it sits where Delete sits on a normal card: the last entry of the rail
    last = dialog.root.locator(".card-nav__actions li").last
    assert last.locator('[data-card-action="unarchive"]').count() == 1
    remove.click()
    expect(dialog.root).to_be_hidden()
    expect(archive.locator(".mg-card")).to_have_count(0)
    eventually(lambda: board.api.get(f"/api/tasks/{card['id']}").json()["archived_at"], None)


def test_a_card_of_the_board_keeps_its_edit_and_delete_after_an_archived_one_was_shown(
    board: Board,
) -> None:
    """The read-only mode is opt-in per opening: the next regular card is writable again."""
    old = board.create("Old and read only", body="\n".join(f"row {n}" for n in range(1, 41)))
    board.create("Plain card")
    _archive(board, old)
    board.open()
    _menu(board, "Show archive")
    archive = board.page.locator("[data-archive-view]")
    archive.locator(".mg-card").first.click()
    archive.get_by_role("button", name="Show more").click()
    dialog = Dialog(board.page)
    expect(dialog.root).to_be_visible()
    dialog.root.get_by_role("button", name="Close", exact=True).click()
    _menu(board, "Hide archive")
    dialog = board.open_card("Plain card")
    expect(dialog.root.locator("[data-view-edit]")).to_be_visible()
    dialog.root.locator("[data-card-nav-toggle]").click()
    expect(dialog.root.locator('[data-card-action="delete"]')).to_be_visible()
    expect(dialog.root.locator('[data-card-action="archive"]')).to_be_visible()
    expect(dialog.root.locator('[data-card-action="unarchive"]')).to_be_hidden()
    expect(dialog.root.locator('[data-card-field="lane"]')).to_be_enabled()
