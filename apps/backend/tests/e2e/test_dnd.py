"""Drag & drop with mouse, touch and keyboard; ordering inside and across lanes."""

from __future__ import annotations

from typing import Any

from playwright.sync_api import expect

from tests.e2e.helpers import Board


def _abc(board: Board) -> None:
    """Backlog shows C, B, A (newest first); Done has D; In Progress has E."""
    for title in ("A", "B", "C"):
        board.create(title)
    board.create("D", status="done")
    board.create("E", status="in_progress")
    board.open()


def card(board: Board, lane: str, n: int) -> Any:
    return board.lane(lane).locator(".task-card").nth(n - 1)


def test_dragging_shows_the_card_at_its_new_place_and_abort_restores(board: Board) -> None:
    _abc(board)
    board.drag(card(board, "backlog", 3), card(board, "backlog", 1), edge="top", release=False)
    assert board.titles("backlog") == ["A", "C", "B"]
    board.page.mouse.move(0, 0)  # outside every lane
    board.page.mouse.up()
    expect(board.lane("backlog").locator(".task-card__title")).to_have_text(["C", "B", "A"])
    board.expect_titles("backlog", ["C", "B", "A"])


def test_escape_aborts_a_drag(board: Board) -> None:
    _abc(board)
    board.drag(card(board, "backlog", 3), card(board, "done", 1), release=False)
    board.page.keyboard.press("Escape")
    board.page.mouse.up()
    board.expect_titles("backlog", ["C", "B", "A"])
    board.expect_titles("done", ["D"])


def test_reorder_inside_a_lane(board: Board) -> None:
    _abc(board)
    board.drag(card(board, "backlog", 3), card(board, "backlog", 1), edge="top")
    expect(board.lane("backlog").locator(".task-card__title")).to_have_text(["A", "C", "B"])
    board.expect_titles("backlog", ["A", "C", "B"])
    board.drag(card(board, "backlog", 1), card(board, "backlog", 3), edge="bottom")
    board.expect_titles("backlog", ["C", "B", "A"])


def test_dropping_between_two_cards(board: Board) -> None:
    _abc(board)
    board.drag(card(board, "backlog", 1), card(board, "backlog", 2), edge="bottom")
    expect(board.lane("backlog").locator(".task-card__title")).to_have_text(["B", "C", "A"])
    board.expect_titles("backlog", ["B", "C", "A"])


def test_order_survives_a_reload(board: Board) -> None:
    _abc(board)
    board.drag(card(board, "backlog", 3), card(board, "backlog", 1), edge="top")
    expect(board.lane("backlog").locator(".task-card__title")).to_have_text(["A", "C", "B"])
    board.open()
    assert board.titles("backlog") == ["A", "C", "B"]


def test_drop_into_another_lane_at_a_given_place(board: Board) -> None:
    _abc(board)
    board.drag(card(board, "backlog", 1), card(board, "done", 1), edge="bottom")
    expect(board.lane("done").locator(".task-card__title")).to_have_text(["D", "C"])
    board.expect_titles("done", ["D", "C"])
    expect(board.page.locator(".lane__count")).to_have_text(["2", "1", "2"])
    board.drag(card(board, "backlog", 1), card(board, "done", 1), edge="top")
    board.expect_titles("done", ["B", "D", "C"])


def test_drop_on_a_lane_header_puts_the_card_on_top(board: Board) -> None:
    _abc(board)
    board.drag(card(board, "in_progress", 1), board.lane("done").locator(".lane__title"))
    board.expect_titles("done", ["E", "D"])


def test_drop_into_an_empty_lane(board: Board) -> None:
    board.create("Only")
    board.open()
    board.drag(card(board, "backlog", 1), board.lane("in_progress").locator(".empty-state"))
    expect(board.lane("in_progress").locator(".task-card")).to_have_count(1)
    board.expect_field("Only", "status", "in_progress")


def test_dropping_a_card_on_itself_changes_nothing(board: Board) -> None:
    _abc(board)
    board.drag(card(board, "backlog", 2), card(board, "backlog", 2))
    board.expect_titles("backlog", ["C", "B", "A"])


