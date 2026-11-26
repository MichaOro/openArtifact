"""Rearranging the windows that are YAML manifests (ADR-063): the handle on the top edge, its menu, the arrange mode with
grips and a banner, moving a section or a field by pointer and by key, saving into the instance's layout layer, discarding,
resetting and exporting; only manifest windows have the handle."""

from __future__ import annotations

from typing import Any, cast

import httpx
import yaml
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import drag, pick_node
from tests.e2e.test_guards import _guard, _window

GUARD = "/api/ui-layouts/forms/guard"


def _boxes(*locators: Locator) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for el in locators:
        box = el.bounding_box()
        assert box is not None
        out.append(cast(dict[str, float], box))
    return out


def _settled(page: Page, locator: Locator) -> dict[str, float]:
    last: dict[str, float] = {}
    for _ in range(60):
        (now,) = _boxes(locator)
        if now == last:
            return now
        last = now
        page.wait_for_timeout(50)
    return last


def _guard_window(page: Page, base_url: str, api: httpx.Client) -> Locator:
    guard = _guard(api, "Layout guard")
    page.goto(f"{base_url}/guards?open={guard['id']}")
    window = _window(page)
    expect(window.locator("[data-form='guard']")).to_be_visible()
    return cast(Locator, window)


def _node_window(page: Page, base_url: str, api: httpx.Client, kind: str = "http") -> Locator:
    definition = api.post("/api/actions", json={"name": f"Layout {kind}"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.click("[data-add-menu]")
    pick_node(page, kind)
    page.locator(f".ge-node--{kind}").dblclick(position={"x": 30, "y": 5})
    window = page.locator("#node-modal")
    expect(window).to_be_visible()
    expect(window.locator(".ge-settings")).to_be_visible()
    return window


def _menu(page: Page, window: Locator) -> Locator:
    window.locator("[data-layout-handle]").click()
    menu = page.locator(".menu--layout")
    expect(menu).to_be_visible()
    return menu


def _item(menu: Locator, name: str) -> Locator:
    return menu.get_by_role("menuitem", name=name)


def _reset(api: httpx.Client, window: str = GUARD) -> None:
    api.delete(window)


# ── the handle ────────────────────────────────────────────────────────


def test_the_handle_sits_on_the_top_edge_in_the_middle_of_a_manifest_window(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    window = _guard_window(page, base_url, api)
    panel = window.locator(".modal__panel")
    handle = window.locator("[data-layout-handle]")
    expect(handle).to_have_accessible_name("Window layout")
    expect(handle).to_have_attribute("title", "Layout of this window (defined as YAML)")
    _settled(page, panel)
    page.wait_for_timeout(
        350
    )  # the window scales in when it opens; both boxes are read after it stands still
    panel_box, handle_box = _boxes(panel, handle)
    assert (
        abs((handle_box["x"] + handle_box["width"] / 2) - (panel_box["x"] + panel_box["width"] / 2))
        < 3
    )
    assert (
        abs((handle_box["y"] + handle_box["height"] / 2) - panel_box["y"]) < 3
    )  # on the border line
    assert handle_box["height"] >= 24 and handle_box["width"] >= 24
    assert panel.locator("[data-layout-handle] svg circle").count() == 9  # the nine dots


def test_the_settings_window_of_a_node_has_the_handle_too(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    for kind in ("http", "code"):
        window = _node_window(page, base_url, api, kind)
        expect(window.locator("[data-layout-handle]")).to_be_visible()


def test_a_window_that_is_not_a_manifest_has_no_handle(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.goto(f"{base_url}/executions")
    page.get_by_role("button", name="Retention").click()
    expect(page.locator("#retention-modal, dialog[open]").first).to_be_visible()
    assert page.locator("[data-layout-handle]:visible").count() == 0


def test_its_menu_is_a_variant_of_its_own_and_offers_edit_reset_and_export(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    window = _guard_window(page, base_url, api)
    menu = _menu(page, window)
    expect(menu.locator(".menu__title")).to_have_text("Layout of this window")
    expect(_item(menu, "Edit layout")).to_be_visible()
    expect(_item(menu, "Export as YAML")).to_be_visible()
    expect(_item(menu, "Reset to default")).to_have_attribute(
        "aria-disabled", "true"
    )  # it is the shipped layout
    border = menu.evaluate("el => getComputedStyle(el).borderTopColor")
    default = page.evaluate(
        "() => getComputedStyle(document.documentElement).getPropertyValue('--layout-accent')"
    )
    assert default.strip() and border != "rgba(0, 0, 0, 0)"


# ── arranging ─────────────────────────────────────────────────────────


def test_edit_shows_dashed_sections_with_grips_a_banner_and_locks_the_form(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    window = _guard_window(page, base_url, api)
    _item(_menu(page, window), "Edit layout").click()
    arrange = window.locator(".lw-arrange")
    expect(arrange).to_be_visible()
    expect(window.locator(".lw-banner")).to_contain_text(
        "changes apply to every window of this kind"
    )
    expect(window.locator("[data-form='guard']")).to_be_hidden()  # the real form is out of the way
    sections = arrange.locator(".lw-section")
    assert sections.count() == 5
    for section in sections.all():
        assert section.evaluate("el => getComputedStyle(el).borderTopStyle") == "dashed"
        assert section.locator(".lw-grip").count() >= 2  # its own and one per field
    expect(arrange.locator("[data-section='trigger'] .lw-field")).to_have_count(5)
    expect(window.locator(".modal__footer")).to_have_attribute(
        "inert", ""
    )  # Save of the guard is locked while arranging
    menu = _menu(page, window)
    expect(_item(menu, "Save layout")).to_have_attribute(
        "aria-disabled", "true"
    )  # nothing changed yet
    expect(_item(menu, "Discard changes")).to_be_visible()


def test_a_section_is_dragged_to_the_other_column_and_saved(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    window = _guard_window(page, base_url, api)
    _item(_menu(page, window), "Edit layout").click()
    arrange = window.locator(".lw-arrange")
    source = arrange.locator("[data-section='escalation'] .lw-section__head .lw-grip")
    target = arrange.locator("[data-section='then']")
    drag(page, source, target.locator(".lw-fields").first)
    right = arrange.locator(".lw-lane[data-lane='1']")
    expect(right.locator("[data-section='escalation']")).to_have_count(1)
    expect(window.locator("[data-layout-handle]")).to_have_attribute("data-dirty", "")
    _item(_menu(page, window), "Save layout").click()
    expect(window.locator(".lw-arrange")).to_have_count(0)
    saved = api.get(GUARD).json()
    assert saved["customised"] is True
    column = next(s["column"] for s in saved["layout"]["sections"] if s["key"] == "escalation")
    assert column == 2
    # a fresh window (the page loaded again) draws it there
    guard = api.get("/api/guards").json()[0]
    page.goto(f"{base_url}/guards?open={guard['id']}")
    window = _window(page)
    escalation = window.locator("[data-form='guard'] [data-section='escalation']")
    then = window.locator("[data-form='guard'] [data-section='then']")
    e, th = _settled(page, escalation), _settled(page, then)
    assert abs(e["x"] - th["x"]) < 4  # the same column as Then now
    _reset(api)


def test_a_field_is_dragged_above_its_neighbour_by_the_pointer(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    window = _guard_window(page, base_url, api)
    _item(_menu(page, window), "Edit layout").click()
    shown = window.locator(".lw-arrange [data-section='trigger'] .lw-fields[data-list='shown']")
    source = shown.locator("[data-field='trigger.events'] .lw-grip")
    first = shown.locator("[data-field='trigger.type']")
    box = first.bounding_box()
    assert box is not None
    sx, sy = source.bounding_box()["x"] + 8, source.bounding_box()["y"] + 8  # type: ignore[index]
    page.mouse.move(sx, sy)
    page.mouse.down()
    page.mouse.move(box["x"] + 40, box["y"] + 2, steps=12)  # above the middle of the first field
    expect(window.locator(".lw-drop")).to_be_visible()  # the line shows where it will land
    page.mouse.up()
    expect(shown.locator(".lw-field").first).to_have_attribute("data-field", "trigger.events")
    expect(window.locator(".lw-drop")).to_have_count(0)
    expect(page.locator(".lw-ghost")).to_have_count(0)


def test_escape_cancels_a_drag_and_leaves_the_order_alone(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    window = _guard_window(page, base_url, api)
    _item(_menu(page, window), "Edit layout").click()
    shown = window.locator(".lw-arrange [data-section='trigger'] .lw-fields[data-list='shown']")
    source = shown.locator("[data-field='trigger.events'] .lw-grip").bounding_box()
    first = shown.locator("[data-field='trigger.type']").bounding_box()
    assert source and first
    page.mouse.move(source["x"] + 8, source["y"] + 8)
    page.mouse.down()
    page.mouse.move(first["x"] + 40, first["y"] + 2, steps=10)
    page.keyboard.press("Escape")
    page.mouse.up()
    expect(shown.locator(".lw-field").first).to_have_attribute("data-field", "trigger.type")
    expect(window).to_be_visible()  # the window did not close under the Escape of the drag


def test_a_field_moves_by_key_and_the_move_is_announced(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    window = _guard_window(page, base_url, api)
    _item(_menu(page, window), "Edit layout").click()
    arrange = window.locator(".lw-arrange")
    grip = arrange.locator("[data-section='trigger'] [data-field='trigger.events'] .lw-grip")
    grip.focus()
    page.keyboard.press("ArrowUp")
    keys = arrange.locator("[data-section='trigger'] .lw-fields[data-list='shown'] .lw-field")
    expect(keys.first).to_have_attribute("data-field", "trigger.events")
    expect(page.locator(".lw-arrange [role='status']")).to_contain_text("position 1")
    focused = page.evaluate("() => document.activeElement.dataset.gripKey")
    assert focused == "f:trigger:trigger.events"  # the grip keeps the focus through the redraw
    page.keyboard.press("Alt+ArrowDown")
    page.keyboard.press("Alt+ArrowDown")
    page.keyboard.press("Alt+ArrowDown")
    page.keyboard.press("Alt+ArrowDown")  # past the last shown field: into the folded group
    expect(
        arrange.locator(
            "[data-section='trigger'] .lw-fields[data-list='folded'] [data-field='trigger.events']"
        )
    ).to_have_count(0)  # required: stays
    _reset(api)


def test_a_field_is_folded_away_and_back_by_key(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    window = _guard_window(page, base_url, api)
    _item(_menu(page, window), "Edit layout").click()
    arrange = window.locator(".lw-arrange")
    grip = arrange.locator("[data-section='trigger'] [data-field='trigger.every_seconds'] .lw-grip")
    grip.focus()
    page.keyboard.press("ArrowDown")  # the next one is the folded group's first field
    folded = arrange.locator("[data-section='trigger'] .lw-fields[data-list='folded']")
    expect(folded.locator("[data-field='trigger.every_seconds']")).to_have_count(1)
    page.keyboard.press("ArrowUp")
    expect(
        arrange.locator(
            "[data-section='trigger'] .lw-fields[data-list='shown'] [data-field='trigger.every_seconds']"
        )
    ).to_have_count(1)
    _reset(api)


def test_discard_throws_the_arrangement_away(page: Page, base_url: str, api: httpx.Client) -> None:
    window = _guard_window(page, base_url, api)
    _item(_menu(page, window), "Edit layout").click()
    window.locator(".lw-arrange [data-section='escalation'] .lw-section__head .lw-grip").focus()
    page.keyboard.press("ArrowRight")
    expect(window.locator("[data-layout-handle]")).to_have_attribute("data-dirty", "")
    _item(_menu(page, window), "Discard changes").click()
    expect(window.locator(".lw-arrange")).to_have_count(0)
    expect(window.locator("[data-form='guard']")).to_be_visible()
    assert api.get(GUARD).json()["customised"] is False


def test_the_node_window_swaps_its_sides_and_other_nodes_of_the_kind_follow(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    window = _node_window(page, base_url, api, "http")
    _item(_menu(page, window), "Edit layout").click()
    grip = window.locator(".lw-arrange [data-section='behaviour'] .lw-section__head .lw-grip")
    grip.focus()
    page.keyboard.press("ArrowLeft")
    expect(
        window.locator(".lw-arrange .lw-lane[data-lane='0'] [data-section='behaviour']")
    ).to_have_count(1)
    _item(_menu(page, window), "Save layout").click()
    expect(window.locator(".lw-arrange")).to_have_count(0)
    columns = window.locator(".ge-settings__column")
    expect(columns.first).to_have_attribute("data-section", "behaviour")
    # the second http node of the same kind: its window has the same order
    page.keyboard.press("Escape")
    page.click("[data-add-menu]")
    pick_node(page, "http")
    page.locator(".ge-node--http").last.dblclick(position={"x": 30, "y": 5})
    second = page.locator("#node-modal")
    expect(second.locator(".ge-settings__column").first).to_have_attribute(
        "data-section", "behaviour"
    )
    _reset(api, "/api/ui-layouts/nodes/http")


def test_reset_brings_the_shipped_layout_back(page: Page, base_url: str, api: httpx.Client) -> None:
    saved: dict[str, Any] = api.get(GUARD).json()["shipped"]
    saved["sections"].reverse()
    assert api.put(GUARD, json=saved).status_code == 200
    window = _guard_window(page, base_url, api)
    menu = _menu(page, window)
    expect(_item(menu, "Reset to default")).not_to_have_attribute("aria-disabled", "true")
    _item(menu, "Reset to default").click()
    page.locator("#confirm-modal [data-confirm]").click()
    expect(page.locator("#confirm-modal")).to_be_hidden()
    assert api.get(GUARD).json()["customised"] is False


def test_export_downloads_the_layout_as_yaml(page: Page, base_url: str, api: httpx.Client) -> None:
    saved: dict[str, Any] = api.get(GUARD).json()["shipped"]
    saved["sections"].reverse()
    api.put(GUARD, json=saved)
    window = _guard_window(page, base_url, api)
    menu = _menu(page, window)
    with page.expect_download() as download:
        _item(menu, "Export as YAML").click()
    assert download.value.suggested_filename == "guard.layout.yaml"
    with open(download.value.path(), encoding="utf-8") as file:
        exported = yaml.safe_load(file.read())
    assert exported["window"] == "forms/guard"
    assert [s["key"] for s in exported["layout"]["sections"]] == [
        s["key"] for s in saved["sections"]
    ]
    _reset(api)


def test_closing_with_an_arrangement_not_saved_asks_first(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    window = _node_window(page, base_url, api, "http")
    _item(_menu(page, window), "Edit layout").click()
    window.locator(".lw-arrange [data-section='behaviour'] .lw-section__head .lw-grip").focus()
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("Escape")
    confirm = page.locator("#confirm-modal")
    expect(confirm).to_be_visible()
    expect(confirm).to_contain_text("Discard the arrangement you have not saved?")
    confirm.locator("[data-confirm]").click()
    expect(window).to_be_hidden()
    assert api.get("/api/ui-layouts/nodes/http").json()["customised"] is False


def test_the_handle_and_its_menu_speak_german(page: Page, base_url: str, api: httpx.Client) -> None:
    page.context.add_cookies([{"name": "oa_lang", "value": "de", "url": base_url}])
    window = _guard_window(page, base_url, api)
    expect(window.locator("[data-layout-handle]")).to_have_accessible_name("Fensterlayout")
    menu = _menu(page, window)
    expect(_item(menu, "Layout bearbeiten")).to_be_visible()
    expect(_item(menu, "Als YAML exportieren")).to_be_visible()
    _item(menu, "Layout bearbeiten").click()
    expect(window.locator(".lw-banner")).to_contain_text("Layout wird angeordnet")


def test_the_arrange_view_is_readable_in_both_themes(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    from tests.e2e.test_ui_catalog import BORDER_MIN, TEXT_MIN, _measure, _theme

    window = _guard_window(page, base_url, api)
    _item(_menu(page, window), "Edit layout").click()
    arrange = window.locator(".lw-arrange")
    expect(arrange).to_be_visible()
    for theme in ("light", "dark"):
        _theme(page, theme)
        page.wait_for_timeout(300)
        for selector in (
            ".lw-banner",
            ".lw-section__title",
            ".lw-field__label",
            ".lw-field__tag",
            ".lw-folded",
        ):
            target = window.locator(selector).first
            assert _measure(page, target)["text"] >= TEXT_MIN, f"{selector} / {theme}"
        section = arrange.locator(".lw-section").first
        assert _measure(page, section)["border"] >= BORDER_MIN, f"section outline / {theme}"
        assert _measure(page, window.locator(".lw-grip").first)["text"] >= BORDER_MIN, (
            f"grip / {theme}"
        )
