"""The timeline of the History tab (ADR-058): changes next to executions, who did it, the quiet trace of a deleted
execution, the filter, live updates; and the layout of the Comments tab."""

from __future__ import annotations

import re
from typing import cast

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
    # the actor is the bold name inside the sentence; the round marker is the kind of EVENT (no avatar in the timeline)
    first = dialog.events.first
    expect(first.locator(".history-event__actor")).to_have_text("You")
    expect(first.locator(".avatar")).to_have_count(0)
    expect(dialog.events.first.locator(".history-marker")).to_have_attribute(
        "data-tone", "muted"
    )  # a rename
    expect(dialog.events.nth(1).locator(".history-marker")).to_have_attribute(
        "data-tone", "accent"
    )  # a lane move
    expect(dialog.events.nth(2).locator(".history-marker")).to_have_attribute(
        "data-tone", "ok"
    )  # created
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


def test_a_deleted_execution_is_one_slim_line_with_the_deletion_time_and_who_deleted_it(
    board: Board, api: httpx.Client
) -> None:
    task = board.create("Item")
    start(api, task, echo_pipeline(api))
    wait_executions(api, task, ["done"])
    ran_at = executions(api, task)[0]["started_at"]
    dialog = _open(board)
    expect(dialog.rows).to_have_count(1)
    expect(dialog.traces).to_have_count(0)
    # delete it in the dialog
    dialog.rows.first.locator("[data-row-delete]").click()
    board.page.locator("#delete-execution-modal [data-confirm]").click()
    expect(dialog.rows).to_have_count(0)
    expect(dialog.traces).to_have_count(1)  # the trace arrives by the live event
    trace = dialog.traces.first
    expect(trace.locator(".history-event__text")).to_have_text("You deleted execution #1")
    expect(trace.locator(".history-marker")).to_have_attribute("data-tone", "bad")
    expect(trace.locator(".history-event__sub")).to_contain_text(
        "ran "
    )  # when it ran: small, muted
    # nothing else of the run is kept: no pipeline, duration, steps, status, and nothing to press
    for gone in (".history-chip", "[data-row-pipeline]", "[data-row-duration]", "[data-row-meta]"):
        expect(trace.locator(gone)).to_have_count(0)
    assert trace.locator("button, a").count() == 0
    # the time shown is the DELETION time (later than the start of the run), the run's time is in the second line
    shown = trace.locator("time").get_attribute("datetime")
    assert shown and shown > ran_at, (shown, ran_at)
    assert executions(api, task) == []
    # it is still there after a reload, from the stored activity
    dialog = _open(board)
    expect(dialog.traces).to_have_count(1)
    expect(dialog.rows).to_have_count(0)


def test_deleting_several_executions_leaves_one_line_naming_them(
    board: Board, api: httpx.Client
) -> None:
    task = board.create("Item")
    pipeline = echo_pipeline(api)
    for n in range(4):
        start(api, task, pipeline)
        wait_executions(api, task, ["done"] * (n + 1))
    dialog = _open(board)
    dialog.history.locator("[data-history-clear]").click()
    board.page.locator("#delete-execution-modal [data-confirm]").click()
    expect(dialog.rows).to_have_count(0)
    expect(dialog.traces).to_have_count(1)  # one action, one line, not four
    expect(dialog.traces.first.locator(".history-event__text")).to_have_text(
        "You deleted 4 executions (#1\u2013#4)"
    )
    expect(
        dialog.traces.first.locator(".history-event__sub")
    ).to_be_hidden()  # no single "ran" time for a group


