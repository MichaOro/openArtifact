"""An action is made for pipelines or for guards (ADR-067): the window that makes it asks for the type, the list keeps the two apart
(two tabs, a Guard chip next to Draft), a type that is in use on the other side cannot change (the window says where), a stage offers
only the actions for pipelines, and the "+" menu of a guard action offers the nodes for guards."""

from __future__ import annotations

import re

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import eventually, pick_node
from tests.helpers import build_pipeline, graph_url, link

_PURPOSES = {"pipeline": "For pipelines", "guard": "For guards"}


def _make(page: Page, name: str, purpose: str) -> None:
    page.click("[data-new-graph]")
    dialog = page.locator("#action-modal")
    expect(dialog).to_be_visible()
    dialog.get_by_label("Name").fill(name)
    dialog.locator(f'[data-choice="{purpose}"]').click()
    dialog.locator("[data-submit]").click()
    expect(page).to_have_url(re.compile(r"/actions/[a-z0-9-]+$"))


def test_an_action_is_made_for_guards_listed_apart_and_changed_with_protection(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.goto(f"{base_url}/actions")
    page.click("[data-new-graph]")
    dialog = page.locator("#action-modal")
    expect(dialog.locator('[data-choice="pipeline"]')).to_have_attribute(
        "aria-pressed", "true"
    )  # the default
    expect(dialog.get_by_text("For guards")).to_be_visible()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    _make(page, "Judge", "guard")
    assert [a["purpose"] for a in api.get("/api/actions").json()] == ["guard"]
    page.goto(f"{base_url}/actions")
    # two lists: the one for pipelines is open and empty, the guard actions are in the other tab with the Guard chip next to Draft
    expect(page.locator('[data-ge-empty][data-purpose="pipeline"]')).to_be_visible()
    page.get_by_role("tab", name="Guard actions").click()
    item = page.locator('[data-ge-list][data-purpose="guard"] .ge-item')
    expect(item).to_have_count(1)
    expect(item.locator(".ge-chip:visible")).to_have_text(["Draft", "Guard"])
    # the pencil changes name and type in the same window
    item.locator("[data-rename]").click()
    expect(dialog.locator("#action-modal-title, .modal__title")).to_have_text("Edit action")
    dialog.locator('[data-choice="pipeline"]').click()
    dialog.locator("[data-submit]").click()
    eventually(lambda: api.get("/api/actions").json()[0]["purpose"], "pipeline", page=page)
    page.get_by_role("tab", name="Pipeline actions").click()
    pipeline_item = page.locator('[data-ge-list][data-purpose="pipeline"] .ge-item')
    expect(pipeline_item).to_have_count(1)
    expect(pipeline_item.locator(".ge-chip:visible")).to_have_text(["Draft"])
    # an action a stage uses cannot become a guard action: the window says where
    flow = build_pipeline(api, name="Uses Judge", stages=1)
    (action,) = api.get("/api/actions").json()
    link(api, flow, flow["stages"][0][1], action)
    page.reload()
    page.locator('[data-ge-list][data-purpose="pipeline"] [data-rename]').click()
    dialog.locator('[data-choice="guard"]').click()
    dialog.locator("[data-submit]").click()
    expect(dialog.locator("[data-form-error]")).to_contain_text(
        "used by the stages of 'Uses Judge'"
    )
    assert api.get(graph_url(action)).json()["graph"]["purpose"] == "pipeline"


def test_a_stage_offers_only_the_actions_for_pipelines(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    api.post("/api/actions", json={"name": "Plain"}).raise_for_status()
    api.post("/api/actions", json={"name": "Judge", "purpose": "guard"}).raise_for_status()
    flow = build_pipeline(api, name="Flow", stages=1)
    page.goto(f"{base_url}/pipelines/{flow['slug']}")
    page.locator(".ge-node--action").first.locator(".ge-node__name").dblclick()
    select = page.locator(".ge-inspector select[data-focus-key='link']")
    expect(select.locator("option")).to_have_text(["Not defined", "Plain"])


def test_the_plus_menu_of_a_guard_action_and_a_pipeline_action_offers_what_their_kinds_allow(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    judge = api.post("/api/actions", json={"name": "Judge", "purpose": "guard"}).json()
    plain = api.post("/api/actions", json={"name": "Plain"}).json()
    for definition in (judge, plain):
        page.goto(f"{base_url}/actions/{definition['slug']}")
        expect(page.locator(".ge-node--output")).to_be_visible()
        page.click("[data-add-menu]")
        pick_node(page, "code")
        expect(page.locator(".ge-node--code")).to_have_count(
            1
        )  # a kind that is for both is in both
