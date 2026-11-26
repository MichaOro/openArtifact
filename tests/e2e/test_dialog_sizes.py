"""Dialogs are sized by their content (ADR-059): as large as necessary, as small as possible, but cleanly readable.

A dialog shrinks to what it holds (at least 20 rem) and grows to a cap (40 rem). A dialog that needs more declares it with
``data-dialog-size`` and a ``data-dialog-reason``; this file holds the list of those exceptions, so a new one is a decision
that shows up in a diff. On a narrow screen every dialog fits."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.helpers import node

REM = 16  # the pixels of 1 rem at the default font size; the tests read the page's own (see _rem)

#: The declared exceptions: dialog id -> size. Add one only with a reason in the template (data-dialog-reason).
EXCEPTIONS = {
    "create-task-modal": "artifact",
    "fields-modal": "wide",
    "node-modal": "wide",
    "guard-modal": "wide",
    "retention-modal": "wide",
    "card-rules-modal": "wide",
    "version-modal": "wide",
}

#: Measure every dialog of a page: open it, read the panel's width and whether it scrolls sideways, close it.
MEASURE = """
() => [...document.querySelectorAll('dialog.modal')].map((dialog) => {
  dialog.showModal();
  const panel = dialog.querySelector('.modal__panel');
  const box = panel.getBoundingClientRect();
  const row = {
    id: dialog.id,
    size: dialog.dataset.dialogSize || null,
    reason: dialog.dataset.dialogReason || null,
    width: Math.round(box.width),
    left: Math.round(box.left),
    right: Math.round(box.right),
    sideways: panel.scrollWidth > panel.clientWidth + 4 || dialog.scrollWidth > dialog.clientWidth + 1,  // a border or two is no scrolling
    viewport: window.innerWidth,
  };
  dialog.close();
  return row;
})
"""


def _pages(api: httpx.Client) -> list[str]:
    """The pages that carry dialogs: board, executions, lists, credentials, providers, an editor and an agent."""
    pipeline = api.post("/api/pipelines", json={"name": "Sized"}).json()
    node(api, pipeline, "stage", name="Gap Analysis", x=240, y=40)
    created = api.post(
        "/api/agents",
        json={
            "name": f"Sizer {uuid.uuid4().hex[:6]}",
            "draft": {"user_prompt": "Hi ${input.x}", "inputs": [{"name": "x", "required": True}]},
        },
    )
    created.raise_for_status()
    agent = created.json()
    return [
        "/",
        "/executions",
        "/pipelines",
        "/actions",
        "/guards",
        "/agents",
        "/credentials",
        "/providers",
        f"/pipelines/{pipeline['slug']}",
        f"/agents/{agent['id']}",
    ]


def _settle(page: Page) -> None:
    """Stop the opening animation (a dialog scales in), so the widths read are the settled ones."""
    page.add_style_tag(
        content="*, *::before, *::after { animation: none !important; transition: none !important; }"
    )


def _rem(page: Page) -> float:
    return float(
        page.evaluate("() => parseFloat(getComputedStyle(document.documentElement).fontSize)")
    )


def _measure_all(page: Page, base_url: str, api: httpx.Client) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _pages(api):
        page.goto(f"{base_url}{path}")
        page.wait_for_load_state("networkidle")
        _settle(page)
        for row in page.evaluate(MEASURE):
            rows.append({**row, "page": path})
    return rows


def test_the_declared_exceptions_are_exactly_the_list_and_each_has_a_reason(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    rows = _measure_all(page, base_url, api)
    declared = {r["id"]: r["size"] for r in rows if r["size"]}
    assert declared == EXCEPTIONS, (
        "a dialog size exception was added or removed: decide it, then update the list"
    )
    for row in rows:
        if row["size"]:
            assert row["reason"], f"{row['id']} declares {row['size']} without a data-dialog-reason"
    assert len(rows) >= 20, "the pages carry their dialogs"


def test_no_dialog_without_an_exception_is_wider_than_the_cap(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    rows = _measure_all(page, base_url, api)
    rem = _rem(page)
    for row in rows:
        if row["size"] == "artifact":
            continue
        cap = (64 if row["size"] == "wide" else 40) * rem
        assert row["width"] <= cap + 1, (row["page"], row["id"], row["width"], cap)
        if not row["size"]:
            assert row["width"] >= 20 * rem - 1, (row["id"], "readable: at least 20 rem")


def test_a_small_dialog_is_small(page: Page, base_url: str, api: httpx.Client) -> None:
    """The dialogs that only ask a short question are compact: the name dialogs and every confirmation."""
    rows = _measure_all(page, base_url, api)
    confirms = [r for r in rows if "confirm" in r["id"] or r["id"].startswith("delete-")]
    names = [
        r
        for r in rows
        if r["id"] == "name-modal" or r["id"] == "add-lane-modal" or r["id"] == "new-modal"
    ]
    assert confirms and names
    rem = _rem(page)
    for row in confirms + names:
        assert row["width"] < 29 * rem, (row["page"], row["id"], row["width"])


def test_the_action_settings_dialog_is_narrow(page: Page, base_url: str, api: httpx.Client) -> None:
    """The dialog of the owner's screenshot: one select and three buttons is not half a screen wide."""
    pipeline = api.post("/api/pipelines", json={"name": "Narrow"}).json()
    stage = node(api, pipeline, "stage", name="Gap Analysis", x=240, y=40)
    node(api, pipeline, "action", stage_id=stage["id"], x=60, y=48)
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    _settle(page)
    expect(page.locator(".ge-node--action")).to_be_visible()
    page.locator(".ge-node--action").dblclick(
        position={"x": 30, "y": 5}
    )  # no definition yet: its settings open
    panel = page.locator("#node-modal .modal__panel")
    expect(panel).to_be_visible()
    width = panel.bounding_box()["width"]  # type: ignore[index]
    rem = _rem(page)
    assert width < 30 * rem, width
    assert width >= 20 * rem - 1


def test_a_confirmation_with_a_long_text_grows_to_the_cap_and_wraps(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    api.post("/api/tasks", json={"title": "long words wrap " * 12, "body": ""}).raise_for_status()
    page.goto(base_url)
    _settle(page)
    card = page.locator(".task-card").first
    expect(card).to_be_visible()
    card.click()
    page.locator('[data-card-action="delete"]').click()
    panel = page.locator("#delete-task-modal .modal__panel")
    expect(panel).to_be_visible()
    box = panel.bounding_box()
    rem = _rem(page)
    assert box and 40 * rem - 2 <= box["width"] <= 40 * rem + 1, box
    assert not page.evaluate(
        "() => document.querySelector('#delete-task-modal .modal__panel').scrollWidth > document.querySelector('#delete-task-modal .modal__panel').clientWidth + 1"
    )


@pytest.mark.parametrize("width", [360, 320])
def test_every_dialog_fits_a_narrow_screen_without_sideways_scrolling(
    page: Page, base_url: str, api: httpx.Client, width: int
) -> None:
    page.set_viewport_size({"width": width, "height": 700})
    rows = _measure_all(page, base_url, api)
    for row in rows:
        assert row["left"] >= 0 and row["right"] <= width, (
            row["page"],
            row["id"],
            row["left"],
            row["right"],
        )
        assert not row["sideways"], (row["page"], row["id"], "scrolls sideways")
