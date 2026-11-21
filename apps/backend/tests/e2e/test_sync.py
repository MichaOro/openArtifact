"""Live updates over SSE between two open tabs."""

from __future__ import annotations

from playwright.sync_api import expect

from tests.e2e.helpers import Board


def _second_tab(board: Board) -> Board:
    other = Board(board.page.context.new_page(), board.base_url, board.api)
    other.open()
    return other


def test_created_artifact_appears_in_the_other_tab(board: Board) -> None:
    board.open()
    other = _second_tab(board)
    board.page.bring_to_front()
    board.create("Live")
    expect(other.card("Live")).to_be_visible()


def test_move_in_one_tab_shows_in_the_other(board: Board) -> None:
    task = board.create("Mover")
    board.open()
    other = _second_tab(board)
    board.patch(task, status="done")
    expect(other.lane("done").locator(".task-card")).to_have_count(1)
    expect(board.lane("done").locator(".task-card")).to_have_count(1)


def test_edit_and_delete_show_in_the_other_tab(board: Board) -> None:
    task = board.create("Original")
    board.open()
    other = _second_tab(board)
    board.patch(task, title="Renamed")
    expect(other.card("Renamed")).to_be_visible()
    board.api.delete(f"/api/tasks/{task['id']}")
    expect(other.card("Renamed")).to_have_count(0)


def test_open_read_view_follows_changes_made_elsewhere(board: Board) -> None:
    task = board.create("Plan", body="old")
    dialog = board.open().open_card("Plan")
    board.patch(task, body="new body")
    expect(dialog.view_body).to_have_text("new body")


def test_deleting_a_parent_elsewhere_detaches_the_child_on_the_board(board: Board) -> None:
    parent = board.create("Parent")
    board.create("Child", parent_id=parent["id"])
    board.open()
    expect(board.card("Child").locator(".task-card__meta")).to_contain_text("Parent: Parent")
    board.api.delete(f"/api/tasks/{parent['id']}")
    expect(board.card("Child").locator(".task-card__meta")).to_be_hidden()
