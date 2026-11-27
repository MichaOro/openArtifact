"""The Dry run tab of the Trigger window (ADR-086): choose a test card, give the inputs, check, start, read the result. Narrow tests of one
window: the rules themselves (checks, skipping, versions) are the server's and are tested in tests/test_dry_run.py."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import arrange, eventually
from tests.helpers import (
    build_definition,
    build_pipeline,
    connect,
    graph_url,
    kind_of,
    link,
    node,
    post,
)

DIALOG = "#node-modal"


def _inputs(api: httpx.Client, graph: dict[str, Any], inputs: list[dict[str, Any]]) -> None:
    trigger = kind_of(api, graph, "trigger")
    api.patch(
        f"{graph_url(graph)}/nodes/{trigger['id']}", json={"config": {"inputs": inputs}}
    ).raise_for_status()


def _commenting_pipeline(api: httpx.Client) -> tuple[dict[str, Any], dict[str, Any]]:
    """A pipeline whose one action adds a comment to the artifact: a writing node, so a dry run skips it. Returns (pipeline, action definition)."""
    pipeline = build_pipeline(api, stages=1, name="Commenting", stage_name="Comment stage")
    definition = build_definition(api, "Comment", output=None)
    trigger, output = kind_of(api, definition, "trigger"), kind_of(api, definition, "output")
    comment = node(
        api,
        definition,
        "artifact",
        name="Say hello",
        config={"operation": "Add comment", "text": "Hello from the run"},
    )
    connect(api, definition, trigger, "out", comment, "in")
    connect(api, definition, comment, "pass", output, "pass")
    link(api, pipeline, pipeline["stages"][0][1], definition)
    return pipeline, definition


def _open_trigger(
    page: Page, base_url: str, api: httpx.Client, graph: dict[str, Any], kind: str = "pipelines"
) -> Any:
    if kind == "pipelines":
        arrange(api, graph)  # the builders put every node at 0, 0
    page.goto(f"{base_url}/{kind}/{graph['slug']}")
    page.locator(".ge-node--trigger").dblclick(position={"x": 20, "y": 5})
    dialog = page.locator(DIALOG)
    expect(dialog).to_be_visible()
    return dialog


def _dry_run_tab(dialog: Any) -> Any:
    dialog.get_by_role("tab", name="Dry run").click()
    panel = dialog.locator("[data-dry-run]")
    expect(panel).to_be_visible()
    return panel


def _add_card_field(page: Page, panel: Any) -> None:
    """The test card is an optional item behind "+ Add" (ADR-086 addendum 2): put it on the form."""
    panel.get_by_role("button", name="Add", exact=True).click()
    page.get_by_role("menuitem", name="Test card").click()


def _choose_card(page: Page, panel: Any, text: str) -> None:
    if not panel.get_by_role("combobox", name="Test card").is_visible():
        _add_card_field(page, panel)
    box = panel.get_by_role("combobox", name="Test card")
    box.click()
    box.fill(text)
    page.get_by_role("listbox").get_by_role("option").first.click()


@pytest.fixture(autouse=True)
def _stop_off(api: httpx.Client) -> Iterator[None]:
    yield
    api.put("/api/settings/stop", json={"active": False})


def test_the_trigger_window_has_the_two_tabs_and_the_output_window_has_none(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline, definition = _commenting_pipeline(api)
    dialog = _open_trigger(page, base_url, api, pipeline)
    tabs = dialog.get_by_role("tab")
    expect(tabs).to_have_text(["Inputs", "Dry run"])
    expect(dialog.get_by_role("tab", name="Inputs")).to_have_attribute("aria-selected", "true")
    dialog.get_by_role("tab", name="Dry run").click()
    expect(dialog.get_by_role("tab", name="Dry run")).to_have_attribute("aria-selected", "true")
    page.keyboard.press("Escape")
    page.goto(f"{base_url}/actions/{definition['slug']}")
    page.locator(".ge-node--output").dblclick(position={"x": 30, "y": 5})
    expect(page.locator(DIALOG)).to_be_visible()
    expect(page.locator(DIALOG).get_by_role("tab")).to_have_count(0)


def test_the_tab_chosen_stays_when_the_window_is_opened_again(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline, _ = _commenting_pipeline(api)
    dialog = _open_trigger(page, base_url, api, pipeline)
    _dry_run_tab(dialog)
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    page.locator(".ge-node--trigger").dblclick(position={"x": 20, "y": 5})
    expect(page.locator(DIALOG).get_by_role("tab", name="Dry run")).to_have_attribute(
        "aria-selected", "true"
    )


def test_the_declared_inputs_are_a_form_with_the_default_faint_and_a_required_one_marked(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline, _ = _commenting_pipeline(api)
    _inputs(
        api,
        pipeline,
        [
            {"name": "who", "type": "text", "required": True, "description": ""},
            {
                "name": "times",
                "type": "number",
                "required": False,
                "description": "",
                "default": "2",
            },
            {"name": "loud", "type": "boolean", "required": False, "description": ""},
            {
                "name": "mood",
                "type": "choice",
                "required": False,
                "description": "",
                "choices": ["calm", "wild"],
            },
            {"name": "tags", "type": "list", "required": False, "description": ""},
        ],
    )
    panel = _dry_run_tab(_open_trigger(page, base_url, api, pipeline))
    expect(panel.get_by_label("who")).to_have_attribute("placeholder", "Required")
    expect(panel.locator("label", has_text="who")).to_contain_text("(required)")
    times = panel.get_by_label("times")
    expect(times).to_have_attribute("placeholder", "2")
    expect(times).to_have_value("")  # empty means the default: it is faint, not typed
    expect(panel.get_by_label("loud").locator("option")).to_have_text(["Not set", "true", "false"])
    expect(panel.get_by_label("mood").locator("option")).to_have_text(["Not set", "calm", "wild"])
    expect(panel.get_by_label("tags")).to_have_js_property("tagName", "TEXTAREA")


def test_the_test_card_is_not_on_the_form_until_it_is_added_and_the_start_waits_for_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline, _ = _commenting_pipeline(api)
    post(api, "/api/tasks", title="First card", status="backlog")
    second = post(api, "/api/tasks", title="Second card", status="in_progress")
    panel = _dry_run_tab(_open_trigger(page, base_url, api, pipeline))
    expect(panel.get_by_role("combobox", name="Test card")).to_be_hidden()
    start = panel.get_by_role("button", name="Start dry run")
    expect(start).to_be_disabled()
    expect(start).to_have_attribute("title", "Add a test card first (Add)")
    panel.get_by_role("button", name="Add", exact=True).click()
    expect(page.get_by_role("menuitem")).to_have_text(["Test card"])
    page.get_by_role("menuitem", name="Test card").click()
    expect(panel.get_by_role("combobox", name="Test card")).to_be_visible()
    expect(
        panel.get_by_role("button", name="Add", exact=True)
    ).to_be_hidden()  # nothing else to add
    _choose_card(page, panel, "Second")
    expect(start).to_be_enabled()
    page.reload()  # a card chosen is remembered for the graph: it is on the form again
    page.locator(".ge-node--trigger").dblclick(position={"x": 20, "y": 5})
    panel = _dry_run_tab(page.locator(DIALOG))
    expect(panel.get_by_role("combobox", name="Test card")).to_have_value(
        f"#{second['number']} Second card"
    )


def test_the_test_card_is_taken_off_the_form_again_and_stays_off(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline, _ = _commenting_pipeline(api)
    post(api, "/api/tasks", title="Test card", status="backlog")
    panel = _dry_run_tab(_open_trigger(page, base_url, api, pipeline))
    _choose_card(page, panel, "Test")
    expect(panel.get_by_role("button", name="Start dry run")).to_be_enabled()
    panel.get_by_role("button", name="Remove the test card").click()
    expect(panel.get_by_role("combobox", name="Test card")).to_be_hidden()
    expect(panel.get_by_role("button", name="Start dry run")).to_be_disabled()
    expect(panel.get_by_role("button", name="Add", exact=True)).to_be_visible()
    page.reload()
    page.locator(".ge-node--trigger").dblclick(position={"x": 20, "y": 5})
    panel = _dry_run_tab(page.locator(DIALOG))
    expect(panel.get_by_role("combobox", name="Test card")).to_be_hidden()


def test_a_start_shows_one_row_that_leads_to_the_execution_and_no_list_of_steps(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline, _ = _commenting_pipeline(api)
    task = post(api, "/api/tasks", title="Test card", status="backlog")
    panel = _dry_run_tab(_open_trigger(page, base_url, api, pipeline))
    _choose_card(page, panel, "Test")
    panel.get_by_role("button", name="Start dry run").click()
    row = panel.locator(".ge-dry__runs .history-row")
    expect(row).to_have_count(1)
    expect(row.locator(".history-chip")).to_have_text("Done")
    expect(row.locator(".history-flag")).to_have_text("Dry run")
    expect(row.locator("[data-row-number]")).to_have_text("#1")
    expect(panel.locator(".ge-dry__step")).to_have_count(
        0
    )  # the steps are in the execution, not in the tab
    assert (
        api.get(f"/api/tasks/{task['id']}/comments").json() == []
    )  # the card did not get the comment
    run = api.get("/api/runs").json()[0]
    row.locator(".history-row__open").click()
    expect(page).to_have_url(
        f"{base_url}/artifacts/{task['number']}/executions/{run['execution_id']}"
    )
    expect(page.locator("[data-head-dry]")).to_be_visible()
    assert (
        api.get(f"/api/tasks/{task['id']}").json()["pipeline_id"] is None
    )  # the card keeps its own target


def test_the_tab_lists_the_latest_dry_runs_newest_first_with_a_link_to_all_of_them(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline, _ = _commenting_pipeline(api)
    post(api, "/api/tasks", title="Test card", status="backlog")
    panel = _dry_run_tab(_open_trigger(page, base_url, api, pipeline))
    _choose_card(page, panel, "Test")
    start = panel.get_by_role("button", name="Start dry run")
    for n in range(1, 7):
        start.click()
        expect(panel.locator(f'.history-row:has([data-row-number]:text-is("#{n}"))')).to_have_count(
            1
        )
        expect(panel.locator(".history-chip", has_text="Running")).to_have_count(0)
    numbers = panel.locator(".ge-dry__runs [data-row-number]")
    expect(numbers).to_have_text(["#6", "#5", "#4", "#3", "#2"])  # the five newest
    expect(panel.get_by_role("link", name="All dry runs in the history")).to_have_attribute(
        "href", "/executions?dry_run=only"
    )


def test_a_missing_required_input_is_said_in_plain_words_before_and_after_the_click(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline, _ = _commenting_pipeline(api)
    _inputs(api, pipeline, [{"name": "who", "type": "text", "required": True, "description": ""}])
    post(api, "/api/tasks", title="Test card", status="backlog")
    panel = _dry_run_tab(_open_trigger(page, base_url, api, pipeline))
    _choose_card(page, panel, "Test")
    expect(panel.locator(".ge-dry__check")).to_contain_text("This would not start")
    expect(panel.locator(".ge-dry__check")).to_contain_text("who")
    panel.get_by_role("button", name="Start dry run").click()
    expect(panel.get_by_role("alert").filter(has_text="who")).to_be_visible()
    panel.get_by_label("who").fill("Ann")
    expect(panel.locator(".ge-dry__check")).to_have_text("Nothing in the way.")


def test_while_the_emergency_stop_is_on_the_start_is_locked_with_its_reason(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline, _ = _commenting_pipeline(api)
    post(api, "/api/tasks", title="Test card", status="backlog")
    api.put("/api/settings/personal", json={"show_stop_switch": True}).raise_for_status()
    api.put("/api/settings/stop", json={"active": True}).raise_for_status()
    panel = _dry_run_tab(_open_trigger(page, base_url, api, pipeline))
    _choose_card(page, panel, "Test")
    start = panel.get_by_role("button", name="Start dry run")
    expect(start).to_be_disabled()
    expect(start).to_have_attribute("title", "The emergency stop is on")
    api.put("/api/settings/stop", json={"active": False}).raise_for_status()
    expect(start).to_be_enabled()


def test_an_action_that_no_pipeline_places_says_so_and_one_that_is_placed_runs(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    loose = build_definition(api, "Loose", output="pass")
    post(api, "/api/tasks", title="Test card", status="backlog")
    panel = _dry_run_tab(_open_trigger(page, base_url, api, loose, "actions"))
    expect(panel.get_by_text("Place this action in a pipeline to run it").first).to_be_visible()
    expect(panel.get_by_role("button", name="Start dry run")).to_be_disabled()
    _, placed = _commenting_pipeline(api)
    panel = _dry_run_tab(_open_trigger(page, base_url, api, placed, "actions"))
    _choose_card(page, panel, "Test")
    panel.get_by_role("button", name="Start dry run").click()
    expect(panel.locator(".ge-dry__runs .history-flag")).to_have_text("Dry run")
    eventually(lambda: api.get("/api/runs").json()[0]["dry_run"], True)


def test_on_a_narrow_screen_the_tab_is_stacked_and_does_not_scroll_sideways(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline, _ = _commenting_pipeline(api)
    _inputs(api, pipeline, [{"name": "who", "type": "text", "required": True, "description": ""}])
    post(api, "/api/tasks", title="Test card", status="backlog")
    page.set_viewport_size({"width": 390, "height": 800})
    panel = _dry_run_tab(_open_trigger(page, base_url, api, pipeline))
    scrolls = panel.evaluate(
        "el => el.closest('dialog').scrollWidth > el.closest('dialog').clientWidth + 1"
    )
    assert scrolls is False
