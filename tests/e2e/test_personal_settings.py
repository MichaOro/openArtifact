"""The Personal settings page and the setting *Mark resolved references* in the browser: the sidebar has the entry and marks it,
the switch is saved when it is changed, the board's cards and the artifact dialog mark the text a ${card.x} stands for (and the
dialog shows its legend in the rail's foot) while it is on, and both follow the switch live."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import Board, eventually

URL = "/api/settings/personal"
SWITCH = "Mark resolved references"


@pytest.fixture
def card(board: Board) -> Iterator[Board]:
    """A board with one artifact whose body has a reference; the personal setting is off again afterwards."""
    fields = [{"name": "secret", "label": "Secret", "kind": "text"}]
    board.api.put("/api/artifact-fields", json={"fields": fields}).raise_for_status()
    board.api.post(
        "/api/tasks",
        json={
            "title": "Marked",
            "body": "The word is ${card.secret}.",
            "fields": {"secret": "bye"},
        },
    ).raise_for_status()
    board.api.put(URL, json={"mark_resolved_references": False}).raise_for_status()
    yield board
    board.api.put(URL, json={"mark_resolved_references": False})


def test_the_personal_page_has_its_entry_and_saves_the_switch_when_it_is_changed(
    card: Board, base_url: str
) -> None:
    page = card.page
    page.goto(f"{base_url}/settings/personal")
    entry = page.locator('.nav-link[href="/settings/personal"]')
    expect(entry).to_have_text("Personal")  # its text, not the key
    expect(entry).to_have_attribute("aria-current", "page")
    switch = page.get_by_label(SWITCH)
    expect(switch).not_to_be_checked()
    switch.check()
    eventually(lambda: card.api.get(URL).json()["mark_resolved_references"], True)
    expect(page.locator("[data-status]")).to_have_text("Saved.")
    page.reload()
    expect(page.get_by_label(SWITCH)).to_be_checked()  # kept


def test_resolved_text_is_marked_with_a_legend_only_while_the_setting_is_on_and_follows_it_live(
    card: Board,
) -> None:
    card.open()
    body = card.card("Marked").locator(".task-card__body")
    expect(body).to_have_text("The word is bye.")
    expect(body.locator("mark.resolved-ref")).to_have_count(0)  # off: plain text
    dialog = card.open_card("Marked")
    view = dialog.root.locator("[data-view-body]")
    expect(view.locator("mark.resolved-ref")).to_have_count(0)
    expect(dialog.root.locator(".resolved-legend")).to_be_hidden()
    # on: the server sends the segments, the card and the dialog mark the filled in word, live, with the dialog open
    card.api.put(URL, json={"mark_resolved_references": True}).raise_for_status()
    expect(view.locator("mark.resolved-ref")).to_have_text(["bye"])
    expect(view).to_have_text("The word is bye.")  # the same words, only marked
    # the legend is a small passive line in the foot of the rail, next to its expand button, and only while the rail is expanded
    legend = dialog.root.locator(".card-nav__foot .resolved-legend")
    expect(legend).to_be_hidden()  # the rail is collapsed
    dialog.root.locator("[data-card-nav-toggle]").click()
    expect(legend).to_be_visible()
    expect(legend).to_have_text("Resolved")
    expect(legend).to_have_attribute("title", "Resolved reference")
    expect(legend.locator(".resolved-legend__mark")).to_have_css(
        "background-color", pattern_not_transparent()
    )
    # the dark theme marks with a warm light colour (not purple on purple)
    light = view.locator("mark.resolved-ref").evaluate("e => getComputedStyle(e).backgroundColor")
    dialog.root.page.evaluate("document.documentElement.dataset.theme = 'dark'")
    dark = view.locator("mark.resolved-ref").evaluate("e => getComputedStyle(e).backgroundColor")
    assert dark != light
    red, green, blue = (float(x) for x in re.findall(r"[\d.]+", dark.split("/")[0])[:3])
    assert red > blue and green > blue and red > 0.8, (
        f"a light warm colour in the dark theme: {dark}"
    )
    dialog.root.page.evaluate("document.documentElement.dataset.theme = 'light'")
    expect(body.locator("mark.resolved-ref")).to_have_text(["bye"])
    # off again: marks and legend go
    card.api.put(URL, json={"mark_resolved_references": False}).raise_for_status()
    expect(view.locator("mark.resolved-ref")).to_have_count(0)
    expect(legend).to_be_hidden()
    expect(body.locator("mark.resolved-ref")).to_have_count(0)


def pattern_not_transparent():  # type: ignore[no-untyped-def]
    import re

    return re.compile(r"^(?!rgba\(0, 0, 0, 0\)$|transparent$).+")
