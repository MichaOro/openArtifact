"""Markdown in the long texts (ADR-077): the bar under the field of a card's text, of a comment and of the prompts of an agent
(heading, bold, italic, strikethrough, lists, quote, code, code block, link with its popup, Ctrl+B, Ctrl+I and Ctrl+K, Preview), the
formatted text where it is read (headings, quotes, code, tables, links), and old texts that read as they always did. The text is
stored as written: the model and the API get the Markdown unchanged."""

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
    old = "2 * 3 * 4, snake_case_name, a*b*c, a - dash, <b>x</b>"
    task = board.create("Item", body=old)
    _comment(board.api, task, old)
    dialog = board.open().open_card("Item")
    expect(dialog.view_body).to_have_text(old)
    expect(dialog.view_body.locator("strong, em, del, ul, ol, h1, h2, a, b")).to_have_count(0)
    comment = dialog.open_comments().comment_items.first.locator("[data-comment-body]")
    expect(comment).to_have_text(old)
    expect(comment.locator("strong, em, del, ul, ol, h1, h2, a, b")).to_have_count(0)
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


def test_a_list_is_drawn_in_the_card_dialog_and_the_first_words_of_the_card_are_plain_lines(
    board: Board,
) -> None:
    board.create("Item", body="intro\n- one\n  - sub\n- two")
    board.open()
    dialog = board.open_card("Item")
    expect(dialog.view_body.locator("ul ul > li")).to_have_text(["sub"])
    expect(dialog.view_body.locator("li")).to_have_count(3)
    expect(board.card("Item").locator(".task-card__body li")).to_have_count(0)
    expect(board.card("Item").locator(".task-card__body")).to_contain_text("one")
    expect(board.card("Item").locator(".task-card__body")).not_to_contain_text(
        "- one"
    )  # the bullet is not drawn on the board


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


BAR_BUTTONS = (
    "Heading (click again for the next level)",
    "Bold",
    "Italic",
    "Strikethrough",
    "Bulleted list",
    "Numbered list",
    "Quote",
    "Code",
    "Code block",
    "Link (Ctrl+K)",
)


def test_the_same_bar_everywhere_has_one_look(board: Board) -> None:
    board.create("Item", body="x")
    dialog: Dialog = board.open().open_card("Item")
    dialog.open_comments()
    bars = dialog.root.locator(".md-bar")
    expect(bars.first.get_by_role("button")).to_have_count(len(BAR_BUTTONS))
    for name in BAR_BUTTONS:
        expect(bars.first.get_by_role("button", name=name, exact=True)).to_have_attribute(
            "title", name
        )


# ── the widened Markdown ──────────────────────────────────────────────────────────────────────────────────────

# a test text only: nothing of it is in the application
SAMPLE = """# Welcome to my Markdown Parser

This is a **simple example** to demonstrate how _Markdown_ is parsed and rendered.

## Features

- Headings
- Text formatting (**bold**, _italic_)
- Lists
- Links
- `Inline code` and code blocks
- Tables
- Blockquotes

> Good documentation makes great software.

#### Code Block Example

```javascript
function hello() {
  console.log("Hello, Markdown!");
}
```

## Table Example
| Item | Detail |
|------|--------|
| Morning | 08:30 |
| Afternoon | 13:15 |
| Evening | 18:45 |
| Night | 22:00 |"""


