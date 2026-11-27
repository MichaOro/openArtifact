"""The guards inside the action a card runs (ADR-060): the pipeline lists them but cannot detach them, because they belong to the
action and watch it in every pipeline that uses it. The popup of the card and the Guards section of its window say so and link to the
action, where Detach is."""

from __future__ import annotations

import re

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_guard_scopes import _action, _attach_to
from tests.e2e.test_guards import _attach, _guard, _open, _pipeline, _popup
from tests.helpers import link

NOTE = (
    'This guard belongs to the action "Summarise" and watches it in every pipeline that uses it. '
    "To detach it, open the action."
)


def _scene(api: httpx.Client) -> tuple[dict[str, object], dict[str, object]]:
    pipeline = _pipeline(api, with_action=True)
    action = _action(api)
    link(api, pipeline, pipeline["action"], action)
    _attach_to(api, _guard(api, "onError"), action, "definition", None)
    return pipeline, action


def _card(page: Page) -> Locator:
    return page.locator(".ge-node--action", has_text="Summarise").first


def test_the_popup_says_why_an_inner_guard_cannot_be_detached_here_and_links_to_the_action(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline, action = _scene(api)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    _card(page).locator("[data-guard-shield]").click()
    popup = _popup(page)
    note = popup.locator("[data-inner-note]")
    expect(note).to_have_text(NOTE)
    assert (
        popup.locator(".gd-popover__inner [role=switch], .gd-popover__inner [data-detach]").count()
        == 0
    )
    link_el = popup.locator("[data-open-action]")
    expect(link_el).to_have_text("Open the action")
    assert f"/actions/{action['id']}" in (link_el.get_attribute("href") or "")


def test_the_window_of_the_card_lists_the_inner_guard_with_the_note_and_the_link_and_shows_the_heading(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline, action = _scene(api)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    _card(page).click(button="right", position={"x": 30, "y": 5})
    page.get_by_role("menuitem", name="Settings").click()
    section = page.locator("[data-guard-section]")
    expect(section.locator("h3")).to_be_visible()  # only inner guards: the heading must not hide
    expect(section.locator(".gd-inner-caption")).to_have_text('In the action "Summarise"')
    expect(section.locator("[data-inner-guards] li")).to_have_text(["onError: The whole action"])
    expect(section.locator("[data-inner-note]")).to_have_text(NOTE)
    assert section.locator("[role=switch], [data-detach]").count() == 0, (
        "nothing to switch or detach here"
    )
    expect(
        section.locator("[data-add-guard]")
    ).to_be_visible()  # Add guard still adds to this placement
    href = section.locator("[data-open-action]").get_attribute("href") or ""
    assert f"/actions/{action['id']}" in href
    section.locator("[data-open-action]").click()
    expect(page).to_have_url(re.compile(rf"/actions/{action['id']}"))


def test_a_guard_attached_to_the_placement_itself_keeps_its_switch_and_detach(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline, _action_definition = _scene(api)
    _attach(api, _guard(api, "Own guard"), pipeline, "action", pipeline["action"]["id"])  # type: ignore[index]
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    _card(page).locator("[data-guard-shield]").click()
    popup = _popup(page)
    own = popup.locator(".gd-popover__attached li", has_text="Own guard")
    expect(own.locator("[role=switch]")).to_have_count(1)
    expect(own.locator("[data-detach]")).to_have_count(1)
    expect(popup.locator("[data-inner-note]")).to_have_count(1)
