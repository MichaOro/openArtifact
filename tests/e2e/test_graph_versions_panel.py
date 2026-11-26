"""The Versions tab of the detail panel of pipelines and actions (ADR-070): publish the draft, the chip, show a version read-only,
publish an earlier one again, a long list folds its middle."""

from __future__ import annotations

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import eventually
from tests.helpers import graph_url, node, post


def _open_versions(page: Page, base_url: str, kind: str, name: str):  # type: ignore[no-untyped-def]
    page.goto(f"{base_url}/{kind}s")
    page.locator(".mg-card", has_text=name).click()
    panel = page.locator(".mg__panel")
    panel.get_by_role("tab", name="Versions").click()
    return panel


def _current(api: httpx.Client, graph: dict, field: str = "published_version"):  # type: ignore[no-untyped-def,type-arg]
    return api.get(graph_url(graph)).json()["graph"][field]


def test_an_action_is_published_changed_shown_and_published_again_in_the_panel(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = post(api, "/api/actions", name="Gap")
    card = page.locator(".mg-card", has_text="Gap")
    panel = _open_versions(page, base_url, "action", "Gap")
    expect(card.locator(".mg-chip", has_text="Draft")).to_be_visible()
    expect(panel).to_contain_text("Nothing is published: executions run the draft.")
    # publish the draft: it asks first, then the chip says which version is in use
    panel.get_by_role("button", name="Publish", exact=True).click()
    page.locator("#confirm-modal").get_by_role("button", name="Publish").click()
    expect(card.locator(".mg-chip", has_text="v1 published")).to_be_visible()
    row = panel.locator('.mg-version[data-version="1"]')
    expect(row).to_contain_text("In use")
    expect(
        panel.get_by_role("button", name="Publish", exact=True)
    ).to_be_disabled()  # the draft equals it
    assert _current(api, action) == 1
    # change the draft (a node): the chip says so, and publishing is offered again
    node(api, action, "timer", name="Pause", seconds=5)
    page.reload()
    page.locator(".mg-card", has_text="Gap").click()
    page.locator(".mg__panel").get_by_role("tab", name="Versions").click()
    expect(page.locator(".mg-card .mg-chip", has_text="Draft has changes")).to_be_visible()
    panel = page.locator(".mg__panel")
    panel.get_by_role("button", name="Publish", exact=True).click()
    page.locator("#confirm-modal").get_by_role("button", name="Publish").click()
    eventually(lambda: _current(api, action), 2)
    expect(panel.locator('.mg-version[data-version="2"]')).to_contain_text("In use")
    # show the first version read-only in the Graph tab, then go back to the draft
    panel.locator('.mg-version[data-version="1"]').get_by_role(
        "button", name="Show version 1"
    ).click()
    expect(panel.get_by_role("tab", name="Graph")).to_have_attribute("aria-selected", "true")
    expect(panel.locator(".mg-showing")).to_contain_text("Showing version 1, read-only.")
    expect(panel.locator(".mg-showing .button")).to_have_text("Back to the draft")
    panel.locator(".mg-showing .button").click()
    expect(panel.locator(".mg-showing")).to_have_count(0)
    # publish version 1 again: a new version that repeats it, in use now
    panel.get_by_role("tab", name="Versions").click()
    panel.get_by_role("button", name="Publish version 1 again").click()
    page.locator("#confirm-modal").get_by_role("button", name="Publish again").click()
    eventually(lambda: _current(api, action), 3)
    third = panel.locator('.mg-version[data-version="3"]')
    expect(third).to_contain_text("In use")
    expect(third).to_contain_text("rollback to version 1")
    expect(
        page.locator(".mg-card .mg-chip", has_text="Draft has changes")
    ).to_be_visible()  # the draft still says two nodes


def test_a_pipeline_has_the_same_tab_and_a_long_list_folds_its_middle(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = post(api, "/api/pipelines", name="Flow")
    for i in range(6):
        node(api, pipeline, "stage", name=f"Stage {i}")
        api.post(f"{graph_url(pipeline)}/publish").raise_for_status()
    panel = _open_versions(page, base_url, "pipeline", "Flow")
    # six versions: the newest two and the first stay, the other three are behind one separator
    expect(panel.locator(".mg-version")).to_have_count(3)
    expect(panel.locator(".mg-version").nth(0)).to_have_attribute("data-version", "6")
    expect(panel.locator(".mg-version").nth(1)).to_have_attribute("data-version", "5")
    expect(panel.locator(".mg-version").nth(2)).to_have_attribute("data-version", "1")
    separator = panel.locator(".fold-separator__button")
    expect(separator).to_have_text("Show more versions (3)")
    separator.click()
    expect(panel.locator(".mg-version")).to_have_count(6)
    expect(panel.locator(".fold-separator__button")).to_have_text("Hide 3 versions")
    # a version of a pipeline is shown as its stages
    panel.locator('.mg-version[data-version="3"]').get_by_role(
        "button", name="Show version 3"
    ).click()
    expect(panel.locator(".mg-showing")).to_contain_text("Showing version 3, read-only.")


def test_publishing_in_the_panel_over_findings_lists_them_and_says_publish_anyway(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = post(api, "/api/actions", name="Gap findings")
    node(api, action, "http", name="Reader", config={"url": "http://example.test/${card.nothing}"})
    panel = _open_versions(page, base_url, "action", "Gap findings")
    panel.get_by_role("button", name="Publish", exact=True).click()
    dialog = page.locator("#confirm-modal")
    expect(dialog).to_contain_text("The check found 1 error(s) and 0 warning(s) in the draft")
    expect(dialog.locator("[data-confirm-items] li")).to_have_count(1)
    expect(dialog.locator("[data-confirm-items] li")).to_contain_text(
        "Error Reader: ${card.nothing}: the artifact has no field 'nothing'"
    )
    dialog.get_by_role("button", name="Cancel").click()
    assert _current(api, action) is None  # nothing was published
    panel.get_by_role("button", name="Publish", exact=True).click()
    dialog.get_by_role("button", name="Publish anyway").click()
    eventually(lambda: _current(api, action), 1)
