"""Reorganize the lanes of the board (ADR-092): a mode in the board's menu, a handle above every lane, cards stay put, the order is saved."""

from __future__ import annotations

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import Board

pytestmark = pytest.mark.e2e

GRIP = "[data-lane-grip]"
LANES = ".board > .lane"


def _board(board: Board, api: httpx.Client) -> Page:
    """Backlog (3 cards), In Progress, Done, and three more lanes so the board scrolls sideways."""
    for title in ("Next", "Platform", "Review"):
        api.post("/api/lanes", json={"title": title}).raise_for_status()
    for n in range(3):
        board.create(f"Card {n}", status="backlog")
    page = board.page
    page.goto(board.base_url)
    expect(page.locator(".lane")).to_have_count(6)
    page.set_viewport_size({"width": 1400, "height": 800})
    expect(page.locator(".board .task-card")).to_have_count(3)
    page.wait_for_timeout(300)
    return page


def _titles(api: httpx.Client) -> list[str]:
    return [lane["title"] for lane in api.get("/api/lanes").json()]


def _names(page: Page) -> list[str]:
    return [t.strip() for t in page.locator(f"{LANES} [data-lane-name]").all_inner_texts()]


def _enter(page: Page) -> None:
    page.locator("[data-board-menu]").click()
    page.get_by_role("menuitem", name="Reorganize lanes").click()
    expect(page.locator(".board--reorder")).to_have_count(1)
    page.wait_for_timeout(350)  # the lanes slide down


def _top(page: Page) -> float:
    box = page.locator(LANES).first.bounding_box()
    assert box
    return box["y"]


def test_the_menu_item_switches_the_mode_and_its_text(board: Board, api: httpx.Client) -> None:
    page = _board(board, api)
    page.locator("[data-board-menu]").click()
    expect(page.get_by_role("menuitem", name="Reorganize lanes")).to_be_visible()
    page.get_by_role("menuitem", name="Reorganize lanes").click()
    page.locator("[data-board-menu]").click()
    expect(page.get_by_role("menuitem", name="Stop reorganizing lanes")).to_be_visible()
    expect(page.get_by_role("menuitem", name="Reorganize lanes", exact=True)).to_have_count(0)
    page.get_by_role("menuitem", name="Stop reorganizing lanes").click()
    expect(page.locator(".board--reorder")).to_have_count(0)


def test_the_lanes_slide_down_for_the_handles_and_come_back_without_a_gap(
    board: Board, api: httpx.Client
) -> None:
    page = _board(board, api)
    before = _top(page)
    expect(page.locator(GRIP).first).to_be_hidden()
    _enter(page)
    shown = _top(page)
    assert shown > before + 20, (before, shown)  # room for a handle row
    grips = page.locator(GRIP)
    expect(grips).to_have_count(6)
    for index in range(4):  # the lanes that are in view: a handle above each, centred
        grip = grips.nth(index).bounding_box()
        lane = page.locator(LANES).nth(index).bounding_box()
        assert grip and lane
        assert grip["y"] + grip["height"] <= lane["y"] + 1, "the handle is above its lane"
        assert abs((grip["x"] + grip["width"] / 2) - (lane["x"] + lane["width"] / 2)) <= 2
    page.keyboard.press("Escape")
    expect(page.locator(".board--reorder")).to_have_count(0)
    page.wait_for_timeout(350)
    assert abs(_top(page) - before) <= 1, "no strip is left when the mode ends"
    expect(grips.first).to_be_hidden()


def test_cards_cannot_be_moved_in_the_mode_and_can_again_after_it(
    board: Board, api: httpx.Client
) -> None:
    page = _board(board, api)
    _enter(page)
    card = page.locator(".task-card", has_text="Card 0")
    box = card.bounding_box()
    target = page.locator(LANES).nth(1).bounding_box()
    assert box and target
    page.mouse.move(box["x"] + 40, box["y"] + 20)
    page.mouse.down()
    page.mouse.move(target["x"] + target["width"] / 2, target["y"] + 200, steps=10)
    page.mouse.up()
    page.wait_for_timeout(300)
    statuses = {t["title"]: t["status"] for t in api.get("/api/tasks").json()}
    assert statuses["Card 0"] == "backlog", "a card stays in its lane while lanes are reorganized"
    page.keyboard.press("Escape")
    box = card.bounding_box()
    assert box
    page.mouse.move(box["x"] + 40, box["y"] + 20)
    page.mouse.down()
    page.mouse.move(target["x"] + target["width"] / 2, target["y"] + 200, steps=10)
    page.mouse.up()
    page.wait_for_timeout(500)
    statuses = {t["title"]: t["status"] for t in api.get("/api/tasks").json()}
    assert statuses["Card 0"] == "in_progress", "and moves again after the mode ended"


