"""The timeline of the History tab (ADR-058): changes next to executions, who did it, the quiet trace of a deleted
execution, the filter, live updates; and the layout of the Comments tab."""

from __future__ import annotations

import httpx
import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import Board, Dialog, echo_pipeline, executions, start, wait_executions


def _open(board: Board, title: str = "Item") -> Dialog:
    return board.open().open_card(title).open_history()


def test_changes_are_listed_newest_first_with_who_did_them(board: Board) -> None:
    task = board.create("Item")
    board.patch(task, status="done")
    board.patch(task, title="Item renamed")
    dialog = board.open().open_card("Item renamed").open_history()
    texts = dialog.events.locator(".history-event__text").all_inner_texts()
    assert [t.replace("\n", " ") for t in texts] == [
        "You renamed it from “Item” to “Item renamed”",
        "You moved it from Backlog to Done",
        "You created this artifact in Backlog",
    ]
    # who did it is an avatar with the kind as its name, then the name: no kind word is written out
    first = dialog.events.first
    expect(first.locator(".avatar")).to_have_attribute("aria-label", "User")
    expect(first.locator(".history-event__actor")).to_have_text("You")
    expect(dialog.root.locator("[data-history-count]")).to_have_text("3")


def test_a_change_made_elsewhere_appears_while_the_tab_is_open(board: Board) -> None:
    task = board.create("Item")
    dialog = _open(board)
    expect(dialog.events).to_have_count(1)
    board.patch(task, status="done")  # as another client would
    expect(dialog.events).to_have_count(2)
    expect(dialog.events.first).to_contain_text("moved it from Backlog to Done")
    expect(dialog.root.locator("[data-history-count]")).to_have_text("2")


def test_a_drag_to_another_lane_is_a_change_too(board: Board) -> None:
    board.create("Item")
    board.open()
    board.drag(board.card("Item"), board.lane("done"))
    board.expect_field("Item", "status", "done")
    dialog = board.open().open_card("Item").open_history()
    expect(dialog.events.first).to_contain_text("moved it from Backlog to Done")


def test_a_deleted_execution_leaves_a_quiet_line_without_buttons_or_link(
    board: Board, api: httpx.Client
) -> None:
    task = board.create("Item")
    pipeline = echo_pipeline(api)
    start(api, task, pipeline)
    wait_executions(api, task, ["done"])
    dialog = _open(board)
    expect(dialog.rows).to_have_count(1)
    expect(dialog.traces).to_have_count(0)
    # delete it in the dialog
    dialog.rows.first.locator("[data-row-delete]").click()
    board.page.locator("#delete-execution-modal [data-confirm]").click()
    expect(dialog.rows).to_have_count(0)
    expect(dialog.traces).to_have_count(1)  # the trace arrives by the live event
    trace = dialog.traces.first
    expect(trace.locator(".history-chip")).to_have_text("Done")
    expect(trace.locator("[data-row-number]")).to_have_text("#1")
    expect(trace.locator("[data-row-pipeline]")).to_have_text("Echo flow")
    expect(trace.locator("[data-row-duration]")).not_to_be_empty()
    expect(trace).to_have_attribute("title", "The execution was deleted")
    assert trace.locator("button, a").count() == 0  # nothing to press: no open, no delete
    assert executions(api, task) == []
    # it is still there after a reload, from the stored activity
    dialog = _open(board)
    expect(dialog.traces).to_have_count(1)
    expect(dialog.rows).to_have_count(0)


def test_the_filter_shows_everything_only_executions_or_only_changes(
    board: Board, api: httpx.Client
) -> None:
    task = board.create("Item")
    board.patch(task, status="done")
    start(api, task, echo_pipeline(api))
    wait_executions(api, task, ["done"])
    dialog = _open(board)
    items = dialog.history.locator("[data-history-rows] > li")
    visible = dialog.history.locator("[data-history-rows] > li:not([hidden])")
    expect(visible).to_have_count(3)  # the run, the move, the creation
    runs = dialog.history.get_by_role("button", name="Executions", exact=True)
    changes = dialog.history.get_by_role("button", name="Changes")
    runs.click()
    expect(runs).to_have_attribute("aria-pressed", "true")
    expect(visible).to_have_count(1)
    expect(visible.first).to_have_class("history-row")
    changes.click()
    expect(visible).to_have_count(2)
    expect(items).to_have_count(3)  # all still in the page, only hidden
    dialog.history.get_by_role("button", name="All").click()
    expect(visible).to_have_count(3)


