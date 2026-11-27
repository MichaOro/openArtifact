"""The Mock tab of a node's window (ADR-087): the switch, the form, the pin on the card, and the test cases of the Trigger. Narrow tests of one window: what a
mock does in a run is the server's and is tested in tests/test_mock_data.py."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import echo_pipeline, execution_of, flow_url, run_started
from tests.e2e.test_dry_run_tab import (
    DIALOG,
    _commenting_pipeline,
    _dry_run_tab,
    _inputs,
    _open_trigger,
)
from tests.helpers import graph_url, kind_of


def _open_comment_node(page: Page, base_url: str, definition: dict[str, Any]) -> Any:
    page.goto(f"{base_url}/actions/{definition['slug']}")
    page.locator(".ge-node--artifact").dblclick(position={"x": 30, "y": 5})
    dialog = page.locator(DIALOG)
    expect(dialog).to_be_visible()
    return dialog


def _stored_mock(api: httpx.Client, definition: dict[str, Any]) -> Any:
    nodes = api.get(graph_url(definition)).json()["nodes"]
    return next(n for n in nodes if n["kind"] == "artifact")["mock"]


def test_the_window_of_a_node_has_a_mock_tab_and_a_pencil_that_opens_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _, definition = _commenting_pipeline(api)
    dialog = _open_comment_node(page, base_url, definition)
    expect(dialog.get_by_role("tab")).to_have_text(["Settings", "Mock"])
    expect(dialog.get_by_role("tab", name="Settings")).to_have_attribute("aria-selected", "true")
    dialog.get_by_role("button", name="Mock data").click()
    expect(dialog.get_by_role("tab", name="Mock")).to_have_attribute("aria-selected", "true")
    expect(dialog.locator("[data-mock-panel]")).to_be_visible()


def test_a_mock_is_saved_while_it_is_typed_and_the_card_gets_a_pin(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _, definition = _commenting_pipeline(api)
    dialog = _open_comment_node(page, base_url, definition)
    dialog.get_by_role("button", name="Mock data").click()
    panel = dialog.locator("[data-mock-panel]")
    panel.get_by_label("Output").fill("created #77")
    panel.get_by_label("Output").blur()
    panel.get_by_label("Data (JSON)").fill('{"id": 77}')
    panel.get_by_label("Data (JSON)").blur()
    panel.get_by_role("switch", name="Mock active").click()
    expect(page.locator(".ge-node--artifact [data-mock-pin]")).to_have_attribute(
        "title", "Mock active: the dry run uses a stored result"
    )
    assert _stored_mock(api, definition) == {
        "enabled": True,
        "outcome": "pass",
        "output": "created #77",
        "data": {"id": 77},
        "reason": "",
    }
    page.reload()
    expect(page.locator(".ge-node--artifact [data-mock-pin]")).to_be_visible()


def test_data_that_is_not_json_is_told_in_a_plain_line_and_nothing_is_saved(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _, definition = _commenting_pipeline(api)
    dialog = _open_comment_node(page, base_url, definition)
    dialog.get_by_role("button", name="Mock data").click()
    panel = dialog.locator("[data-mock-panel]")
    panel.get_by_label("Data (JSON)").fill("{id: 7")
    panel.get_by_label("Data (JSON)").blur()
    expect(panel.get_by_role("alert")).to_have_text(
        "The data is not valid JSON. Nothing was saved."
    )
    assert _stored_mock(api, definition) is None


def test_the_pin_opens_the_window_at_the_mock_tab(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _, definition = _commenting_pipeline(api)
    node_id = next(
        n for n in api.get(graph_url(definition)).json()["nodes"] if n["kind"] == "artifact"
    )["id"]
    api.patch(
        f"{graph_url(definition)}/nodes/{node_id}",
        json={"mock": {"enabled": True, "output": "x"}},
    ).raise_for_status()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    page.locator(".ge-node--artifact [data-mock-pin]").click()
    dialog = page.locator(DIALOG)
    expect(dialog.get_by_role("tab", name="Mock")).to_have_attribute("aria-selected", "true")


def test_a_test_case_fills_the_inputs_and_is_kept_in_the_draft(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline, _ = _commenting_pipeline(api)
    _inputs(api, pipeline, [{"name": "amount", "type": "text", "required": False, "default": ""}])
    dialog = _open_trigger(page, base_url, api, pipeline)
    panel = _dry_run_tab(dialog)
    panel.get_by_label("amount").fill("5000")
    panel.get_by_label("Name of the test case").fill("Big order")
    panel.get_by_role("button", name="Save as test case").click()
    expect(panel.get_by_label("Test case", exact=True)).to_have_value("Big order")
    trigger = kind_of(api, pipeline, "trigger")
    stored = next(
        n for n in api.get(graph_url(pipeline)).json()["nodes"] if n["id"] == trigger["id"]
    )
    assert stored["cases"] == [{"name": "Big order", "inputs": {"amount": "5000"}}]
    panel.get_by_label("amount").fill("1")
    panel.get_by_label("Test case", exact=True).select_option("")
    panel.get_by_label("Test case", exact=True).select_option("Big order")
    expect(panel.get_by_label("amount")).to_have_value("5000")


def test_keep_as_mock_in_the_flow_sets_the_result_of_a_real_step_as_the_mock_of_the_draft(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = echo_pipeline(api, "kept text")
    task: dict[str, Any] = api.post("/api/tasks", json={"title": "Item"}).json()
    run_started(api, task, pipeline)
    page.goto(flow_url(base_url, task, execution_of(api, task)))
    page.locator('.ge-node[aria-label^="Action"]').dblclick()
    page.locator('.ge-node[aria-label^="Execute Command: echo"]').click()
    page.get_by_role("button", name="Keep as mock").click()
    expect(page.get_by_text("Set as the mock of this node in the draft.")).to_be_visible()
    definition = api.get("/api/actions").json()
    code_node = next(
        n
        for d in definition
        for n in api.get(f"/api/actions/{d['id']}").json()["nodes"]
        if n["kind"] == "code" and n["mock"]
    )
    assert code_node["mock"]["enabled"] is True
    assert code_node["mock"]["output"].strip() == "kept text"
