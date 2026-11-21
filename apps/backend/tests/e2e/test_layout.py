"""Themes, sidebar and the narrow layouts."""

from __future__ import annotations

from playwright.sync_api import expect

from tests.e2e.helpers import Board


def test_theme_toggle_switches_and_persists(board: Board) -> None:
    board.open()
    html = board.page.locator("html")
    before = html.get_attribute("data-theme")
    board.page.locator("[data-theme-toggle]").click()
    after = html.get_attribute("data-theme")
    assert after != before
    board.page.reload()
    expect(html).to_have_attribute("data-theme", after or "")


def test_lanes_have_their_own_colours(board: Board) -> None:
    board.open()
    colours = board.page.locator(".lane__count").evaluate_all(
        "els => els.map((e) => getComputedStyle(e).backgroundColor)"
    )
    assert len(set(colours)) == 3


def test_sidebar_collapses_and_expands(board: Board) -> None:
    board.open()
    root = board.page.locator("html")
    toggle = board.page.locator("[data-sidebar-toggle]")
    start = root.get_attribute("data-sidebar")
    toggle.click()
    assert root.get_attribute("data-sidebar") != start


def test_narrow_screen_starts_with_a_collapsed_overlay_sidebar(board: Board) -> None:
    board.page.set_viewport_size({"width": 390, "height": 800})
    board.open()
    expect(board.page.locator("html")).to_have_attribute("data-sidebar", "collapsed")
    assert board.page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_dialog_fits_a_phone_in_landscape(board: Board) -> None:
    board.create("Plan", body="text")
    board.page.set_viewport_size({"width": 740, "height": 360})
    dialog = board.open().open_card("Plan").edit()
    box = dialog.root.locator(".modal__panel").bounding_box()
    assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= 740
    expect(dialog.rail_toggle).to_be_hidden()
