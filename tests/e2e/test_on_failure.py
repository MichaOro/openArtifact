"""If a node or an action fails (ADR-061): the setting has three values, and the error output is there only with the third."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import add_action, eventually, pick_node
from tests.helpers import graph_url

FAIL_LABEL = "If the node fails"


def _action_with_code(
    page: Page, base_url: str, api: httpx.Client
) -> tuple[dict[str, Any], Locator]:
    definition: dict[str, Any] = api.post("/api/actions", json={"name": "Check"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.click("[data-add-menu]")
    pick_node(page, "code")
    node = page.locator(".ge-node--code")
    expect(node).to_have_count(1)
    return definition, node


def _stored(api: httpx.Client, graph: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(n for n in api.get(graph_url(graph)).json()["nodes"] if n["kind"] == kind)


def test_the_error_output_of_a_node_is_there_only_with_the_third_value(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition, code = _action_with_code(page, base_url, api)
    expect(code.locator(".ge-port--pass")).to_be_visible()
    expect(code.locator(".ge-port--fail")).to_be_hidden()  # the default: stop the run
    code.dblclick(position={"x": 30, "y": 5})
    dialog = page.locator("#node-modal")
    setting = dialog.get_by_label(FAIL_LABEL)
    expect(setting.locator("option")).to_have_text(["Stop the run", "Continue", "Error output"])
    expect(setting).to_have_value("fail")
    setting.select_option(label="Continue")
    eventually(lambda: _stored(api, definition, "code")["config"]["on_failure"], "continue")
    expect(code.locator(".ge-port--fail")).to_be_hidden()  # Continue goes on through On Pass
    setting.select_option(label="Error output")
    eventually(lambda: _stored(api, definition, "code")["config"]["on_failure"], "error_output")
    expect(code.locator(".ge-port--fail")).to_be_visible()
    expect(code.locator(".ge-port--fail")).to_have_attribute("data-label", "On Fail")


def test_the_error_output_stays_while_a_connection_uses_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition, code = _action_with_code(page, base_url, api)
    code.dblclick(position={"x": 30, "y": 5})
    dialog = page.locator("#node-modal")
    dialog.get_by_label(FAIL_LABEL).select_option(label="Error output")
    eventually(lambda: _stored(api, definition, "code")["config"]["on_failure"], "error_output")
    # a connection from the error output (made as the editor does it: through the API)
    output = _stored(api, definition, "output")
    api.patch(f"{graph_url(definition)}/nodes/{output['id']}", json={"fail_enabled": True})
    api.post(
        f"{graph_url(definition)}/edges",
        json={
            "source_id": _stored(api, definition, "code")["id"],
            "source_port": "fail",
            "target_id": output["id"],
            "target_port": "fail",
        },
    ).raise_for_status()
    page.keyboard.press("Escape")
    page.reload()
    expect(page.locator(".ge-edge--fail")).to_have_count(1)
    page.locator(".ge-node--code").dblclick(position={"x": 30, "y": 5})
    setting = page.locator("#node-modal").get_by_label(FAIL_LABEL)
    setting.select_option(label="Stop the run")
    # refused, said plainly, and nothing changed
    expect(page.locator("#node-modal")).to_contain_text("remove that connection first")
    assert _stored(api, definition, "code")["config"]["on_failure"] == "error_output"
    expect(page.locator(".ge-node--code .ge-port--fail")).to_be_visible()
    expect(page.locator(".ge-edge--fail")).to_have_count(1)


def test_an_action_has_the_setting_and_its_error_output_follows_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = api.post("/api/pipelines", json={"name": "Flow"}).json()
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    expect(page.locator(".ge-node--trigger")).to_be_visible()
    page.click("[data-add-menu]")
    pick_node(page, "stage")
    expect(page.locator(".ge-node--stage")).to_have_count(1)
    add_action(page)
    action = page.locator(".ge-node--action").first
    expect(action).to_be_visible()
    expect(action.locator(".ge-port--pass")).to_be_visible()
    expect(action.locator(".ge-port--error")).to_be_hidden()  # the default: stop the run
    action.click(button="right", position={"x": 30, "y": 5})
    page.get_by_role("menuitem", name="Settings").click()
    dialog = page.locator("#node-modal")
    setting = dialog.get_by_label("If the action fails")
    expect(setting.locator("option")).to_have_text(["Stop the run", "Continue", "Error output"])
    setting.select_option(label="Error output")
    expect(action.locator(".ge-port--error")).to_be_visible()
    expect(action.locator(".ge-port--error")).to_have_attribute("data-label", "On Error")
    setting.select_option(label="Continue")
    expect(action.locator(".ge-port--error")).to_be_hidden()


def test_the_setting_speaks_german(page: Page, base_url: str, api: httpx.Client) -> None:
    page.context.add_cookies([{"name": "oa_lang", "value": "de", "url": base_url}])
    _definition, code = _action_with_code(page, base_url, api)
    code.dblclick(position={"x": 30, "y": 5})
    setting = page.locator("#node-modal").get_by_label("Wenn der Node fehlschlägt")
    expect(setting.locator("option")).to_have_text(["Lauf stoppen", "Fortfahren", "Fehlerausgang"])
