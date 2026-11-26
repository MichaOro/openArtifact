"""Draft and published versions of guards in the browser (ADR-081): a new guard is a draft, the Versions tab of the Guards page publishes,
shows an earlier version read-only and publishes it again, the mark in the guard window offers Publish and Discard draft in a popup that
sits inside the window, and an attached guard nobody published says that it watches nothing."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.test_guards import ROUND, _attach, _guard, _pipeline, _window

CONFIRM = "#confirm-modal [data-confirm], #confirm-modal [data-submit]"


def _draft(api: httpx.Client, name: str = "Gate") -> dict[str, Any]:
    """A definition that nobody published: the library's own state for a new guard."""
    body = {
        "name": name,
        "trigger": {"type": "event", "events": ["enter"]},
        "when": ROUND,
        "consequence": "pause",
        "description": "first words",
    }
    response = api.post("/api/guards", json=body)
    response.raise_for_status()
    made: dict[str, Any] = response.json()
    return made


def _goto(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/guards")
    expect(page.locator(".mg-card").first).to_be_visible()


def _chips(page: Page) -> Any:
    return page.locator(".mg-card__chips .ge-chip")


def _panel_tab(page: Page, name: str) -> Any:
    panel = page.locator(".mg__panel")
    panel.get_by_role("tab", name=name).click()
    return panel.locator('[role="tabpanel"]:not([hidden])')


def test_a_new_guard_is_a_draft_and_the_versions_tab_publishes_shows_and_publishes_again(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    guard = _draft(api)
    _goto(page, base_url)
    expect(_chips(page).last).to_have_text("Draft")
    page.locator(".mg-card").click()
    versions = _panel_tab(page, "Versions")
    expect(versions).to_contain_text("Nothing is published: this guard watches nothing yet.")
    versions.locator("[data-publish]").click()
    page.locator(CONFIRM).first.click()
    expect(_chips(page).last).to_have_text("v1 published")
    versions = _panel_tab(page, "Versions")
    expect(versions.locator('.mg-version[data-version="1"]')).to_contain_text("In use")

    api.patch(f"/api/guards/{guard['id']}", json={"description": "second words"}).raise_for_status()
    page.reload()
    expect(_chips(page).last).to_have_text("Draft has changes")
    page.locator(".mg-card").click()
    versions = _panel_tab(page, "Versions")
    expect(versions).to_contain_text("The draft differs from the published version 1")
    versions.locator("[data-publish]").click()
    page.locator(CONFIRM).first.click()
    expect(_chips(page).last).to_have_text("v2 published")

    versions = _panel_tab(page, "Versions")
    versions.get_by_role(
        "button", name="Show version 1"
    ).click()  # the Overview shows version 1, read-only
    overview = page.locator('.mg__panel [role="tabpanel"]:not([hidden])')
    expect(overview).to_contain_text("Showing version 1, read-only.")
    expect(overview).to_contain_text("first words")
    expect(overview.locator("[data-open-guard]")).to_have_count(
        0
    )  # only the draft is opened and changed
    overview.locator("[data-back-to-draft]").click()
    expect(page.locator('.mg__panel [role="tabpanel"]:not([hidden])')).to_contain_text(
        "second words"
    )

    versions = _panel_tab(page, "Versions")
    versions.get_by_role("button", name="Publish version 1 again").click()
    page.locator(CONFIRM).first.click()
    expect(_chips(page).last).to_have_text(
        "Draft has changes"
    )  # version 3 repeats version 1; the draft says 'second words'
    assert [v["number"] for v in api.get(f"/api/guards/{guard['id']}/versions").json()] == [3, 2, 1]
    assert api.get(f"/api/guards/{guard['id']}/versions").json()[0]["source_number"] == 1


def test_the_mark_in_the_guard_window_publishes_and_discards_in_a_popup_inside_the_window(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    guard = _guard(api, "Gate", description="first words")  # published as version 1
    _goto(page, base_url)
    page.locator(".mg-card").dblclick()
    window = _window(page)
    mark = window.locator("[data-guard-state]")
    expect(mark.locator(".ge-chip")).to_have_text("v1 published")
    expect(window.locator("[data-publication-trigger]")).to_have_count(
        0
    )  # equal: nothing to do, a plain chip
    expect(window.locator("[data-guard-used]")).to_have_text("Not used yet")
    window.get_by_role("button", name="Cancel").click()

    api.patch(f"/api/guards/{guard['id']}", json={"description": "second words"}).raise_for_status()
    page.reload()
    page.locator(".mg-card").dblclick()
    window = _window(page)
    trigger = window.locator("[data-publication-trigger]")
    expect(trigger).to_contain_text("Draft")
    trigger.click()
    popup = window.locator(
        "[data-publication-popover]"
    )  # it sits inside the window, which hides what is outside it
    expect(popup).to_be_visible()
    expect(popup).to_contain_text("The draft differs from the published version 1")
    expect(popup).to_contain_text("Switching the guard on or off acts at once")
    below, box = trigger.bounding_box(), popup.bounding_box()
    assert below and box and box["y"] >= below["y"] + below["height"] - 1, (
        "the popup opens under the mark"
    )
    popup.locator('[data-publication-action="discard"]').click()
    popup.locator('[data-publication-action="discard-confirm"]').click()
    expect(mark.locator(".ge-chip")).to_have_text("v1 published")
    stored = api.get(f"/api/guards/{guard['id']}").json()
    assert (stored["description"], stored["draft_changed"]) == ("first words", False)

    window.get_by_role("button", name="Cancel").click()
    api.patch(f"/api/guards/{guard['id']}", json={"description": "third words"}).raise_for_status()
    page.reload()
    page.locator(".mg-card").dblclick()
    window = _window(page)
    window.locator("[data-publication-trigger]").click()
    window.locator('[data-publication-action="publish"]').click()
    expect(window.locator("[data-guard-state] .ge-chip")).to_have_text("v2 published")
    stored = api.get(f"/api/guards/{guard['id']}").json()
    assert (stored["published_version"], stored["draft_changed"]) == (2, False)


def test_a_guard_nobody_published_says_in_its_window_and_in_its_usage_that_it_watches_nothing(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    guard = _draft(api, "Quiet")
    _attach(api, guard, pipeline, "stage", pipeline["stage"]["id"])
    _goto(page, base_url)
    page.locator(".mg-card").click()
    usage = _panel_tab(page, "Usage")
    expect(usage).to_contain_text("Not published")
    page.locator(".mg-card").dblclick()
    window = _window(page)
    expect(window.locator("[data-guard-used]")).to_have_text(
        "Used in 1 place. Only the published version applies. Not published yet: it watches nothing until it is published."
    )
    trigger = window.locator("[data-publication-trigger]")
    trigger.click()
    expect(window.locator("[data-publication-popover]")).to_contain_text(
        "Nothing is published: this guard watches nothing yet."
    )
    window.locator('[data-publication-action="publish"]').click()
    expect(window.locator("[data-guard-state] .ge-chip")).to_have_text("v1 published")
    expect(window.locator("[data-guard-used]")).to_have_text(
        "Used in 1 place. Only the published version applies."
    )
