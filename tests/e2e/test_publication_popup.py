"""The mark in the toolbar of the editor ("Draft", "v2 published") opens a small popup with Publish and Discard draft (ADR-070
addendum), so a draft is published or thrown away without a visit to the management page."""

from __future__ import annotations

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import eventually, pick_node
from tests.helpers import node, post

MARK = ".ge-bar__state"
TRIGGER = "[data-publication-trigger]"
POPUP = "[data-publication-popover]"


def _changed_action(api: httpx.Client, name: str) -> dict[str, object]:
    """An action with version 1 published and a node added after it: its draft differs."""
    action = post(api, "/api/actions", name=name)
    api.post(f"/api/actions/{action['id']}/publish").raise_for_status()
    node(api, action, "code", name="Added after")
    return action


def test_the_mark_of_a_draft_with_changes_opens_a_popup_that_closes_on_escape_and_on_a_click_elsewhere(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _changed_action(api, "Popup")
    page.goto(f"{base_url}/actions/{action['slug']}")
    trigger = page.locator(TRIGGER)
    expect(trigger).to_have_attribute("aria-haspopup", "dialog")
    expect(trigger).to_have_attribute("aria-expanded", "false")
    trigger.click()
    popup = page.locator(POPUP)
    expect(popup).to_be_visible()
    expect(trigger).to_have_attribute("aria-expanded", "true")
    expect(popup.get_by_role("button", name="Publish")).to_be_visible()
    expect(popup.get_by_role("button", name="Discard draft")).to_be_visible()
    page.keyboard.press("Escape")
    expect(popup).to_be_hidden()
    expect(trigger).to_be_focused()
    trigger.click()
    expect(popup).to_be_visible()
    page.mouse.click(600, 500)
    expect(popup).to_be_hidden()


def test_publish_in_the_popup_makes_the_next_version_and_the_mark_stops_being_a_control(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _changed_action(api, "Publish here")
    page.goto(f"{base_url}/actions/{action['slug']}")
    expect(page.locator(MARK)).to_have_text("Draft")
    page.locator(TRIGGER).click()
    page.locator(POPUP).get_by_role("button", name="Publish").click()
    expect(page.locator(MARK)).to_have_text("v2 published")
    expect(page.locator(POPUP)).to_be_hidden()
    expect(page.locator(TRIGGER)).to_have_count(
        0
    )  # equal to the published version: nothing to do, a plain chip
    assert [v["number"] for v in api.get(f"/api/actions/{action['id']}/versions").json()] == [2, 1]


def test_discard_asks_first_and_then_brings_the_published_graph_back_without_a_reload(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _changed_action(api, "Discard here")
    page.goto(f"{base_url}/actions/{action['slug']}")
    nodes = page.locator("[data-nodes] > *")
    expect(nodes).to_have_count(3)  # trigger, output and the node added after the publication
    page.evaluate("window.__kept = true")  # survives only while the page is not reloaded
    page.locator(TRIGGER).click()
    popup = page.locator(POPUP)
    popup.get_by_role("button", name="Discard draft").click()
    expect(popup).to_contain_text("The changes since version 1 are lost")
    popup.get_by_role("button", name="Cancel").click()
    expect(popup.get_by_role("button", name="Publish")).to_be_visible()
    expect(nodes).to_have_count(3)  # Cancel changed nothing
    popup.get_by_role("button", name="Discard draft").click()
    popup.get_by_role("button", name="Discard draft").click()
    expect(page.locator(MARK)).to_have_text("v1 published")
    expect(nodes).to_have_count(2)
    assert page.evaluate("window.__kept") is True, (
        "the editor read the graph again, the page was not reloaded"
    )
    assert len(api.get(f"/api/actions/{action['id']}").json()["nodes"]) == 2


def test_a_draft_nobody_published_offers_publish_only(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = post(api, "/api/actions", name="Never published")
    page.goto(f"{base_url}/actions/{action['slug']}")
    page.locator(TRIGGER).click()
    popup = page.locator(POPUP)
    expect(popup).to_contain_text("Nothing is published")
    expect(popup.get_by_role("button", name="Publish")).to_be_visible()
    expect(popup.get_by_role("button", name="Discard draft")).to_have_count(0)


def test_a_refusal_of_the_server_is_shown_in_the_popup_and_the_popup_stays_open(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _changed_action(api, "Refused")
    page.goto(f"{base_url}/actions/{action['slug']}")
    page.locator(TRIGGER).click()
    api.post(
        f"/api/actions/{action['id']}/publish"
    ).raise_for_status()  # published elsewhere meanwhile
    page.locator(POPUP).get_by_role("button", name="Publish").click()
    expect(page.locator(POPUP).get_by_role("alert")).to_contain_text(
        "Nothing changed since version 2"
    )
    expect(page.locator(POPUP)).to_be_visible()


def test_the_pipeline_editor_has_the_same_popup(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = post(api, "/api/pipelines", name="Flow popup")
    api.post(f"/api/pipelines/{pipeline['id']}/publish").raise_for_status()
    node(api, pipeline, "stage", name="Added after")
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    page.locator(TRIGGER).click()
    popup = page.locator(POPUP)
    expect(popup.get_by_role("button", name="Discard draft")).to_be_visible()
    popup.get_by_role("button", name="Discard draft").click()
    popup.get_by_role("button", name="Discard draft").click()
    expect(page.locator(MARK)).to_have_text("v1 published")


# ── the check before publishing (ADR-082) ────────────────────────────

CONFIRM = "#confirm-modal"


def _action_with_findings(api: httpx.Client, name: str) -> dict[str, object]:
    """An action whose draft has an error (a card field that does not exist) and a warning (a variable nobody sets)."""
    action = post(api, "/api/actions", name=name)
    node(
        api,
        action,
        "http",
        name="Reader",
        config={"url": "http://example.test/${card.nothing}/${var.token}"},
    )
    return action


def test_publishing_over_findings_asks_with_the_findings_and_cancel_publishes_nothing(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _action_with_findings(api, "Findings cancel")
    page.goto(f"{base_url}/actions/{action['slug']}")
    page.locator(TRIGGER).click()
    page.locator(POPUP).get_by_role("button", name="Publish").click()
    dialog = page.locator(CONFIRM)
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("The check found 1 error(s) and 1 warning(s) in the draft")
    items = dialog.locator("[data-confirm-items] li")
    expect(items).to_have_count(2)
    expect(items.nth(0)).to_contain_text("Error Reader: ")  # errors first, by the node's name
    expect(items.nth(0)).to_contain_text("the artifact has no field 'nothing'")
    expect(items.nth(1)).to_contain_text("Warning Reader: ")
    expect(dialog.get_by_role("button", name="Publish anyway")).to_have_class(
        "button button--danger"
    )  # an error: asked in red
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden()
    expect(page.locator(MARK)).to_have_text("Draft")
    assert api.get(f"/api/actions/{action['id']}/versions").json() == []  # nothing was published


def test_publish_anyway_publishes_the_draft_with_the_findings(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _action_with_findings(api, "Findings publish")
    page.goto(f"{base_url}/actions/{action['slug']}")
    page.locator(TRIGGER).click()
    page.locator(POPUP).get_by_role("button", name="Publish").click()
    page.locator(CONFIRM).get_by_role("button", name="Publish anyway").click()
    expect(page.locator(MARK)).to_have_text("v1 published")
    assert [v["number"] for v in api.get(f"/api/actions/{action['id']}/versions").json()] == [1]


def test_a_draft_with_findings_is_saved_without_any_question(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = post(api, "/api/actions", name="Findings save")
    page.goto(f"{base_url}/actions/{action['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.click("[data-add-menu]")
    pick_node(page, "http")
    page.locator(".ge-node--http").dblclick(position={"x": 30, "y": 5})
    field = page.locator("#node-modal").get_by_label("URL")
    wrong = "http://example.test/${secret:NOPE}/${(Nobody).output}"
    field.fill(wrong)
    field.press("Enter")
    eventually(
        lambda: [
            n["config"]["url"]
            for n in api.get(f"/api/actions/{action['id']}").json()["nodes"]
            if n["kind"] == "http"
        ],
        [wrong],
    )  # saved at once: the draft may be wrong, only what is published runs
    expect(page.locator(CONFIRM)).to_be_hidden()