def test_the_sample_is_drawn_with_headings_a_list_a_quote_code_and_a_table(board: Board) -> None:
    task = board.create("Item", body=SAMPLE)
    _comment(board.api, task, "see [the docs](https://example.test/a) and https://example.test/b")
    dialog = board.open().open_card("Item")
    body = dialog.view_body
    expect(body.locator("h1")).to_have_text("Welcome to my Markdown Parser")
    expect(body.locator("h2")).to_have_text(["Features", "Table Example"])
    expect(body.locator("h4")).to_have_text("Code Block Example")
    expect(body.locator("ul > li")).to_have_count(7)
    expect(body.locator("p strong")).to_have_text("simple example")
    expect(body.locator("p em")).to_have_text("Markdown")
    expect(body.locator("li code")).to_have_text("Inline code")
    expect(body.locator("blockquote")).to_have_text("Good documentation makes great software.")
    expect(body.locator(".md-code__lang")).to_have_text("javascript")
    expect(body.locator("pre code")).to_have_text(
        'function hello() {\n  console.log("Hello, Markdown!");\n}'
    )
    expect(body.locator("table th")).to_have_text(["Item", "Detail"])
    expect(body.locator("table tbody tr")).to_have_count(4)
    expect(body.locator("table tbody tr").nth(3).locator("td")).to_have_text(["Night", "22:00"])
    sizes = body.evaluate(
        "el => [el.querySelector('h1'), el.querySelector('p')].map(n => parseFloat(getComputedStyle(n).fontSize))"
    )
    assert sizes[0] > sizes[1]  # a heading is bigger than the text
    family = body.locator("pre code").evaluate("el => getComputedStyle(el).fontFamily").lower()
    assert "mono" in family or "menlo" in family or "consolas" in family  # code is monospace
    comment = dialog.open_comments().comment_items.first.locator("[data-comment-body]")
    docs = comment.get_by_role("link", name="the docs")
    expect(docs).to_have_attribute("href", "https://example.test/a")
    expect(docs).to_have_attribute("target", "_blank")
    expect(docs).to_have_attribute("rel", "noopener noreferrer nofollow")
    expect(docs).to_have_attribute("title", "https://example.test/a")
    expect(comment.get_by_role("link", name="https://example.test/b")).to_have_count(1)


def test_a_wide_table_scrolls_inside_the_text_and_does_not_widen_the_window(board: Board) -> None:
    cells = " | ".join(f"column number {n}" for n in range(14))
    board.create("Wide", body=f"| {cells} |\n|{'---|' * 14}\n| {cells} |")
    dialog = board.open().open_card("Wide")
    wrap = dialog.view_body.locator(".md-table")
    expect(wrap).to_be_visible()
    metrics = wrap.evaluate("el => ({scroll: el.scrollWidth, shown: el.clientWidth})")
    assert metrics["scroll"] > metrics["shown"]
    box = dialog.root.bounding_box()
    wrap_box = wrap.bounding_box()
    assert box is not None and wrap_box is not None
    assert wrap_box["x"] + wrap_box["width"] <= box["x"] + box["width"] + 1


def test_the_bar_writes_headings_lists_quotes_and_code(board: Board) -> None:
    board.create("Item")
    dialog = board.open().open_card("Item").open_comments()
    box = dialog.comments.locator("[data-comments-input]")
    bar = dialog.comments.locator(".md-bar")
    heading = bar.get_by_role("button", name="Heading (click again for the next level)", exact=True)
    box.fill("Title")
    box.press("Control+A")
    for expected in ("# Title", "## Title", "### Title", "Title"):
        heading.click()
        expect(box).to_have_value(expected)
    box.fill("one\ntwo")
    box.press("Control+A")
    bar.get_by_role("button", name="Numbered list").click()
    expect(box).to_have_value("1. one\n2. two")
    bar.get_by_role("button", name="Numbered list").click()
    expect(box).to_have_value("one\ntwo")
    bar.get_by_role("button", name="Quote").click()
    expect(box).to_have_value("> one\n> two")
    bar.get_by_role("button", name="Quote").click()
    expect(box).to_have_value("one\ntwo")
    bar.get_by_role("button", name="Code block", exact=True).click()
    expect(box).to_have_value("```\none\ntwo\n```")
    box.press("Control+Z")
    expect(box).to_have_value("one\ntwo")  # undo takes the fence back
    box.fill("run npm test now")
    _select(box, "npm test")
    bar.get_by_role("button", name="Code", exact=True).click()
    expect(box).to_have_value("run `npm test` now")