def test_the_run_and_the_changes_are_in_one_order_by_time(board: Board, api: httpx.Client) -> None:
    task = board.create("Item")
    start(api, task, echo_pipeline(api))
    wait_executions(api, task, ["done"])
    board.patch(task, status="done")  # after the run
    dialog = _open(board)
    kinds = dialog.history.locator("[data-history-rows] > li").evaluate_all(
        "rows => rows.map(r => r.classList.contains('history-event') ? 'change' : 'run')"
    )
    assert kinds == ["change", "run", "change"]  # the move, the run, the creation


# ── the Comments tab layout ───────────────────────────────────────────


def _comment_layout(board: Board, count: int) -> dict[str, dict[str, float]]:
    """Open the Comments tab of an artifact with ``count`` comments; the boxes of the parts that must not overlap."""
    task = board.create("Item")
    for number in range(count):
        board.api.post(f"/api/tasks/{task['id']}/comments", json={"body": f"comment {number}"})
    dialog = board.open().open_card("Item").open_comments()
    expect(dialog.comment_items).to_have_count(count)
    footer = dialog.root.locator(".task-view .modal__footer")
    parts = {
        "panel": dialog.comments,
        "list": dialog.comments.locator("[data-comments-scroll]"),
        "label": dialog.comments.locator("label[for=comment-input]"),
        "hint": dialog.comments.locator("#comment-hint"),
        "textarea": dialog.comments.locator("[data-comments-input]"),
        "send": dialog.comment_send,
        "close": footer.locator("[data-modal-close]"),
        "footer": footer,
    }
    boxes = {name: part.bounding_box() for name, part in parts.items()}
    assert all(boxes.values()), boxes
    return {name: box for name, box in boxes.items() if box}


def _check_composer_at_the_bottom(boxes: dict[str, dict[str, float]]) -> None:
    panel, label, hint, text = boxes["panel"], boxes["label"], boxes["hint"], boxes["textarea"]
    send, close, foot, lst = boxes["send"], boxes["close"], boxes["footer"], boxes["list"]
    # the label is left and the hint right of it, on the same line
    assert abs(label["y"] - hint["y"]) < label["height"], (label, hint)
    assert hint["x"] > label["x"] + label["width"]
    assert (
        hint["x"] + hint["width"] >= text["x"] + text["width"] - 2
    )  # right-aligned to the text box
    # the text box is below that row, the full width of the tab, and at the bottom of the panel
    assert text["y"] >= label["y"] + label["height"]
    assert text["y"] + text["height"] >= panel["y"] + panel["height"] - 24, (text, panel)
    assert text["width"] >= panel["width"] - 2 * 40
    # the list is above the label and does not overlap the composer
    assert lst["y"] + lst["height"] <= label["y"] + 1
    # the send button is in the footer, right of Close (like Edit on the Details tab), and not under the text box
    assert send["y"] >= foot["y"] and send["y"] + send["height"] <= foot["y"] + foot["height"] + 1
    assert send["x"] >= close["x"] + close["width"]
    assert send["y"] > text["y"] + text["height"]


def test_the_send_button_is_in_the_footer_next_to_close_on_the_comments_tab_only(
    board: Board,
) -> None:
    board.create("Item")
    dialog = board.open().open_card("Item")
    expect(dialog.comment_send).to_be_hidden()  # Details
    dialog.open_comments()
    expect(dialog.comment_send).to_be_visible()
    expect(dialog.root.locator(".task-view .modal__footer").locator("button:visible")).to_have_text(
        ["Close", "Comment"]
    )
    dialog.open_history()
    expect(dialog.comment_send).to_be_hidden()


@pytest.mark.parametrize("count", [0, 2])
def test_the_composer_sits_at_the_bottom_with_no_and_with_two_comments(
    board: Board, count: int
) -> None:
    _check_composer_at_the_bottom(_comment_layout(board, count))


def test_many_comments_scroll_in_the_list_and_the_composer_stays_in_place(board: Board) -> None:
    boxes = _comment_layout(board, 30)
    _check_composer_at_the_bottom(boxes)
    dialog = Dialog(board.page)
    scroll = dialog.comments.locator("[data-comments-scroll]")
    assert scroll.evaluate("el => el.scrollHeight > el.clientHeight"), "the list should scroll"
    assert scroll.evaluate("el => getComputedStyle(el).overflowY") == "auto"
    # one scroller only: the panel itself does not scroll
    assert dialog.comments.evaluate("el => el.scrollHeight <= el.clientHeight + 1")
    expect(dialog.comments.locator("[data-comments-input]")).to_be_in_viewport()
