"""Markdown in the long texts (ADR-077): the bar under the field of a card's text, of a comment and of the prompts of an agent
(bold, italic, strikethrough, a bullet list, Ctrl+B and Ctrl+I, Preview), the formatted text where it is read, and old texts that
read as they always did. The text is stored as written: the model and the API get the Markdown unchanged."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import Board, Dialog, eventually


def _select(box: Locator, text: str) -> None:
    """Select `text` in the field, the way a person does with the mouse."""
    box.evaluate(
        "(el, text) => { el.focus(); const at = el.value.indexOf(text); el.setSelectionRange(at, at + text.length); }",
        text,
    )


def _comment(api: httpx.Client, task: dict[str, Any], body: str) -> None:
    api.post(f"/api/tasks/{task['id']}/comments", json={"body": body}).raise_for_status()


def test_the_comment_bar_formats_the_selection_and_the_saved_comment_shows_it(board: Board) -> None:
    board.create("Item")
    dialog = board.open().open_card("Item").open_comments()
    box = dialog.comments.locator("[data-comments-input]")
    bar = dialog.comments.locator(".md-bar")
    expect(bar).to_be_visible()
    box.fill("alpha beta gamma delta")
    _select(box, "alpha")
    bar.get_by_role("button", name="Bold").click()
    expect(box).to_have_value("**alpha** beta gamma delta")
    expect(box).to_be_focused()  # the bar never takes the focus from the field
    _select(box, "beta")
    bar.get_by_role("button", name="Italic").click()
    _select(box, "gamma")
    bar.get_by_role("button", name="Strikethrough").click()
    expect(box).to_have_value("**alpha** *beta* ~~gamma~~ delta")
    box.fill("one\ntwo")
    box.press("Control+A")
    bar.get_by_role("button", name="Bulleted list").click()
    expect(box).to_have_value("- one\n- two")
    box.fill("**bold** *it* ~~gone~~\n- item")
    box.press("Control+Enter")
    item = dialog.comment_items.first.locator("[data-comment-body]")
    expect(item.locator("strong")).to_have_text("bold")
    expect(item.locator("em")).to_have_text("it")
    expect(item.locator("del")).to_have_text("gone")
    expect(item.locator("ul > li")).to_have_text(["item"])
    expect(item).not_to_contain_text("*")
    stored = board.api.get(f"/api/tasks/{board.stored()['Item']['id']}/comments").json()
    assert [c["body"] for c in stored] == ["**bold** *it* ~~gone~~\n- item"]  # stored as written


def test_ctrl_b_and_ctrl_i_format_the_text_of_a_card_and_undo_takes_it_back(board: Board) -> None:
    board.create("Item", body="plain")
    dialog = board.open().open_card("Item").edit()
    box = dialog.body_input
    box.press("Control+A")
    box.press("Control+B")
    expect(box).to_have_value("**plain**")
    box.press("Control+Z")  # the browser's own undo still works: the bar edits through the browser
    expect(box).to_have_value("plain")
    box.press("Control+A")
    box.press("Control+I")
    expect(box).to_have_value("*plain*")
    dialog.save()
    expect(dialog.view_body.locator("em")).to_have_text("plain")
    assert board.stored()["Item"]["body"] == "*plain*"


def test_the_preview_shows_the_text_as_it_reads_and_starts_off(board: Board) -> None:
    board.create("Item", body="**big** news")
    dialog = board.open().open_card("Item").edit()
    box = dialog.body_input
    switch = dialog.root.get_by_role("switch", name="Preview")
    expect(switch).to_have_attribute("aria-checked", "false")
    expect(box).to_be_visible()
    switch.click()
    preview = dialog.root.locator(
        "#create-task-modal-form .md-preview"
    )  # the comments tab has a bar of its own
    expect(preview.locator("strong")).to_have_text("big")
    expect(box).to_be_hidden()
    expect(dialog.root.get_by_role("button", name="Bold")).to_be_disabled()
    switch.click()
    expect(box).to_be_visible()
    expect(box).to_have_value("**big** news")
    expect(preview).to_be_hidden()


def test_old_texts_read_as_they_always_did(board: Board) -> None:
    old = "2 * 3 * 4, snake_case_name, a*b*c, 1. one, a - dash, <b>x</b>"
    task = board.create("Item", body=old)
    _comment(board.api, task, old)
    dialog = board.open().open_card("Item")
    expect(dialog.view_body).to_have_text(old)
    expect(dialog.view_body.locator("strong, em, del, ul, b")).to_have_count(0)
    comment = dialog.open_comments().comment_items.first.locator("[data-comment-body]")
    expect(comment).to_have_text(old)
    expect(comment.locator("strong, em, del, ul, b")).to_have_count(0)
    expect(board.card("Item").locator(".task-card__body")).to_have_text(old)


def test_a_reference_is_still_a_link_inside_the_formatting(board: Board) -> None:
    target = board.create("Target")
    board.create("Source", body=f"**see #{target['number']}** and #{target['number']}")
    board.open()
    dialog = board.open_card("Source")
    link = dialog.view_body.locator("strong a.ref")
    expect(link).to_have_text(f"#{target['number']}")
    expect(link).to_have_attribute("title", "Target")
    expect(dialog.view_body.locator("a.ref")).to_have_count(2)
    card = board.card("Source").locator(".task-card__body")
    expect(card.locator("strong")).to_have_text(f"see #{target['number']}")
    expect(card.locator("a")).to_have_count(0)  # the board's card draws no links, as before


def test_a_list_is_drawn_in_the_card_dialog_and_the_first_words_of_the_card_stay_lines(
    board: Board,
) -> None:
    board.create("Item", body="intro\n- one\n  - sub\n- two")
    board.open()
    dialog = board.open_card("Item")
    expect(dialog.view_body.locator("ul ul > li")).to_have_text(["sub"])
    expect(dialog.view_body.locator("li")).to_have_count(3)
    expect(board.card("Item").locator(".task-card__body li")).to_have_count(0)
    expect(board.card("Item").locator(".task-card__body")).to_contain_text("- one")


def test_the_prompts_of_an_agent_have_the_bar_and_are_saved_as_written(
    board: Board, page: Page, base_url: str
) -> None:
    agent = board.api.post(
        "/api/agents", json={"name": "Writer", "draft": {"user_prompt": "Summarise ${input.text}"}}
    ).json()
    page.goto(f"{base_url}/agents/{agent['id']}")
    editor = page.locator("[data-agent-editor]")
    prompt = editor.get_by_label("User prompt")
    panel = editor.locator("#ag-panel-prompts")
    expect(panel.locator(".md-bar")).to_have_count(2)  # one for each prompt ...
    expect(panel.locator(".md-bar:visible")).to_have_count(
        1
    )  # ... and the system prompt is switched off: its bar is hidden with it
    prompt.fill("Summarise the text now")
    _select(prompt, "text")
    panel.get_by_role("button", name="Bold").click()
    expect(prompt).to_have_value("Summarise the **text** now")
    editor.get_by_role("button", name="Save draft").click()
    eventually(
        lambda: board.api.get(f"/api/agents/{agent['id']}").json()["draft"]["user_prompt"],
        "Summarise the **text** now",
    )


def test_the_same_bar_everywhere_has_one_look(board: Board) -> None:
    board.create("Item", body="x")
    dialog: Dialog = board.open().open_card("Item")
    dialog.open_comments()
    bars = dialog.root.locator(".md-bar")
    expect(bars.first.get_by_role("button")).to_have_count(4)
    for name in ("Bold", "Italic", "Strikethrough", "Bulleted list"):
        expect(bars.first.get_by_role("button", name=name)).to_have_attribute("title", name)
