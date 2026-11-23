"""The canonical settings dialog of a node (ADR-053): Definition and Behaviour columns, optional settings added on request,
advanced settings folded, and nothing drawn for what a kind does not have."""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import add_setting, eventually, pick_node
from tests.helpers import graph_url


def _open(page: Page, base_url: str, api: httpx.Client, kind: str) -> Any:
    definition = api.post("/api/actions", json={"name": "Settings"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.click("[data-add-menu]")
    pick_node(page, kind)
    page.locator(f".ge-node--{kind}").dblclick(position={"x": 30, "y": 5})
    expect(page.locator("#node-modal")).to_be_visible()
    return definition


def _config(api: httpx.Client, definition: Any, kind: str) -> dict[str, Any]:
    nodes = api.get(graph_url(definition)).json()["nodes"]
    return next(n["config"] for n in nodes if n["kind"] == kind)  # type: ignore[no-any-return]


def test_a_node_with_a_definition_and_a_behaviour_gets_two_columns(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _open(page, base_url, api, "http")
    dialog = page.locator("#node-modal")
    settings = dialog.locator(".ge-settings")
    expect(settings).to_have_attribute("data-columns", "2")
    expect(dialog).to_have_class(re.compile(r"is-wide"))
    definition = settings.locator('.ge-settings__column[data-section="definition"]')
    behaviour = settings.locator('.ge-settings__column[data-section="behaviour"]')
    for label in ("Method", "URL", "Headers", "Body"):
        expect(definition.get_by_label(label, exact=True)).to_be_visible()
    expect(
        behaviour.get_by_label("If the node fails")
    ).to_be_visible()  # the shared failure setting is Behaviour
    expect(behaviour.get_by_label("Timeout (seconds)", exact=True)).to_have_count(
        0
    )  # optional: not shown yet
    expect(settings.locator(".ge-settings__title")).to_have_text(["Definition", "Behaviour"])
    d, b = definition.bounding_box(), behaviour.bounding_box()
    assert (
        d and b and abs(d["y"] - b["y"]) < 2 and b["x"] > d["x"] + d["width"] - 2
    )  # side by side, same top


def test_the_columns_stack_when_the_dialog_is_narrow(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.set_viewport_size({"width": 700, "height": 900})
    _open(page, base_url, api, "http")
    settings = page.locator("#node-modal .ge-settings")
    d = settings.locator('.ge-settings__column[data-section="definition"]').bounding_box()
    b = settings.locator('.ge-settings__column[data-section="behaviour"]').bounding_box()
    assert d and b and b["y"] >= d["y"] + d["height"] - 2  # Behaviour below Definition
    assert page.evaluate("document.documentElement.scrollWidth") <= 700  # nothing scrolls sideways


def test_a_node_without_behaviour_has_one_column_and_no_empty_section(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _open(page, base_url, api, "if")
    settings = page.locator("#node-modal .ge-settings")
    expect(settings).to_have_attribute("data-columns", "1")
    expect(settings.locator(".ge-settings__column")).to_have_count(1)
    expect(settings.locator(".ge-settings__title")).to_have_count(
        0
    )  # no headings for a single column
    expect(page.locator("#node-modal")).not_to_have_class(re.compile(r"is-wide"))
    expect(settings.get_by_text("Add setting")).to_have_count(0)  # nothing optional, no empty menu


def test_an_optional_setting_is_added_kept_and_taken_away(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open(page, base_url, api, "http")
    dialog = page.locator("#node-modal")
    add_setting(page, "Timeout (seconds) · default 30")  # the menu says what applies meanwhile
    timeout = dialog.get_by_label("Timeout (seconds)", exact=True)
    expect(timeout).to_have_attribute("placeholder", "30")  # the default shows grey
    expect(timeout).to_have_value("")
    timeout.fill("12")
    timeout.press("Enter")
    eventually(lambda: _config(api, definition, "http")["timeout_seconds"], 12)

    page.keyboard.press("Escape")  # reopened: a configured optional setting is there without asking
    page.locator(".ge-node--http").dblclick(position={"x": 30, "y": 5})
    expect(dialog.get_by_label("Timeout (seconds)", exact=True)).to_have_value("12")
    expect(dialog.get_by_role("button", name="Add setting")).to_have_count(0)  # nothing left to add

    dialog.get_by_role(
        "button", name="Use the default again: Timeout (seconds)"
    ).click()  # not set again, the default applies
    eventually(lambda: _config(api, definition, "http")["timeout_seconds"], 30)
    expect(dialog.get_by_label("Timeout (seconds)", exact=True)).to_have_count(0)
    add_setting(page, "Timeout (seconds)")  # offered again

    page.keyboard.press("Escape")  # added but never given a value: not kept
    page.locator(".ge-node--http").dblclick(position={"x": 30, "y": 5})
    expect(dialog.get_by_label("Timeout (seconds)", exact=True)).to_have_count(0)


def test_advanced_settings_are_folded_and_open_while_one_is_set(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open(page, base_url, api, "http")
    dialog = page.locator("#node-modal")
    advanced = dialog.locator('.ge-advanced[data-section="behaviour"]')
    expect(advanced).not_to_have_attribute(
        "open", ""
    )  # closed: the accepted status codes are advanced
    expect(dialog.get_by_label("Success status")).to_be_hidden()
    advanced.locator("summary").click()
    status = dialog.get_by_label("Success status")
    status.fill("200, 404")
    status.press("Enter")
    eventually(lambda: _config(api, definition, "http")["success_status"], "200, 404")

    page.keyboard.press("Escape")
    page.locator(".ge-node--http").dblclick(position={"x": 30, "y": 5})
    expect(dialog.locator('.ge-advanced[data-section="behaviour"]')).to_have_attribute(
        "open", ""
    )  # a set value is never hidden
    expect(dialog.get_by_label("Success status")).to_have_value("200, 404")


def test_a_code_node_keeps_its_secrets_in_advanced_and_its_timeout_optional(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _open(page, base_url, api, "code")
    dialog = page.locator("#node-modal")
    expect(dialog.locator('.ge-advanced[data-section="definition"] summary')).to_have_text(
        "Advanced"
    )
    expect(dialog.get_by_label("Secrets")).to_be_hidden()
    expect(
        dialog.locator(".ge-settings__column[data-section=behaviour]").get_by_label(
            "If the node fails"
        )
    ).to_be_visible()
    expect(dialog.get_by_role("button", name="Add setting")).to_have_count(1)


def test_a_timer_has_a_single_column_with_its_one_setting(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _open(page, base_url, api, "timer")
    settings = page.locator("#node-modal .ge-settings")
    expect(settings).to_have_attribute("data-columns", "1")
    expect(settings.get_by_label("Seconds")).to_be_visible()