def test_the_filter_shows_everything_only_executions_or_only_changes(
    board: Board, api: httpx.Client
) -> None:
    task = board.create("Item")
    board.patch(task, status="done")
    start(api, task, echo_pipeline(api))
    wait_executions(api, task, ["done"])
    board.api.post(
        f"/api/tasks/{task['id']}/comments", json={"body": "a remark"}
    ).raise_for_status()
    dialog = _open(board)
    items = dialog.history.locator("[data-history-rows] > li")
    visible = dialog.history.locator("[data-history-rows] > li:not([hidden])")
    expect(visible).to_have_count(4)  # the run, the move, the creation, the comment
    runs = dialog.history.get_by_role("button", name="Executions", exact=True)
    changes = dialog.history.get_by_role("button", name="Changes")
    comments = dialog.history.get_by_role("button", name="Comments", exact=True)
    runs.click()
    expect(runs).to_have_attribute("aria-pressed", "true")
    expect(visible).to_have_count(1)
    expect(visible.first).to_have_class(re.compile(r"\bhistory-row\b"))
    changes.click()
    expect(visible).to_have_count(2)
    expect(items).to_have_count(4)  # all still in the page, only hidden
    comments.click()
    expect(visible).to_have_count(1)
    expect(visible.first).to_contain_text("a remark")
    dialog.history.get_by_role("button", name="All").click()
    expect(visible).to_have_count(4)


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
    expect(dialog.comment_items).to_have_count(
        min(count, 10)
    )  # the newest ten; the rest is behind a fold
    footer = dialog.root.locator(".task-view .modal__footer")
    parts = {
        "panel": dialog.comments,
        "list": dialog.comments.locator("[data-comments-scroll]"),
        "label": dialog.comments.locator("label[for=comment-input]"),
        "hint": dialog.comments.locator("#comment-hint"),
        "textarea": dialog.comments.locator("[data-comments-input]"),
        "bar": dialog.comments.locator(".md-bar"),  # the formatting bar under the field (ADR-077)
        "send": dialog.comment_send,
        "close": footer.locator("[data-modal-close]"),
        "footer": footer,
    }
    boxes = {name: part.bounding_box() for name, part in parts.items()}
    assert all(boxes.values()), boxes
    return {name: cast(dict[str, float], box) for name, box in boxes.items() if box}


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
    # the composer is the text box with its formatting bar under it (ADR-077): the bar closes the panel, the text box sits right above it
    bar = boxes["bar"]
    assert bar["y"] >= text["y"] + text["height"] - 1, (bar, text)
    assert bar["y"] + bar["height"] >= panel["y"] + panel["height"] - 24, (bar, panel)
    assert text["y"] + text["height"] >= bar["y"] - 24, (
        text,
        bar,
    )  # right above the bar: a gap of one space step
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


# ── the fold, comments in the timeline and the jump to a comment (ADR-058) ────────────────────


def _renamed(board: Board, times: int) -> str:
    """An artifact with ``times`` renames: ``times + 1`` entries with "created"; returns its final title."""
    task = board.create("T0")
    for number in range(1, times + 1):
        board.patch(task, title=f"T{number}")
    return f"T{times}"


def _commented(board: Board, count: int, title: str = "Item") -> dict[str, object]:
    task = board.create(title)
    for number in range(count):
        board.api.post(
            f"/api/tasks/{task['id']}/comments", json={"body": f"comment {number}"}
        ).raise_for_status()
    return task


def test_a_long_history_shows_the_newest_ten_and_the_creation_and_folds_the_rest(
    board: Board,
) -> None:
    title = _renamed(board, 24)  # 25 entries
    dialog = board.open().open_card(title).open_history()
    expect(dialog.root.locator("[data-history-count]")).to_have_text(
        "25"
    )  # the count stays the total
    expect(dialog.timeline).to_have_count(12)  # ten, the fold row, and "created" at the bottom
    expect(dialog.timeline.first).to_contain_text("renamed it from “T23” to “T24”")  # newest on top
    expect(dialog.timeline.last).to_contain_text(
        "created this artifact"
    )  # the anchor is always there
    expect(dialog.fold).to_have_text("Show 14 older entries")
    # the fold sits between the ten and the anchor
    assert dialog.history.locator("[data-history-rows] > li:not([hidden])").evaluate_all(
        "rows => rows.map(r => r.classList.contains('history-collapse'))"
    ) == [False] * 10 + [True, False]
    dialog.fold.click()
    expect(dialog.timeline).to_have_count(26)  # all 25 and the "Show fewer" row
    expect(dialog.fold).to_have_text("Show fewer")
    expect(dialog.timeline.nth(24)).to_contain_text("created this artifact")
    dialog.fold.click()
    expect(dialog.timeline).to_have_count(12)
    expect(dialog.fold).to_have_text("Show 14 older entries")


def test_ten_entries_or_fewer_have_no_fold(board: Board) -> None:
    title = _renamed(board, 9)  # 10 entries
    dialog = board.open().open_card(title).open_history()
    expect(dialog.timeline).to_have_count(10)
    expect(dialog.fold).to_have_count(0)


