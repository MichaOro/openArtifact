"""The Execute Command node (ADR-075): its name, its output limit with a unit, and the notice on an instance that has it switched off."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.conftest import _serve
from tests.e2e.helpers import add_setting, eventually, pick_node
from tests.helpers import graph_url


def _open_editor(page: Page, url: str, client: httpx.Client) -> dict[str, Any]:
    definition: dict[str, Any] = client.post(
        "/api/actions", json={"name": "Execute Command check"}
    ).json()
    page.goto(f"{url}/actions/{definition['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    return definition


def _node_dialog(page: Page) -> None:
    page.locator(".ge-node--code").dblclick(position={"x": 30, "y": 5})
    expect(page.locator("#node-modal")).to_be_visible()


def _limit(api: httpx.Client, definition: dict[str, Any]) -> Any:
    node = next(n for n in api.get(graph_url(definition)).json()["nodes"] if n["kind"] == "code")
    return node["config"].get("output_limit_bytes")


def _row(page: Page) -> Locator:
    return page.locator('#node-modal .ge-optional[data-setting="output_limit_bytes"]')


def test_the_menu_and_the_node_say_execute_command(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _open_editor(page, base_url, api)
    page.click("[data-add-menu]")
    page.fill(".ge-add__search", "Execute")
    entry = page.locator("[data-add=code]")
    expect(entry).to_contain_text("Execute Command")  # not "Code": it is no sandbox
    expect(entry.locator(".tag")).to_have_count(
        0
    )  # on this instance the kind is switched on, so nothing says "Switched off"
    entry.click()
    expect(page.locator(".ge-node--code")).to_contain_text("Execute Command")


def test_the_output_limit_is_typed_in_a_unit_and_kept_in_bytes(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open_editor(page, base_url, api)
    page.click("[data-add-menu]")
    pick_node(page, "code")
    _node_dialog(page)
    assert (
        _limit(api, definition) is None
    )  # a node that never asked for it uses the limit of the instance
    add_setting(page, "Output limit")
    row = _row(page)
    number, unit = row.locator(".size-input input"), row.locator(".size-input select")
    expect(number).to_have_value("64")
    expect(unit).to_have_value("KiB")
    eventually(
        lambda: _limit(api, definition), 65536
    )  # stored at once: a row that shows a value and holds nothing would lie
    number.fill("2")
    unit.select_option("MiB")
    eventually(lambda: _limit(api, definition), 2097152)
    number.fill("70")  # more than the 64 MiB a node may ask for
    number.press("Enter")
    expect(row.get_by_role("alert")).to_contain_text("from 1 KiB to 64 MiB")
    assert _limit(api, definition) == 2097152  # refused: nothing was sent
    number.fill("1500")
    unit.select_option("B")
    eventually(lambda: _limit(api, definition), 1500)
    page.keyboard.press("Escape")
    page.reload()
    _node_dialog(page)
    expect(_row(page).locator(".size-input input")).to_have_value(
        "1500"
    )  # 1500 bytes stay 1500 B, nobody converts
    expect(_row(page).locator(".size-input select")).to_have_value("B")
    _row(page).locator(".ge-optional__remove").click()
    eventually(
        lambda: _limit(api, definition), None
    )  # the bin takes the setting away: the instance's limit applies again


@pytest.fixture(scope="module")
def off_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """An application that has Execute Command nodes switched off (the default of the environment)."""
    data: Path = tmp_path_factory.mktemp("execute-command-off")
    yield from _serve(data, code_nodes_enabled="false")


def test_a_switched_off_instance_says_so_and_the_node_stays_editable(
    page: Page, off_url: str
) -> None:
    with httpx.Client(base_url=off_url) as client:
        definition = _open_editor(page, off_url, client)
        page.click("[data-add-menu]")
        page.fill(".ge-add__search", "Execute")
        expect(page.locator("[data-add=code] .tag")).to_have_text("Switched off")
        page.click("[data-add=code]")  # still addable: existing nodes and new ones stay editable
        _node_dialog(page)
        notice = page.locator("#node-modal .ge-switched-off")
        expect(notice).to_contain_text("switched off on this instance")
        expect(notice).to_contain_text("OPENARTIFACT_CODE_NODES_ENABLED=true")
        page.locator("#node-modal").get_by_label("Language", exact=True).select_option("python")
        eventually(
            lambda: next(
                n for n in client.get(graph_url(definition)).json()["nodes"] if n["kind"] == "code"
            )["config"]["language"],
            "python",
        )
