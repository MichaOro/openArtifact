"""Board basics: creating, deleting, counters and the empty state."""

from __future__ import annotations

import re

from playwright.sync_api import expect

from tests.e2e.helpers import Board


def test_empty_board_shows_three_lanes_with_empty_states(board: Board) -> None:
    board.open()
    expect(board.page.locator(".lane__count")).to_have_text(["0", "0", "0"])
    expect(board.page.locator(".empty-state")).to_have_count(3)


def test_create_artifact_in_a_lane(board: Board) -> None:
    board.open()
    board.page.locator('[data-create-task][data-status="in_progress"]').click()
    dialog = board.page.locator("#create-task-modal")
    dialog.locator("#create-task-modal-field-title").fill("Write release notes")
    dialog.locator("#create-task-modal-field-body").fill("Draft")
    dialog.locator("[data-submit]").click()
    expect(board.card("Write release notes")).to_be_visible()
    board.expect_field("Write release notes", "status", "in_progress")
    expect(board.page.locator(".lane__count").nth(1)).to_have_text("1")


def test_title_is_required(board: Board) -> None:
    board.open()
    board.page.locator('[data-create-task][data-status="backlog"]').click()
    board.page.locator("#create-task-modal [data-submit]").click()
    expect(board.page.locator("#create-task-modal-field-title-error")).to_be_visible()
    assert board.stored() == {}


def test_new_artifacts_land_on_top_and_get_increasing_numbers(board: Board) -> None:
    first, second = board.create("First"), board.create("Second")
    assert second["number"] == first["number"] + 1
    board.open()
    assert board.titles("backlog") == ["Second", "First"]


def test_delete_from_the_card_asks_for_confirmation(board: Board) -> None:
    board.create("Doomed")
    board.open()
    board.card("Doomed").locator("[data-delete-task]").click()
    confirm = board.page.locator("#delete-task-modal")
    confirm.locator("[data-cancel]").click()
    assert "Doomed" in board.stored()
    board.card("Doomed").locator("[data-delete-task]").click()
    confirm.locator("[data-confirm]").click()
    expect(board.card("Doomed")).to_have_count(0)
    assert board.stored() == {}


def test_delete_dialog_warns_that_children_lose_their_parent(board: Board) -> None:
    parent = board.create("Parent")
    board.create("Child", parent_id=parent["id"])
    board.open()
    board.card("Parent").locator("[data-delete-task]").click()
    expect(board.page.locator("#delete-task-modal [data-children-note]")).to_be_visible()
    board.page.locator("#delete-task-modal [data-confirm]").click()
    expect(board.card("Parent")).to_have_count(0)
    board.expect_field("Child", "parent_id", None)


def test_an_expired_sign_in_sends_the_browser_to_the_sign_in_page(board: Board) -> None:
    board.page.route(
        "**/api/tasks",
        lambda route: route.fulfill(status=401, json={"detail": "Sign in"}),
    )
    board.page.route(
        "**/login*",
        lambda route: route.fulfill(status=200, body="sign in", content_type="text/html"),
    )
    board.page.goto(board.base_url)
    expect(board.page).to_have_url(re.compile(r"/login\?next=%2F$"))


def test_a_refused_event_stream_is_reported_instead_of_leaving_a_stale_board(board: Board) -> None:
    board.create("Visible")
    board.page.route(
        "**/api/events",
        lambda route: route.fulfill(status=401, json={"detail": "Sign in"}),
    )
    board.open()
    expect(board.page.locator("[data-alert]")).to_contain_text("Live updates stopped")
    expect(board.card("Visible")).to_be_visible()