def test_a_new_entry_arriving_live_keeps_the_fold_and_does_not_move_the_view(board: Board) -> None:
    title = _renamed(board, 24)
    task = board.stored()[title]
    dialog = board.open().open_card(title).open_history()
    expect(dialog.fold).to_have_text("Show 14 older entries")
    board.patch(task, title="T25")
    expect(dialog.timeline.first).to_contain_text("“T24” to “T25”")
    expect(dialog.fold).to_have_text(
        "Show 15 older entries"
    )  # one more is hidden, the ten stay ten
    expect(dialog.timeline).to_have_count(12)


def test_comments_are_entries_with_their_first_words_and_a_new_one_arrives_live(
    board: Board,
) -> None:
    task = _commented(board, 1)
    dialog = board.open().open_card("Item").open_history()
    expect(dialog.comment_entries).to_have_count(1)
    entry = dialog.comment_entries.first
    expect(entry.locator(".history-event__text")).to_have_text("You commented: “comment 0”")
    expect(entry.locator(".history-marker")).to_have_attribute("data-tone", "accent")
    board.api.post(f"/api/tasks/{task['id']}/comments", json={"body": "x" * 200}).raise_for_status()
    expect(dialog.comment_entries).to_have_count(2)
    long = dialog.comment_entries.first.locator(".history-event__text").inner_text()
    assert long.endswith("…”") and len(long) < 120  # cut at about 80 characters
    expect(dialog.root.locator("[data-history-count]")).to_have_text("3")  # created, two comments


def test_an_entry_of_a_comment_jumps_to_it_expands_the_fold_and_pulses_the_border_three_times(
    board: Board,
) -> None:
    _commented(board, 25)
    dialog = board.open().open_card("Item").open_history()
    dialog.history.get_by_role("button", name="Comments", exact=True).click()
    oldest = dialog.comment_entries.filter(has_text="“comment 0”")
    expect(dialog.timeline).to_have_count(
        11
    )  # the 10 newest comments and the fold ("created" is not in this filter)
    expect(oldest).to_be_hidden()  # under the fold
    dialog.fold.click()
    expect(oldest).to_be_visible()
    # the Comments tab folded its older comments too: the oldest one is not even rendered
    dialog.open_comments()
    expect(dialog.comment_items).to_have_count(10)
    expect(dialog.comments_fold).to_have_text("Show 15 older comments")
    dialog.open_history()
    oldest.locator("[data-event-jump]").click()
    # the tab switched, the list expanded over the comment, scrolled to it, focused it and pulses its border
    expect(dialog.comments).to_be_visible()
    expect(dialog.comment_items).to_have_count(25)
    target = dialog.comment_items.filter(has_text="comment 0").first
    expect(target).to_have_attribute("data-pulse", "")
    style = target.evaluate(
        "el => { const s = getComputedStyle(el); return [s.animationName, s.animationIterationCount, s.animationDuration]; }"
    )
    assert style == ["comment-pulse", "3", "1s"], style
    expect(target).to_be_in_viewport()
    assert target.evaluate("el => document.activeElement === el")  # focus is on the comment
    expect(target).not_to_have_attribute(
        "data-pulse", "", timeout=6000
    )  # and the pulse ends by itself (three pulses of a second)


def _rgba(css: str) -> tuple[int, int, int, float]:
    """The first colour of a computed style as 0-255 channels and alpha (Chromium writes color(srgb r g b / a))."""
    match = re.search(
        r"color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: / ([\d.]+))?\)|rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)",
        css,
    )
    assert match, css
    if match.group(1):
        r, g, b = (round(float(match.group(i)) * 255) for i in (1, 2, 3))
        return r, g, b, float(match.group(4) or 1)
    return int(match.group(5)), int(match.group(6)), int(match.group(7)), float(match.group(8) or 1)


def test_the_filter_buttons_come_in_the_order_all_comments_executions_changes(board: Board) -> None:
    board.create("Item")
    dialog = _open(board)
    names = dialog.history.locator("[data-history-filter] button").all_inner_texts()
    assert names == ["All", "Comments", "Executions", "Changes"], names


