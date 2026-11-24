"""The timeline of the History tab (ADR-058): changes next to executions, who did it, the quiet trace of a deleted
execution, the filter, live updates; and the layout of the Comments tab."""

from __future__ import annotations

import httpx
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


def test_the_comments_tab_has_its_composer_right_under_the_list_and_only_close_in_the_footer(
    board: Board,
) -> None:
    task = board.create("Item")
    for number in range(2):
        board.api.post(f"/api/tasks/{task['id']}/comments", json={"body": f"comment {number}"})
    dialog = board.open().open_card("Item").open_comments()
    expect(dialog.comment_items).to_have_count(2)
    footer = dialog.root.locator(".task-view .modal__footer")
    expect(footer.locator("button:visible")).to_have_text(
        ["Close"]
    )  # the send button is not repeated here
    send = dialog.comments.locator("[data-comments-send]")
    form = dialog.comments.locator("[data-comments-form]")
    textarea = dialog.comments.locator("[data-comments-input]")
    send.scroll_into_view_if_needed()  # the panel scrolls when list and box together are taller than the dialog
    list_box = dialog.comments.locator("[data-comments-scroll]").bounding_box()
    form_box = form.bounding_box()
    text_box = textarea.bounding_box()
    send_box = send.bounding_box()
    footer_box = footer.bounding_box()
    assert list_box and form_box and text_box and send_box and footer_box
    # no dead space: the box to write in starts right under the last comment
    assert 0 <= form_box["y"] - (list_box["y"] + list_box["height"]) <= 24
    # the send button is under the text box, at its right edge, inside the panel and above the footer
    assert send_box["y"] >= text_box["y"] + text_box["height"]
    assert send_box["x"] + send_box["width"] <= text_box["x"] + text_box["width"] + 1
    assert send_box["x"] > text_box["x"] + text_box["width"] / 2
    assert send_box["y"] + send_box["height"] <= footer_box["y"] + 1
    # nothing overlaps nothing: the list ends above the text box
    assert list_box["y"] + list_box["height"] <= text_box["y"]


def test_many_comments_scroll_in_the_panel_and_the_composer_stays_reachable(board: Board) -> None:
    task = board.create("Item")
    for number in range(30):
        board.api.post(f"/api/tasks/{task['id']}/comments", json={"body": f"comment {number}"})
    dialog = board.open().open_card("Item").open_comments()
    expect(dialog.comment_items).to_have_count(30)
    expect(
        dialog.comments.locator("[data-comments-input]")
    ).to_be_in_viewport()  # opened at the end
    # one scroller only: the list does not scroll inside the panel
    assert (
        dialog.comments.locator("[data-comments-scroll]").evaluate(
            "el => getComputedStyle(el).overflowY"
        )
        == "visible"
    )