def test_a_lane_dragged_by_its_handle_moves_and_the_order_is_saved(
    board: Board, api: httpx.Client
) -> None:
    page = _board(board, api)
    first = _titles(api)
    _enter(page)
    grips = page.locator(GRIP)
    a = grips.nth(0).bounding_box()
    c = grips.nth(2).bounding_box()
    assert a and c
    page.mouse.move(a["x"] + a["width"] / 2, a["y"] + a["height"] / 2)
    page.mouse.down()
    page.mouse.move(c["x"] + c["width"] / 2 + 60, c["y"] + 10, steps=14)
    page.mouse.up()
    page.wait_for_timeout(600)
    expected = [first[1], first[2], first[0], *first[3:]]
    assert _titles(api) == expected
    assert [n.casefold() for n in _names(page)] == [n.casefold() for n in expected]
    page.reload()
    assert [n.casefold() for n in _names(page)] == [n.casefold() for n in expected], (
        "it survives a reload"
    )
    expect(page.locator(".board--reorder")).to_have_count(0)  # the mode is not stored


def test_the_arrow_keys_on_a_handle_move_the_lane_and_announce_it(
    board: Board, api: httpx.Client
) -> None:
    page = _board(board, api)
    before = _titles(api)
    _enter(page)
    page.locator(GRIP).nth(1).focus()
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(500)
    assert _titles(api) == [before[0], before[2], before[1], *before[3:]]
    live = page.locator("[data-live-region]")
    expect(live).to_contain_text("moved to position 3 of 6")
    focused = page.evaluate("document.activeElement?.hasAttribute('data-lane-grip')")
    assert focused, "the handle keeps the focus"
    page.keyboard.press("ArrowLeft")
    page.wait_for_timeout(500)
    assert _titles(api) == before


def test_another_page_follows_a_reorder_without_a_reload(
    board: Board, api: httpx.Client, base_url: str
) -> None:
    page = _board(board, api)
    other = page.context.new_page()
    other.goto(base_url)
    other.locator(LANES).first.wait_for()
    names = _titles(api)
    api.post("/api/lanes/order", json={"lanes": [*reversed(names)]}).raise_for_status()
    expect(other.locator(f"{LANES} [data-lane-name]").first).to_have_text(
        names[-1], ignore_case=True
    )
    assert [n.casefold() for n in _names(other)] == [n.casefold() for n in reversed(names)]
    other.close()


def test_a_failed_save_puts_the_old_order_back_and_says_so(board: Board, api: httpx.Client) -> None:
    page = _board(board, api)
    before = _names(page)
    _enter(page)
    page.route("**/api/lanes/order", lambda route: route.fulfill(status=500, body="{}"))
    grips = page.locator(GRIP)
    a = grips.nth(0).bounding_box()
    c = grips.nth(2).bounding_box()
    assert a and c
    page.mouse.move(a["x"] + a["width"] / 2, a["y"] + a["height"] / 2)
    page.mouse.down()
    page.mouse.move(c["x"] + c["width"] / 2 + 60, c["y"] + 10, steps=14)
    page.mouse.up()
    page.wait_for_timeout(700)
    assert _names(page) == before, "the lanes are where they were"
    expect(page.locator("[data-alert-text]").first).to_contain_text("went wrong")


def test_the_search_keeps_working_in_the_mode(board: Board, api: httpx.Client) -> None:
    page = _board(board, api)
    _enter(page)
    page.locator("[data-board-search]").fill("Card 1")
    expect(page.locator(".task-card:visible")).to_have_count(1)
    expect(page.locator(GRIP).first).to_be_visible()
