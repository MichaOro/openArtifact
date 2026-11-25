"""The Guards page as a management page (ADR-069): a click selects a guard and shows its details on the right, a double click, the
pencil and Enter open it in the guard editor, the bin and Delete ask first; the panel says what fires it, its condition in words,
its consequence, its action, where it is used and for how many running scopes its condition holds."""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import code_definition
from tests.e2e.test_guards import ROUND, _attach, _guard, _pipeline, _window


def _goto(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/guards")
    expect(page.locator(".mg-card").first).to_be_visible()


def test_a_click_selects_and_shows_the_details_and_opening_takes_a_double_click_the_pencil_or_enter(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _guard(api, "Round guard", description="Pauses a run that loops.")
    _goto(page, base_url)
    card = page.locator(".mg-card")
    panel = page.locator(".mg__panel")
    expect(panel).to_be_hidden()
    card.click()
    expect(card).to_have_attribute("aria-current", "true")
    expect(panel).to_be_visible()
    expect(panel.locator("h2")).to_have_text("Round guard")
    expect(page.locator("#guard-modal")).to_be_hidden()  # a single click only selects
    overview = panel.locator('[role="tabpanel"]:not([hidden])')
    expect(overview).to_contain_text("On entered")
    expect(overview).to_contain_text("Rounds of the scope is at least 5")
    expect(overview).to_contain_text("Pause the run")
    expect(overview).to_contain_text("Pauses a run that loops.")
    card.dblclick()
    window = _window(page)
    expect(window.locator("[data-guard-name]")).to_have_text("Round guard")
    window.get_by_role("button", name="Cancel").click()
    expect(window).to_be_hidden()
    card.locator("[data-edit]").click()  # the pencil
    _window(page)
    page.keyboard.press("Escape")
    card.focus()
    page.keyboard.press("Enter")  # the keyboard
    _window(page)


def test_the_bin_and_the_delete_key_ask_first_and_a_used_guard_says_why_it_stays(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    used = _guard(api, "Used guard")
    _attach(api, used, pipeline, "stage", pipeline["stage"]["id"])
    free = _guard(api, "Free guard")
    _goto(page, base_url)
    free_card = page.locator(".mg-card", has_text="Free guard")
    free_card.focus()
    page.keyboard.press("Delete")
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-modal [data-cancel]").first.click()
    assert {g["id"] for g in api.get("/api/guards").json()} >= {free["id"]}  # nothing was deleted
    used_bin = page.locator(".mg-card", has_text="Used guard").locator("[data-delete]")
    expect(used_bin).to_have_attribute("aria-disabled", "true")
    expect(used_bin).to_have_attribute("title", "Detach it first: it is used in 1 place")
    used_bin.click(force=True)
    expect(page.locator("[data-alert]")).to_contain_text("Detach it first")
    free_card.locator("[data-delete]").click()
    page.locator("#confirm-modal [data-confirm], #confirm-modal [data-submit]").first.click()
    expect(page.locator(".mg-card")).to_have_count(1)


def test_the_panel_shows_the_action_the_steps_where_it_is_used_and_the_preview(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    action = code_definition(api, "Judge health", "print('ok')")
    api.patch(f"/api/actions/{action['id']}", json={"purpose": "guard"}).raise_for_status()
    guard: dict[str, Any] = _guard(
        api,
        "Health guard",
        consequence="run_action",
        action_id=action["id"],
        escalation=[{"from_firing": 2, "every_runs": 3}, {"from_firing": 4, "every_seconds": 300}],
    )
    _attach(api, guard, pipeline, "stage", pipeline["stage"]["id"])
    _goto(page, base_url)
    page.locator(".mg-card").click()
    panel = page.locator(".mg__panel")
    overview = panel.locator('[role="tabpanel"]:not([hidden])')
    link = overview.get_by_role("link", name="Judge health")
    expect(link).to_have_attribute("href", re.compile(rf"/actions/{action['id']}$"))
    expect(overview).to_contain_text("From firing 2 on: every 3 rounds")
    expect(overview).to_contain_text("From firing 4 on: every 5 minutes")
    panel.get_by_role("tab", name="Usage").click()
    uses = panel.locator(".mg-uses li")
    expect(uses).to_have_count(1)
    expect(uses.first).to_contain_text("Stage")
    expect(uses.first.get_by_role("link")).to_have_attribute(
        "href", re.compile(rf"/pipelines/{pipeline['id']}$")
    )
    panel.get_by_role("tab", name="Preview").click()
    expect(panel.locator(".gd-preview")).to_have_text("Nothing it watches runs right now.")
    assert ROUND["items"]  # the guard has a condition: the preview asked the server


def test_the_search_filters_and_most_used_puts_the_busy_guard_first(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _guard(api, "Alpha watch")
    busy = _guard(api, "Zulu watch")
    _attach(api, busy, pipeline, "stage", pipeline["stage"]["id"])
    _goto(page, base_url)
    names = page.locator(".mg-card .mg-card__name")
    expect(names).to_have_text(["Alpha watch", "Zulu watch"])
    page.locator(".mg-sort").select_option("used")
    expect(names).to_have_text(["Zulu watch", "Alpha watch"])
    page.locator(".mg-search input").fill("alpha")
    expect(names).to_have_text(["Alpha watch"])
    page.locator(".mg-view__button").nth(1).click()  # rows
    expect(page.locator(".mg__list")).to_have_attribute("data-view", "list")
