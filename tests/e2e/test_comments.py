"""The Comments tab of the artifact dialog (ADR-055): writing, editing, deleting, who wrote what, live updates and the
link from a run's comment to its execution."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import expect

from tests.e2e.helpers import Board, Dialog, start, wait_executions
from tests.helpers import build_definition, build_pipeline, connect, kind_of, link, node


def _comment(api: httpx.Client, task: dict[str, Any], body: str, **extra: Any) -> dict[str, Any]:
    response = api.post(f"/api/tasks/{task['id']}/comments", json={"body": body, **extra})
    response.raise_for_status()
    made: dict[str, Any] = response.json()
    return made


def _open(board: Board) -> Dialog:
    return board.open().open_card("Item").open_comments()


def test_the_tab_starts_empty_and_a_comment_is_written_with_ctrl_enter(board: Board) -> None:
    task = board.create("Item")
    dialog = _open(board)
    expect(dialog.comments.locator("[data-comments-empty]")).to_be_visible()
    send = dialog.comments.locator("[data-comments-send]")
    expect(send).to_have_attribute("aria-disabled", "true")
    box = dialog.comments.locator("[data-comments-input]")
    box.fill("first line\nsecond line")
    expect(send).to_have_attribute("aria-disabled", "false")
    box.press("Control+Enter")
    expect(dialog.comment_items).to_have_count(1)
    item = dialog.comment_items.first
    expect(item.locator("[data-comment-author]")).to_have_text("You")
    avatar = item.locator(".avatar")
    expect(avatar).to_have_attribute("aria-label", "User")
    expect(avatar).to_have_attribute("data-kind", "user")
    expect(avatar).to_have_text("")  # the kind is the icon, not a word
    expect(item.locator(".history-chip")).to_have_count(0)
    # the line break is kept; the text is not markup
    expect(item.locator("[data-comment-body]")).to_have_text("first line\nsecond line")
    expect(box).to_have_value("")
    expect(dialog.tab("comments").locator("[data-comments-count]")).to_have_text("1")
    stored = board.api.get(f"/api/tasks/{task['id']}/comments").json()
    assert [c["body"] for c in stored] == ["first line\nsecond line"]


def test_html_in_a_comment_is_shown_as_text(board: Board) -> None:
    task = board.create("Item")
    _comment(board.api, task, "<b>bold</b> <img src=x onerror=alert(1)>")
    dialog = _open(board)
    body = dialog.comment_items.first.locator("[data-comment-body]")
    expect(body).to_have_text("<b>bold</b> <img src=x onerror=alert(1)>")
    expect(body.locator("b, img")).to_have_count(0)


def test_comments_are_oldest_first_and_the_view_ends_at_the_newest(
    board: Board,
) -> None:
    task = board.create("Item")
    _comment(board.api, task, "one")
    for i in range(2, 31):
        _comment(board.api, task, f"comment {i}")
    dialog = _open(board)
    expect(dialog.comment_items).to_have_count(30)
    expect(dialog.comment_items.first.locator("[data-comment-body]")).to_have_text("one")
    expect(dialog.comment_items.last.locator("[data-comment-body]")).to_have_text("comment 30")
    board.page.wait_for_function(
        "() => { const e = document.querySelector('[data-comments]');"
        " return e.scrollHeight > e.clientHeight && e.scrollHeight - e.scrollTop - e.clientHeight < 8; }"
    )  # it overflows (30 comments) and ends at the newest one


def test_a_comment_is_edited_in_place_and_says_edited(board: Board) -> None:
    task = board.create("Item")
    _comment(board.api, task, "draft")
    dialog = _open(board)
    item = dialog.comment_items.first
    expect(item.locator("[data-comment-edited]")).to_be_hidden()
    item.locator("[data-comment-more]").click()
    board.page.get_by_role("menuitem", name="Edit").click()
    area = item.locator("[data-comment-edit-input]")
    expect(area).to_be_focused()
    area.fill("final text")
    item.get_by_role("button", name="Save").click()
    expect(item.locator("[data-comment-body]")).to_have_text("final text")
    expect(item.locator("[data-comment-edited]")).to_be_visible()
    assert board.api.get(f"/api/tasks/{task['id']}/comments").json()[0]["body"] == "final text"


def test_escape_cancels_an_edit_without_closing_the_dialog(board: Board) -> None:
    task = board.create("Item")
    _comment(board.api, task, "keep me")
    dialog = _open(board)
    item = dialog.comment_items.first
    item.locator("[data-comment-more]").click()
    board.page.get_by_role("menuitem", name="Edit").click()
    item.locator("[data-comment-edit-input]").fill("changed but not saved")
    board.page.keyboard.press("Escape")
    expect(dialog.root).to_be_visible()
    expect(item.locator("[data-comment-body]")).to_have_text("keep me")


def test_a_comment_is_deleted_after_a_confirmation(board: Board) -> None:
    task = board.create("Item")
    _comment(board.api, task, "gone soon")
    _comment(board.api, task, "stays")
    dialog = _open(board)
    dialog.comment_items.first.locator("[data-comment-more]").click()
    board.page.get_by_role("menuitem", name="Delete").click()
    confirm = board.page.locator("#delete-comment-modal")
    expect(confirm).to_contain_text("the comment of You")
    confirm.locator("[data-confirm]").click()
    expect(dialog.comment_items).to_have_count(1)
    expect(dialog.comment_items.first.locator("[data-comment-body]")).to_have_text("stays")
    assert [c["body"] for c in board.api.get(f"/api/tasks/{task['id']}/comments").json()] == [
        "stays"
    ]


def test_a_comment_from_another_client_appears_changes_and_disappears_live(board: Board) -> None:
    task = board.create("Item")
    dialog = _open(board)
    made = _comment(board.api, task, "from a script")
    expect(dialog.comment_items).to_have_count(1)
    board.api.patch(
        f"/api/tasks/{task['id']}/comments/{made['id']}", json={"body": "changed by a script"}
    ).raise_for_status()
    expect(dialog.comment_items.first.locator("[data-comment-body]")).to_have_text(
        "changed by a script"
    )
    expect(dialog.comment_items.first.locator("[data-comment-edited]")).to_be_visible()
    board.api.delete(f"/api/tasks/{task['id']}/comments/{made['id']}").raise_for_status()
    expect(dialog.comment_items).to_have_count(0)
    expect(dialog.comments.locator("[data-comments-empty]")).to_be_visible()


def test_a_comment_of_another_artifact_does_not_show(board: Board) -> None:
    task, other = board.create("Item"), board.create("Other")
    dialog = _open(board)
    _comment(board.api, other, "not for this one")
    _comment(board.api, task, "for this one")
    expect(dialog.comment_items).to_have_count(1)
    expect(dialog.comment_items.first.locator("[data-comment-body]")).to_have_text("for this one")


def test_a_comment_written_by_a_run_links_to_its_execution(board: Board) -> None:
    task = board.create("Item")
    pipeline = build_pipeline(board.api, stages=1)
    definition = build_definition(board.api, "Say", output=None, fail_enabled=True)
    trigger, output = (
        kind_of(board.api, definition, "trigger"),
        kind_of(board.api, definition, "output"),
    )
    writer = node(
        board.api, definition, "artifact", name="Reviewer",
        config={"operation": "Add comment", "text": "Reviewed by the pipeline"},
    )  # fmt: skip
    connect(board.api, definition, trigger, "out", writer, "in")
    connect(board.api, definition, writer, "pass", output, "pass")
    connect(board.api, definition, writer, "fail", output, "fail")
    link(board.api, pipeline, pipeline["stages"][0][1], definition)
    start(board.api, task, pipeline)
    wait_executions(board.api, task, ["done"])
    dialog = _open(board)
    item = dialog.comment_items.first
    expect(item.locator("[data-comment-author]")).to_have_text("Reviewer")
    expect(item.locator(".avatar")).to_have_attribute("aria-label", "Run")
    expect(item.locator(".avatar")).to_have_attribute("data-kind", "run")
    anchor = item.locator("[data-comment-run]")
    expect(anchor).to_be_visible()
    execution = board.api.get(f"/api/tasks/{task['id']}/executions").json()["items"][0]
    expect(anchor).to_have_attribute(
        "href", f"/artifacts/{task['number']}/executions/{execution['id']}"
    )