def test_the_pulse_is_the_accent_in_the_light_theme_and_the_sand_tone_in_the_dark_one(
    board: Board,
) -> None:
    _commented(board, 2)
    board.page.emulate_media(
        reduced_motion="reduce"
    )  # the highlight is then static and can be read
    dialog = board.open().open_card("Item").open_history()
    colours = {}
    for theme in ("light", "dark"):
        board.page.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
        dialog.open_history()
        dialog.comment_entries.last.locator("[data-event-jump]").click()
        target = dialog.comment_items.filter(has_text="comment 0").first
        expect(target).to_have_attribute("data-pulse", "")
        board.page.wait_for_function(  # the border may still be fading to the highlight
            "el => getComputedStyle(el).borderTopColor.includes('0.67')",
            arg=target.element_handle(),
        )
        colours[theme] = target.evaluate(
            "el => { const s = getComputedStyle(el); return [s.borderTopColor, s.boxShadow]; }"
        )
        expect(target).not_to_have_attribute("data-pulse", "", timeout=4000)
    light_border, light_ring = (_rgba(part) for part in colours["light"])
    dark_border, dark_ring = (_rgba(part) for part in colours["dark"])
    # light: the violet accent (#8050e8); dark: the sand tone (#f0ede5); both paler than before: border 67 %, ring 30 % (it was 45 %)
    assert light_border[:3] == (128, 80, 232) and light_ring[:3] == (128, 80, 232), (
        light_border,
        light_ring,
    )
    assert dark_border[:3] == (240, 237, 229) and dark_ring[:3] == (240, 237, 229), (
        dark_border,
        dark_ring,
    )
    assert light_ring[3] == dark_ring[3] == 0.3 and light_border[3] == dark_border[3] == 0.67


def test_the_jump_holds_a_static_highlight_when_motion_is_reduced(board: Board) -> None:
    _commented(board, 3)
    board.page.emulate_media(reduced_motion="reduce")
    dialog = board.open().open_card("Item").open_history()
    dialog.comment_entries.last.locator("[data-event-jump]").click()
    target = dialog.comment_items.filter(has_text="comment 0").first
    expect(target).to_have_attribute("data-pulse", "")
    style = target.evaluate(
        "el => { const s = getComputedStyle(el); return [s.animationName, s.boxShadow]; }"
    )
    assert style[0] == "none" and style[1] != "none", style  # no animation, a highlight that holds
    expect(target).not_to_have_attribute("data-pulse", "", timeout=4000)


def test_the_comment_entry_can_be_used_with_the_keyboard(board: Board) -> None:
    _commented(board, 1)
    dialog = board.open().open_card("Item").open_history()
    jump = dialog.comment_entries.first.locator("[data-event-jump]")
    jump.focus()
    board.page.keyboard.press("Enter")
    expect(dialog.comments).to_be_visible()
    expect(dialog.comment_items.first).to_have_attribute("data-pulse", "")


def test_the_comments_tab_folds_the_older_comments_and_keeps_the_view_when_they_are_shown(
    board: Board,
) -> None:
    _commented(board, 25)
    dialog = board.open().open_card("Item").open_comments()
    expect(dialog.comment_items).to_have_count(10)
    expect(dialog.comment_items.first).to_contain_text("comment 15")  # the newest ten, oldest first
    expect(dialog.comment_items.last).to_contain_text("comment 24")
    expect(dialog.comments.locator("[data-comments-summary]")).to_have_text(
        "25 comments"
    )  # the total
    expect(dialog.comments_fold).to_have_text("Show 15 older comments")
    dialog.comments_fold.click()
    expect(dialog.comment_items).to_have_count(25)
    expect(dialog.comments_fold).to_have_text("Show fewer")
    dialog.comments_fold.click()
    expect(dialog.comment_items).to_have_count(10)


def test_a_deleted_comment_leaves_one_slim_line_and_its_text_is_nowhere_in_the_history(
    board: Board,
) -> None:
    _commented(board, 1)
    dialog = board.open().open_card("Item").open_comments()
    dialog.comment_items.first.locator("[data-comment-more]").click()
    board.page.get_by_role("menuitem", name="Delete").click()
    board.page.locator("#delete-comment-modal [data-confirm]").click()
    expect(dialog.comment_items).to_have_count(0)
    dialog.open_history()
    expect(dialog.comment_entries).to_have_count(
        1
    )  # the "commented" entry was replaced, not added to
    gone = dialog.comment_entries.first
    expect(gone.locator(".history-event__text")).to_have_text("You deleted a comment")
    expect(gone.locator(".history-marker")).to_have_attribute("data-tone", "bad")
    assert gone.locator("button, a").count() == 0
    assert "comment 0" not in dialog.history.inner_text()  # no trace of the text
