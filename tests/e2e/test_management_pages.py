"""The management pages of pipelines and actions (ADR-069): a click selects and shows the details in the panel, a double click and the
pencil open the editor, the bin deletes after a question, the keys move and open, cards or list, search and tags, the usage tab, the
greyed versions tab, and the sheet on a narrow screen."""

from __future__ import annotations

import re

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import eventually
from tests.helpers import build_pipeline, link, post


def _card(page: Page, name: str):  # type: ignore[no-untyped-def]
    return page.locator(".mg-card", has_text=name)


def test_a_click_selects_and_shows_the_panel_a_double_click_and_the_pencil_open_the_editor(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    post(api, "/api/actions", name="Gap analysis", description="Finds gaps.", tags=["epic"])
    page.goto(f"{base_url}/actions")
    panel = page.locator(".mg__panel")
    expect(panel).to_be_hidden()
    _card(page, "Gap analysis").click()
    expect(panel).to_be_visible()
    expect(panel.locator("h2")).to_have_text("Gap analysis")
    expect(_card(page, "Gap analysis")).to_have_attribute("aria-current", "true")
    expect(panel.get_by_role("tab")).to_have_text(["Overview", "Graph", "Versions", "Usage"])
    expect(panel.get_by_role("tab", name="Versions")).to_be_disabled()  # a place held, not built
    expect(panel.locator(".mg-tag")).to_have_text(["epic"])
    _card(page, "Gap analysis").dblclick()
    expect(page).to_have_url(f"{base_url}/actions/gap-analysis")
    page.go_back()
    _card(page, "Gap analysis").locator("[data-edit]").click()
    expect(page).to_have_url(f"{base_url}/actions/gap-analysis")


def test_the_keys_select_open_and_delete_and_the_bin_asks_first(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    post(api, "/api/pipelines", name="Alpha")
    post(api, "/api/pipelines", name="Beta")
    page.goto(f"{base_url}/pipelines")
    page.locator("#graph-modal").wait_for(state="attached")
    page.get_by_label("Order").select_option("name")
    first = page.locator(".mg-card").first
    first.focus()
    page.keyboard.press("ArrowDown")
    expect(_card(page, "Beta")).to_have_attribute("aria-current", "true")
    expect(page.locator(".mg__panel h2")).to_have_text("Beta")
    page.keyboard.press("Delete")
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.keyboard.press("Escape")
    assert len(api.get("/api/pipelines").json()) == 2, (
        "asked first, nothing is deleted without the answer"
    )
    page.keyboard.press("Enter")
    expect(page).to_have_url(f"{base_url}/pipelines/beta")
    page.go_back()
    _card(page, "Beta").locator("[data-delete]").click()
    page.click("#confirm-modal [data-confirm]")
    expect(page.locator(".mg-card")).to_have_count(1)
    eventually(lambda: [p["name"] for p in api.get("/api/pipelines").json()], ["Alpha"], page=page)


def test_cards_or_list_search_and_tags_and_the_usage_of_an_action(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    judge = post(api, "/api/actions", name="Judge", tags=["review"])
    post(api, "/api/actions", name="Mailer", tags=["mail"])
    flow = build_pipeline(api, name="Review flow", stages=1, stage_name="Check")
    link(api, flow, flow["stages"][0][1], judge)
    page.goto(f"{base_url}/actions")
    expect(page.locator(".mg__list")).to_have_attribute("data-view", "cards")
    page.get_by_role("button", name="List").click()
    expect(page.locator(".mg__list")).to_have_attribute("data-view", "list")
    page.reload()
    expect(page.locator(".mg__list")).to_have_attribute(
        "data-view", "list"
    )  # kept for the next visit
    page.get_by_role("searchbox").fill("mail")
    expect(page.locator(".mg-card")).to_have_count(1)
    page.get_by_role("searchbox").fill("review")  # a tag is searched too
    expect(_card(page, "Judge")).to_have_count(1)
    page.get_by_role("searchbox").fill("")
    page.get_by_role("button", name="Filter").click()
    page.get_by_role("menuitem", name="mail").click()
    expect(page.locator(".mg-card")).to_have_count(1)
    expect(_card(page, "Mailer")).to_be_visible()
    page.get_by_role("button", name="Filter").click()
    page.get_by_role("menuitem", name="All tags").click()
    _card(page, "Judge").click()
    page.locator(".mg__panel").get_by_role("tab", name="Usage").click()
    link_to_flow = page.locator(".mg__panel .mg-uses a")
    expect(link_to_flow).to_have_text("Review flow · Check")
    expect(link_to_flow).to_have_attribute("href", "/pipelines/review-flow")


def test_a_new_pipeline_gets_description_and_tags_and_the_panel_is_a_sheet_on_a_narrow_screen(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    post(api, "/api/pipelines", name="Existing")
    page.goto(f"{base_url}/pipelines")
    page.click("[data-new-graph]")
    window = page.locator("#graph-modal")
    window.get_by_label("Name").fill("Described")
    window.get_by_label("Description").fill("Does things.")
    window.get_by_label("Tags").fill("epic, Epic, analysis")
    window.locator("[data-submit]").click()
    expect(page).to_have_url(f"{base_url}/pipelines/described")
    made = next(p for p in api.get("/api/pipelines").json() if p["name"] == "Described")
    assert (made["description"], made["tags"]) == ("Does things.", ["epic", "analysis"])
    page.set_viewport_size({"width": 420, "height": 850})
    page.goto(f"{base_url}/pipelines")
    _card(page, "Existing").click()
    panel = page.locator(".mg__panel")
    expect(panel).to_be_visible()
    assert panel.evaluate("el => getComputedStyle(el).position") == "fixed", (
        "a sheet from the bottom"
    )
    box = panel.bounding_box()
    assert box and abs(box["y"] + box["height"] - 850) < 2 and box["width"] >= 410
    panel.get_by_role("button", name=re.compile("Close")).click()
    expect(panel).to_be_hidden()
