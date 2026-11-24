"""In the browser: the Edit Fields node, the operators of Switch cases and Settings > Run limits."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import eventually
from tests.e2e.test_execution_nodes import _add, _config, _open_action, _select


def test_an_edit_fields_node_is_added_and_its_fields_are_saved(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open_action(page, base_url, api)
    card = _add(page, "set")
    expect(card.locator(".ge-node__kind")).to_have_text("no field yet")
    inspector = page.locator(".ge-inspector")  # _add opened the node's settings
    fields = inspector.get_by_label("Fields", exact=True)
    fields.fill("priority = high\nscore = ${var.points}")
    fields.blur()  # a text is saved when the field is left (persist-policy.js)
    _config(api, definition, "set", fields="priority = high\nscore = ${var.points}")
    expect(card.locator(".ge-node__kind")).to_have_text("priority, score")
    inspector.get_by_label("Value types").select_option("detect")
    _config(api, definition, "set", value_types="detect")
    fields.fill("Bad = 1")
    fields.blur()
    expect(inspector.get_by_role("alert").filter(has_text="is not a variable name")).to_be_visible()
    _config(
        api, definition, "set", fields="priority = high\nscore = ${var.points}"
    )  # refused: kept


def test_a_switch_case_gets_an_operator_and_its_port_follows_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open_action(page, base_url, api)
    card = _add(page, "switch")
    inspector = _select(page, "switch")
    expect(card.locator('[data-port="case_1"]')).to_be_hidden()  # unused: no output
    inspector.get_by_label("Value", exact=True).fill("${var.score}")
    inspector.get_by_label("Value", exact=True).press("Enter")
    case_1 = inspector.locator('details[data-group="Case 1"]')
    case_1.get_by_label("Operator").select_option("is empty")
    _config(api, definition, "switch", case_operator_1="is empty")
    expect(card.locator('[data-port="case_1"]')).to_have_count(
        1
    )  # needs no value: the output is there
    case_1.get_by_label("Operator").select_option("greater than")
    case_1.get_by_label("Compare with").fill("10")
    case_1.get_by_label("Compare with").press("Enter")
    _config(api, definition, "switch", case_operator_1="greater than", case_1="10")
    expect(card.locator('[data-port="case_1"]')).to_have_attribute(
        "data-label", "> 10"
    )  # labelled with the rule


def test_run_limits_are_shown_changed_and_refused_outside_their_bounds(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    api.put("/api/settings/run-limits", json={"max_steps": 1000, "time_limit_minutes": 0})
    page.goto(f"{base_url}/settings/run-limits")
    steps = page.get_by_label("Steps per execution")
    minutes = page.get_by_label("Time limit per execution")
    save = page.locator("[data-submit]")
    expect(steps).to_have_value("1000")
    expect(minutes).to_have_value("0")
    expect(page.locator('.nav-link[aria-current="page"]')).to_have_text("Run limits")
    expect(save).to_be_disabled()  # nothing changed yet
    steps.fill("250")
    minutes.fill("15")
    save.click()
    expect(page.locator("[data-status]")).to_contain_text("Saved")
    limits: dict[str, Any] = api.get("/api/settings/run-limits").json()
    assert (limits["max_steps"], limits["time_limit_minutes"]) == (250, 15)
    steps.fill("5")
    save.click()
    expect(page.locator("[data-form-error]")).to_be_visible()
    eventually(lambda: api.get("/api/settings/run-limits").json()["max_steps"], 250)
    api.put("/api/settings/run-limits", json={"max_steps": 1000, "time_limit_minutes": 0})