def test_drag_does_not_open_the_dialog(board: Board) -> None:
    _abc(board)
    board.drag(card(board, "backlog", 1), board.lane("done").locator(".lane__title"))
    expect(board.page.locator("#create-task-modal")).to_be_hidden()


def test_failed_move_is_rolled_back_with_an_error(board: Board) -> None:
    _abc(board)
    board.page.route(
        "**/api/tasks/*",
        lambda route: (
            route.fulfill(status=500, body="{}")
            if route.request.method == "PATCH"
            else route.continue_()
        ),
    )
    board.drag(card(board, "backlog", 3), card(board, "backlog", 1), edge="top")
    expect(board.page.locator("[data-alert]")).to_be_visible()
    assert board.titles("backlog") == ["C", "B", "A"]


def test_keyboard_moves_between_lanes_and_inside_a_lane(board: Board) -> None:
    _abc(board)
    board.card("B").focus()
    board.page.keyboard.press("Alt+ArrowRight")
    expect(board.lane("in_progress").locator(".task-card__title")).to_have_text(["B", "E"])
    expect(board.card("B")).to_be_focused()
    board.page.keyboard.press("Alt+ArrowDown")
    expect(board.lane("in_progress").locator(".task-card__title")).to_have_text(["E", "B"])
    expect(board.card("B")).to_be_focused()
    board.page.keyboard.press("Alt+ArrowUp")
    expect(board.lane("in_progress").locator(".task-card__title")).to_have_text(["B", "E"])
    expect(board.card("B")).to_be_focused()
    board.page.keyboard.press("Alt+ArrowUp")  # already on top: no-op
    board.expect_titles("in_progress", ["B", "E"])
    assert board.card("B").evaluate("el => el === document.activeElement")


def test_enter_opens_and_delete_asks_for_confirmation(board: Board) -> None:
    _abc(board)
    board.card("A").focus()
    board.page.keyboard.press("Enter")
    expect(board.page.locator("#create-task-modal [data-view-title]")).to_have_text("A")
    board.page.keyboard.press("Escape")
    board.card("A").focus()
    board.page.keyboard.press("Delete")
    expect(board.page.locator("#delete-task-modal")).to_be_visible()


# ── touch ─────────────────────────────────────────────────────────────


def _touch(cdp: Any, kind: str, x: float = 0, y: float = 0) -> None:
    points = [] if kind == "touchEnd" else [{"x": x, "y": y, "id": 1}]
    cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})


def test_sideways_swipe_drags_a_card_and_vertical_swipe_does_not(
    browser: Any, base_url: str, api: Any
) -> None:
    context = browser.new_context(
        viewport={"width": 740, "height": 360}, has_touch=True, is_mobile=True
    )
    page = context.new_page()
    cdp = context.new_cdp_session(page)
    try:
        board = Board(page, base_url, api)
        board.create("Swipe me")
        board.open()
        box = board.card("Swipe me").bounding_box()
        target = board.lane("in_progress").locator(".lane__title").bounding_box()
        assert box is not None and target is not None
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

        _touch(cdp, "touchStart", x, y)  # vertical: scrolls, no drag
        for i in range(1, 5):
            _touch(cdp, "touchMove", x, y + 14 * i)
        assert page.locator(".task-card--ghost").count() == 0
        _touch(cdp, "touchEnd")
        board.expect_field("Swipe me", "status", "backlog")

        _touch(cdp, "touchStart", x, y)  # sideways: drag
        for i in range(1, 11):
            _touch(
                cdp,
                "touchMove",
                x + (target["x"] + 30 - x) * i / 10,
                y + (target["y"] + 10 - y) * i / 10,
            )
            page.wait_for_timeout(25)
        assert page.locator(".task-card--ghost").count() == 1
        _touch(cdp, "touchEnd")
        expect(board.lane("in_progress").locator(".task-card")).to_have_count(1)
        board.expect_field("Swipe me", "status", "in_progress")
    finally:
        context.close()
