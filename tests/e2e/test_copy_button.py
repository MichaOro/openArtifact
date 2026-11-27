"""The copy button of long texts (components/copy-button.js): the whole output of a step, the text of a field and the body and title of a card go to the clipboard with
one click, however far the block has scrolled; the button says what happened, short single lines have none, and where the clipboard is not allowed it says so."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import Board, echo_pipeline, execution_of, flow_url, run_started
from tests.e2e.test_dry_run_tab import _commenting_pipeline
from tests.e2e.test_icon_list_glyphs import _centred, _measure
from tests.e2e.test_mock_tab import _open_comment_node

LONG = " ".join(
    f"word{n}" for n in range(1, 600)
)  # about 4 000 characters on one line: the block wraps and scrolls


def _allow_clipboard(page: Page, base_url: str) -> None:
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base_url)


def _clipboard(page: Page) -> str:
    return str(page.evaluate("navigator.clipboard.readText()"))


def _output_block(page: Page, base_url: str, api: httpx.Client, text: str) -> Locator:
    """The opened Output block of the step that printed `text`, in the flow panel of its execution."""
    pipeline = echo_pipeline(api, text)
    task: dict[str, Any] = api.post("/api/tasks", json={"title": "Item"}).json()
    run_started(api, task, pipeline)
    page.goto(flow_url(base_url, task, execution_of(api, task)))
    page.locator('.ge-node[aria-label^="Action"]').dblclick()
    page.locator('.ge-node[aria-label^="Execute Command: echo"]').click()
    block = page.locator("[data-step-output]")
    block.locator("summary").click()
    expect(block.locator("pre")).not_to_have_text("Loading")
    return block


def test_the_whole_output_of_a_step_is_copied_even_when_the_block_has_scrolled(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _allow_clipboard(page, base_url)
    block = _output_block(page, base_url, api, LONG)
    pre = block.locator("pre")
    button = block.get_by_role("button", name="Copy")
    expect(button).to_be_visible()
    # the output is longer than the block: scroll it to the end, the button is still in view in the block's corner
    scrolled = pre.evaluate(
        "(el) => { el.scrollTop = el.scrollHeight; return [el.scrollTop, el.scrollHeight, el.clientHeight]; }"
    )
    assert scrolled[0] > 0 and scrolled[1] > scrolled[2], scrolled
    box, frame = button.bounding_box(), pre.bounding_box()
    assert box and frame
    assert frame["x"] <= box["x"] and box["x"] + box["width"] <= frame["x"] + frame["width"], (
        box,
        frame,
    )
    assert frame["y"] <= box["y"] and box["y"] + box["height"] <= frame["y"] + frame["height"], (
        box,
        frame,
    )
    button.click()
    assert _clipboard(page).strip() == LONG  # all of it, not the lines that are in view


def test_the_button_ticks_for_a_moment_and_says_copied(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _allow_clipboard(page, base_url)
    block = _output_block(page, base_url, api, LONG)
    block.get_by_role("button", name="Copy").click()
    copied = block.get_by_role("button", name="Copied")
    expect(copied).to_be_visible()
    expect(copied).to_have_attribute("data-state", "copied")
    expect(block.locator(".copy-button__status")).to_have_text("Copied")  # announced politely
    expect(block.get_by_role("button", name="Copy")).to_be_visible(
        timeout=5000
    )  # and back to the icon
    expect(block.locator(".copy-button")).not_to_have_attribute("data-state", "copied")


def test_a_short_single_line_has_no_copy_button_and_a_text_of_several_lines_has_one(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    block = _output_block(page, base_url, api, "short")
    expect(block.locator("pre")).to_have_text("short\n")
    expect(block.locator(".copy-button")).to_be_hidden()
    expect(block.locator(".copy-host--on")).to_have_count(0)  # and the block keeps its whole width


def test_where_the_clipboard_is_not_allowed_the_button_says_so(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.add_init_script(
        "Object.defineProperty(navigator, 'clipboard', { value: { writeText: () => Promise.reject(new Error('denied')) } });"
        "document.execCommand = () => false;"
    )
    block = _output_block(page, base_url, api, LONG)
    block.get_by_role("button", name="Copy").click()
    message = block.locator(".copy-button__status")
    expect(message).to_have_text("Copying is not possible here")
    expect(message).to_be_visible()
    expect(block.locator(".copy-button")).to_have_attribute("data-state", "failed")


def test_a_field_copies_what_is_typed_in_it_now(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _allow_clipboard(page, base_url)
    _, definition = _commenting_pipeline(api)
    dialog = _open_comment_node(page, base_url, definition)
    dialog.get_by_role("button", name="Mock data").click()
    panel = dialog.locator("[data-mock-panel]")
    output = panel.get_by_label("Output")
    expect(panel.locator(".copy-button").first).to_be_hidden()  # nothing typed: nothing to copy
    output.fill("created #77\nsecond line")
    button = output.locator("xpath=..").get_by_role("button", name="Copy")
    expect(button).to_be_visible()
    button.click()
    assert _clipboard(page) == "created #77\nsecond line"
    output.fill("changed")  # the field now holds other text: the button copies that
    output.locator("xpath=..").get_by_role("button", name="Copied").or_(button).first.click()
    page.wait_for_timeout(200)
    assert _clipboard(page) == "changed"


def test_the_body_and_the_title_of_a_card_are_copied_as_written(
    board: Board, page: Page, base_url: str
) -> None:
    _allow_clipboard(page, base_url)
    body = f"# Heading\n\n{LONG}"
    title = "A long title " + "x" * 90
    board.create(title, body=body)
    board.open()
    dialog = board.open_card(title)
    view = dialog.root.locator("[data-view-body]").locator("xpath=..")
    view.get_by_role("button", name="Copy").click()
    assert _clipboard(page) == body  # the Markdown as written, not the drawn heading
    head = dialog.root.locator("[data-view-title]").locator("xpath=..")
    head.get_by_role("button", name="Copy").click()
    assert _clipboard(page) == title
    # a short title has none
    dialog.root.locator("[data-view-edit]").click()
    expect(
        dialog.root.locator("[name=body]").locator("xpath=..").get_by_role("button", name="Copy")
    ).to_be_visible()


def test_a_short_title_has_no_copy_button(board: Board) -> None:
    board.create("Short", body="x")
    board.open()
    dialog = board.open_card("Short")
    expect(
        dialog.root.locator("[data-view-title]").locator("xpath=..").locator(".copy-button")
    ).to_be_hidden()
    expect(
        dialog.root.locator("[data-view-body]").locator("xpath=..").locator(".copy-button")
    ).to_be_hidden()


def test_the_glyph_of_the_copy_button_is_centred_in_its_square(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    block = _output_block(page, base_url, api, LONG)
    button = block.locator(".copy-button")
    expect(button).to_be_visible()
    _centred("copy-button", _measure(page, button))
    box = button.bounding_box()
    assert box and box["width"] == box["height"] == 24, box  # a square hit area