def test_the_link_button_opens_a_popup_with_two_lines_and_writes_the_link(board: Board) -> None:
    board.create("Item")
    dialog = board.open().open_card("Item").open_comments()
    box = dialog.comments.locator("[data-comments-input]")
    bar = dialog.comments.locator(".md-bar")
    popup = bar.locator(".md-link-popup")
    box.fill("visit the site today")
    _select(box, "the site")
    bar.get_by_role("button", name="Link (Ctrl+K)", exact=True).click()
    expect(popup).to_be_visible()
    text, address = popup.get_by_label("Text"), popup.get_by_label("Address")
    expect(text).to_have_value("the site")  # the selection is prefilled
    expect(address).to_be_focused()
    address.fill("www.example.test/page")
    address.press("Enter")
    expect(popup).to_be_hidden()
    expect(box).to_have_value("visit [the site](https://www.example.test/page) today")
    expect(box).to_be_focused()
    box.press("Control+Z")
    expect(box).to_have_value("visit the site today")  # one undo takes the link back


def test_the_link_popup_checks_the_address_closes_with_escape_and_edits_a_link(
    board: Board,
) -> None:
    board.create("Item")
    dialog = board.open().open_card("Item").open_comments()
    box = dialog.comments.locator("[data-comments-input]")
    bar = dialog.comments.locator(".md-bar")
    popup = bar.locator(".md-link-popup")
    box.fill("a link")
    _select(box, "link")
    box.press("Control+K")  # the shortcut opens it as the button does
    expect(popup).to_be_visible()
    popup.get_by_label("Address").fill("javascript:alert(1)")
    popup.get_by_role("button", name="Insert").click()
    expect(popup.get_by_role("alert")).to_have_text(
        "This is not a web or mail address (http, https or mailto)."
    )
    expect(popup).to_be_visible()
    expect(box).to_have_value("a link")  # nothing was inserted
    popup.get_by_label("Address").fill("")
    popup.get_by_label("Address").press("Enter")
    expect(popup.get_by_role("alert")).to_have_text("Enter an address.")
    popup.get_by_label("Address").press("Escape")
    expect(popup).to_be_hidden()
    expect(box).to_be_focused()
    expect(dialog.root).to_be_visible()  # Escape closed the popup, not the window
    box.fill("see [old](https://old.test) here")
    box.evaluate("el => { el.focus(); el.setSelectionRange(7, 7); }")
    box.press("Control+K")
    expect(popup.get_by_label("Text")).to_have_value("old")
    expect(popup.get_by_label("Address")).to_have_value("https://old.test")
    popup.get_by_label("Text").fill("new")
    popup.get_by_label("Address").fill("https://new.test")
    popup.get_by_role("button", name="Insert").click()
    expect(box).to_have_value("see [new](https://new.test) here")


def test_the_preview_shows_blocks_and_links(board: Board) -> None:
    board.create("Item", body="## Head\n\n> quoted\n\n[site](https://example.test)")
    dialog = board.open().open_card("Item").edit()
    dialog.root.get_by_role("switch", name="Preview").click()
    preview = dialog.root.locator("#create-task-modal-form .md-preview")
    expect(preview.locator("h2")).to_have_text("Head")
    expect(preview.locator("blockquote")).to_have_text("quoted")
    expect(preview.get_by_role("link", name="site")).to_have_attribute(
        "href", "https://example.test"
    )


def test_the_card_on_the_board_shows_plain_lines_without_block_marks_or_links(board: Board) -> None:
    board.create(
        "Item",
        body="## Title\n- first **bold**\n> quoted\n| a | b |\n|---|---|\n| 1 | 2 |\n[site](https://example.test)",
    )
    board.open()
    body = board.card("Item").locator(".task-card__body")
    expect(body.locator("h2, ul, li, blockquote, table, a, pre")).to_have_count(0)
    expect(body.locator("strong")).to_have_text("bold")
    for mark in ("##", "- ", "> ", "|---", "](https"):
        expect(body).not_to_contain_text(mark)
    expect(body).to_contain_text("Title")
    expect(body).to_contain_text("site")
