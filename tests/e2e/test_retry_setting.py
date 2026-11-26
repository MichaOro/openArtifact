"""Retry on fail in the node dialog (ADR-073, ADR-074): the setting row, the units of the wait, and a bin that never lies over its control."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import add_setting, eventually, pick_node
from tests.helpers import graph_url


def _code_node_dialog(page: Page, base_url: str, api: httpx.Client) -> dict[str, Any]:
    definition: dict[str, Any] = api.post("/api/actions", json={"name": "Retry check"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.click("[data-add-menu]")
    pick_node(page, "code")
    node = page.locator(".ge-node--code")
    expect(node).to_have_count(1)
    node.dblclick(position={"x": 30, "y": 5})
    expect(page.locator("#node-modal")).to_be_visible()
    return definition


def _retry(api: httpx.Client, definition: dict[str, Any]) -> Any:
    node = next(n for n in api.get(graph_url(definition)).json()["nodes"] if n["kind"] == "code")
    return node["config"].get("retry")


def _row(page: Page) -> Locator:
    return page.locator('#node-modal .ge-optional[data-setting="retry"]')


def test_an_added_retry_starts_on_with_the_defaults_and_stores_them(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _code_node_dialog(page, base_url, api)
    assert _retry(api, definition) is None  # a node that never asked for it does not retry
    add_setting(page, "Retry on fail")
    row = _row(page)
    expect(row.get_by_role("switch")).to_have_attribute("aria-checked", "true")
    expect(row.get_by_label("Max. tries")).to_have_value("3")
    expect(row.locator(".duration-input input")).to_have_value("1")
    expect(row.locator(".duration-input select")).to_have_value("sec")
    eventually(
        lambda: _retry(api, definition), {"enabled": True, "max_tries": 3, "wait_ms": 1000}
    )  # stored at once: a row that says On and holds nothing would lie


def test_the_wait_is_typed_in_a_unit_and_kept_in_milliseconds(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _code_node_dialog(page, base_url, api)
    add_setting(page, "Retry on fail")
    row = _row(page)
    number, unit = row.locator(".duration-input input"), row.locator(".duration-input select")
    number.fill("90")
    number.press("Enter")
    eventually(lambda: (_retry(api, definition) or {}).get("wait_ms"), 90000)
    unit.select_option(
        "min"
    )  # the number stays, the unit is what the person means: 90 minutes is too long
    expect(row.get_by_role("alert")).to_contain_text("from 0 to 10 min")
    assert _retry(api, definition)["wait_ms"] == 90000  # refused: nothing was sent
    number.fill("2")
    number.press("Enter")
    eventually(lambda: _retry(api, definition)["wait_ms"], 120000)
    number.fill("3467")
    unit.select_option("ms")
    eventually(lambda: _retry(api, definition)["wait_ms"], 3467)
    page.keyboard.press("Escape")
    page.reload()
    page.locator(".ge-node--code").dblclick(position={"x": 30, "y": 5})
    expect(_row(page).locator(".duration-input input")).to_have_value(
        "3467"
    )  # 3467 ms stays 3467 ms
    expect(_row(page).locator(".duration-input select")).to_have_value("ms")


def test_a_wrong_number_of_tries_says_why_and_is_not_sent(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _code_node_dialog(page, base_url, api)
    add_setting(page, "Retry on fail")
    tries = _row(page).get_by_label("Max. tries")
    eventually(lambda: _retry(api, definition) is not None, True)
    tries.fill("1")
    tries.press("Enter")
    expect(_row(page).get_by_role("alert")).to_contain_text("a whole number from 2 to 10")
    assert _retry(api, definition)["max_tries"] == 3
    tries.fill("5")
    tries.press("Enter")
    eventually(lambda: _retry(api, definition)["max_tries"], 5)
    expect(_row(page).get_by_role("alert")).to_be_hidden()


def test_off_hides_the_numbers_keeps_them_and_the_bin_takes_the_setting_away(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _code_node_dialog(page, base_url, api)
    add_setting(page, "Retry on fail")
    row = _row(page)
    row.get_by_label("Max. tries").fill("4")
    row.get_by_label("Max. tries").press("Enter")
    eventually(lambda: (_retry(api, definition) or {}).get("max_tries"), 4)
    row.get_by_role("switch").click()
    expect(row.get_by_label("Max. tries")).to_be_hidden()
    eventually(lambda: _retry(api, definition), {"enabled": False, "max_tries": 4, "wait_ms": 1000})
    row.get_by_role("switch").click()
    expect(row.get_by_label("Max. tries")).to_have_value(
        "4"
    )  # the number was kept while it was off
    row.locator(".ge-optional__remove").click()
    eventually(lambda: _retry(api, definition), None)
    expect(_row(page)).to_have_count(0)
    page.locator("#node-modal").get_by_role("button", name="Add setting").click()
    expect(page.get_by_role("menuitem", name="Retry on fail")).to_be_visible()  # offered again


def test_the_bin_of_a_setting_never_lies_over_its_control(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    """The overlap the owner saw: the select of 'If the node fails' and its bin. Every removable setting is one row: control, then bin."""
    _code_node_dialog(page, base_url, api)
    add_setting(page, "If the node fails")
    add_setting(page, "Retry on fail")
    for key in ("on_failure", "retry"):
        row = page.locator(f'#node-modal .ge-optional[data-setting="{key}"]')
        expect(row).to_be_visible()
        control = row.locator(".field__control, .ge-switch").first.bounding_box()
        bin_ = row.locator(".ge-optional__remove").bounding_box()
        assert control is not None and bin_ is not None, key
        assert control["x"] + control["width"] <= bin_["x"] + 0.5, (
            f"{key}: the bin lies over its control"
        )
        centre = bin_["y"] + bin_["height"] / 2
        assert control["y"] <= centre <= control["y"] + control["height"], (
            f"{key}: the bin is not on the control's line"
        )
    select = page.locator('#node-modal .ge-optional[data-setting="on_failure"] select')
    box = select.bounding_box()
    assert box is not None and box["width"] > 80, "the select gave way to the bin but stays usable"
