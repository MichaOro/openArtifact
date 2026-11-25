"""The agents page as a management page (ADR-069): cards or rows with the beginning of the user prompt, a click selects and shows the
panel (user prompt, the system prompt only while it is in effect, the model the agent sets itself, the versions), a double click and the
pencil open the editor, the bin deletes after a question (and is disabled while a node refers to the agent), the window that makes or
changes an agent is a form manifest."""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.helpers import node, post

LONG = " ".join(f"Line {i}: check the ticket and say what is missing." for i in range(1, 40))


def _agent(api: httpx.Client, name: str, **draft: Any) -> dict[str, Any]:
    response = api.post("/api/agents", json={"name": name, "draft": draft})
    response.raise_for_status()
    return response.json()  # type: ignore[no-any-return]


def _open(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/agents")
    expect(page.locator(".mg-card").first).to_be_visible()


def test_a_click_shows_the_prompts_and_the_system_prompt_only_while_it_is_in_effect(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _agent(
        api,
        "Triage",
        user_prompt="Summarise the card. Then list what is missing.",
        system_prompt_enabled=True,
        system_prompt="You are brief.",
        limits_enabled=True,
        model="free-pool",
    )
    _agent(
        api,
        "Plain",
        user_prompt="Say hi.",
        system_prompt="Never shown.",
        system_prompt_enabled=False,
    )
    _open(page, base_url)
    # the card says the first sentence and the model
    triage = page.locator(".mg-card", has_text="Triage")
    expect(triage.locator(".mg-card__text")).to_have_text("Summarise the card.")
    expect(triage).to_contain_text("free-pool")
    triage.click()
    panel = page.locator(".mg__panel")
    expect(panel.locator(".mg-panel__title h2")).to_have_text("Triage")
    expect(panel.locator(".ct__text")).to_have_text(
        ["Summarise the card. Then list what is missing.", "You are brief."]
    )
    expect(panel.get_by_role("heading", name="User prompt")).to_be_visible()
    expect(panel.get_by_role("heading", name="System prompt")).to_be_visible()
    expect(panel.locator(".mg-facts")).to_contain_text("free-pool")
    # a system prompt that is switched off is not shown, even though it is kept
    page.locator(".mg-card", has_text="Plain").click()
    expect(panel.locator(".mg-panel__title h2")).to_have_text("Plain")
    expect(panel.locator(".ct__text")).to_have_text(["Say hi."])
    expect(panel.get_by_role("heading", name="System prompt")).to_have_count(0)


def test_a_long_prompt_is_cut_and_opens_with_show_more(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _agent(api, "Wordy", user_prompt=LONG)
    _open(page, base_url)
    page.locator(".mg-card", has_text="Wordy").click()
    text = page.locator(".mg__panel .ct__text")
    more = page.locator(".mg__panel .ct__bar button").first
    expect(more).to_have_text("Show more")
    short = text.bounding_box()
    more.click()
    expect(more).to_have_text("Show less")
    tall = text.bounding_box()
    assert short and tall and tall["height"] > short["height"] * 2, "all of it shows"
    assert text.inner_text().strip() == LONG
    expect(
        page.locator(".mg__panel").get_by_role("button", name=re.compile("^Copy"))
    ).to_be_visible()


def test_double_click_and_the_pencil_open_the_editor_and_the_keys_work(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    first = _agent(api, "Alpha", user_prompt="One.")
    _agent(api, "Beta", user_prompt="Two.")
    _open(page, base_url)
    page.locator(".mg-card", has_text="Alpha").dblclick()
    expect(page).to_have_url(re.compile(rf"/agents/{first['id']}$"))
    _open(page, base_url)
    page.locator(".mg-card", has_text="Alpha").locator("[data-edit]").click()
    expect(page).to_have_url(re.compile(rf"/agents/{first['id']}$"))
    # the keys: an arrow selects the next one, Enter opens it
    _open(page, base_url)
    page.locator(".mg-card", has_text="Alpha").focus()
    page.keyboard.press("ArrowRight")
    expect(page.locator(".mg__panel .mg-panel__title h2")).to_have_text("Beta")
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"/agents/[0-9a-f-]{36}$"))


def test_the_bin_asks_first_and_is_disabled_while_a_node_refers_to_the_agent(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    gone = _agent(api, "Disposable", user_prompt="x")
    used = _agent(api, "Needed", user_prompt="y")
    action = post(api, "/api/actions", name="Uses it")
    node(api, action, "agent", name="Ask", config={"agent_id": used["id"]})
    _open(page, base_url)
    needed = page.locator(".mg-card", has_text="Needed").locator("[data-delete]")
    expect(needed).to_have_attribute("aria-disabled", "true")
    needed.click(force=True)
    expect(page.locator("#confirm-modal")).not_to_be_visible()
    page.locator(".mg-card", has_text="Disposable").locator("[data-delete]").click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-modal [data-confirm]").click()
    expect(page.locator(".mg-card", has_text="Disposable")).to_have_count(0)
    assert gone["id"] not in [a["id"] for a in api.get("/api/agents").json()]


def test_the_window_makes_and_changes_an_agent_and_the_versions_tab_lists_them(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.goto(f"{base_url}/agents")
    page.click("[data-new-agent]")
    window = page.locator("#agent-modal")
    expect(window).to_be_visible()
    window.get_by_label("Name", exact=True).fill("Maker")
    window.get_by_label("Description").fill("Made in the window")
    window.locator("[data-submit]").click()
    expect(page).to_have_url(re.compile(r"/agents/[0-9a-f-]{36}$"))
    _open_after = f"{base_url}/agents"
    page.goto(_open_after)
    card = page.locator(".mg-card", has_text="Maker")
    card.click()
    panel = page.locator(".mg__panel")
    panel.get_by_role("button", name="Properties").click()
    window = page.locator("#agent-modal")
    window.get_by_label("Name", exact=True).fill("Maker 2")
    window.locator("[data-submit]").click()
    expect(page.locator(".mg-card", has_text="Maker 2")).to_have_count(1)
    page.locator(".mg-card", has_text="Maker 2").click()
    panel.get_by_role("tab", name="Versions").click()
    expect(panel.get_by_role("tabpanel", name="Versions")).to_contain_text("Not published")
