"""The page size of a management page follows the room (ADR-069 addendum 12): the cards of the first page are whole columns times whole rows of what
fits the area (never fewer than 12), the "Per page" choices are the base and twice and four times the base, the browser remembers the step, and
a phone loads 12 and scrolls."""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import Board, eventually
from tests.helpers import post

MEASURE = """() => {
  const cards = [...document.querySelectorAll('.mg-card')];
  const box = (el) => el.getBoundingClientRect();
  const first = box(cards[0]);
  const columns = cards.filter((c) => Math.abs(box(c).top - first.top) < 2).length;
  const last = box(cards[cards.length - 1]);
  const pager = box(document.querySelector('.mg__pager'));
  const list = document.querySelector('.mg__list');
  return {
    count: cards.length, columns, cardHeight: first.height, gap: parseFloat(getComputedStyle(list).rowGap),
    lastBottom: last.bottom, pagerBottom: pager.bottom, viewport: window.innerHeight,
    base: Number(document.querySelector('.mg').dataset.base), size: Number(document.querySelector('.mg').dataset.size),
  };
}"""


def _actions(api: httpx.Client, count: int) -> None:
    for i in range(count):
        post(api, "/api/actions", name=f"Action {i:03d}")


def _measure(page: Page) -> dict[str, Any]:
    return page.evaluate(MEASURE)  # type: ignore[no-any-return]


def _options(page: Page) -> list[str]:
    return page.locator(".mg__size select option").all_inner_texts()


def test_the_first_page_holds_whole_columns_times_whole_rows_that_fill_the_area(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _actions(api, 80)
    page.set_viewport_size(
        {"width": 2300, "height": 1500}
    )  # large enough for more than the minimum of 12
    page.goto(f"{base_url}/actions")
    expect(page.locator(".mg-card").first).to_be_visible()
    m = _measure(page)
    assert m["count"] == m["base"] == m["size"] > 12, m
    assert m["count"] % m["columns"] == 0, "whole rows only: no half-filled last row"
    assert m["columns"] > 1 and m["count"] // m["columns"] > 1, m
    assert m["pagerBottom"] <= m["viewport"] + 1, (
        "the pager is inside the window: nothing is cut off below"
    )
    free = m["viewport"] - m["pagerBottom"]
    assert free < m["cardHeight"] + m["gap"], (
        f"another row would still fit ({free:.0f}px free): the area is not used"
    )
    expect(page.locator(".mg__pager .mg__count")).to_have_text(
        re.compile(rf"^1.{m['count']} of 80$")
    )


def test_the_choices_are_the_base_and_twice_and_four_times_the_base_and_the_pager_pages_by_the_chosen_size(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _actions(api, 120)
    page.goto(f"{base_url}/actions")
    expect(page.locator(".mg-card").first).to_be_visible()
    base = _measure(page)["base"]
    assert _options(page) == [str(base), str(base * 2), str(base * 4)]
    expect(page.locator(".mg__size select")).to_have_value("1")
    page.locator(".mg__pager").get_by_role("button", name="Next").click()
    expect(page.locator(".mg__pager .mg__count")).to_have_text(
        re.compile(rf"^{base + 1}.{base * 2} of 120$")
    )
    # the first entry on the screen (number base + 1) is within the first 2 x base entries, so it stays on the first page
    page.locator(".mg__size select").select_option(label=str(base * 2))
    expect(page.locator(".mg-card")).to_have_count(base * 2)
    expect(page.locator(".mg__pager .mg__count")).to_have_text(
        re.compile(rf"^1.{base * 2} of 120$")
    )


def test_the_step_is_remembered_not_the_number_and_an_old_stored_size_is_ignored(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _actions(api, 120)
    page.goto(f"{base_url}/actions")
    expect(page.locator(".mg-card").first).to_be_visible()
    base = _measure(page)["base"]
    page.locator(".mg__size select").select_option(label=str(base * 4))
    expect(page.locator(".mg-card")).to_have_count(base * 4)
    stored = page.evaluate("JSON.parse(localStorage.getItem('oa-management-actions'))")
    assert stored["step"] == 4 and "size" not in stored, stored
    page.reload()
    expect(page.locator(".mg-card").first).to_be_visible()
    expect(page.locator(".mg__size select")).to_have_value("4")
    expect(page.locator(".mg-card")).to_have_count(base * 4)
    # a value written by the version before (a number of entries) is not a step: the first step is used
    page.evaluate(
        "localStorage.setItem('oa-management-actions', JSON.stringify({view: 'cards', sort: 'name', size: 24}))"
    )
    page.reload()
    expect(page.locator(".mg-card").first).to_be_visible()
    expect(page.locator(".mg__size select")).to_have_value("1")
    expect(page.locator(".mg-card")).to_have_count(base)


def test_a_phone_loads_twelve_and_the_page_scrolls(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _actions(api, 30)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{base_url}/actions")
    expect(page.locator(".mg-card").first).to_be_visible()
    m = _measure(page)
    assert m["base"] == 12 and m["count"] == 12 and m["columns"] == 1, m
    assert m["lastBottom"] > m["viewport"], (
        "twelve single cards are taller than the screen: the page scrolls"
    )
    expect(page.locator(".mg__pager .mg__count")).to_have_text(re.compile(r"^1.12 of 30$"))
    page.locator(".mg-card").last.scroll_into_view_if_needed()
    expect(page.locator(".mg-card").last).to_be_in_viewport()
    assert _options(page) == ["12", "24", "48"]


def test_the_room_changes_with_the_window_and_the_first_card_stays(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _actions(api, 120)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{base_url}/actions")
    expect(page.locator(".mg-card").first).to_be_visible()
    small = _measure(page)["base"]
    first_title = page.locator(".mg-card").first.locator(".mg-card__name").inner_text()
    page.set_viewport_size({"width": 2300, "height": 1500})
    eventually(lambda: _measure(page)["base"] > small, True, page=page)  # debounced, a moment later
    big = _measure(page)
    assert big["count"] == big["base"] and big["base"] % big["columns"] == 0, big
    assert page.locator(".mg-card").first.locator(".mg-card__name").inner_text() == first_title
    page.set_viewport_size({"width": 1280, "height": 800})
    eventually(lambda: _measure(page)["base"], small, page=page)
    assert _options(page) == [str(small), str(small * 2), str(small * 4)]


def test_the_list_view_uses_the_room_with_the_height_of_its_rows(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _actions(api, 150)
    page.set_viewport_size({"width": 1700, "height": 1300})
    page.goto(f"{base_url}/actions")
    expect(page.locator(".mg-card").first).to_be_visible()
    page.get_by_role("button", name="List").click()
    eventually(lambda: page.locator(".mg-card").count() == _measure(page)["base"], True, page=page)
    m = _measure(page)
    assert m["columns"] == 1 and m["base"] >= 12, m
    assert m["pagerBottom"] <= m["viewport"] + 1, m
    free = m["viewport"] - m["pagerBottom"]
    assert free < m["cardHeight"] + m["gap"] + 6, (
        f"another row would still fit ({free:.0f}px free): {m}"
    )


def test_the_archive_uses_the_same_rule(board: Board) -> None:
    for i in range(40):
        card = board.create(f"Old card {i:02d}")
        board.api.post(f"/api/tasks/{card['id']}/archive").raise_for_status()
    try:
        board.page.set_viewport_size({"width": 2300, "height": 1500})
        board.open()
        board.page.locator("[data-board-menu]").click()
        board.page.get_by_role("menuitem", name="Show archive").click()
        archive = board.page.locator("[data-archive-view]")
        expect(archive.locator(".mg-card").first).to_be_visible()
        m = board.page.evaluate(MEASURE)
        assert m["base"] > 12 and m["count"] == min(m["base"], 40), m
        assert m["count"] % m["columns"] == 0 or m["count"] == 40, m
        assert m["pagerBottom"] <= m["viewport"] + 1, "the pager is inside the window"
        sizes = [int(n) for n in board.page.locator(".mg__size select option").all_inner_texts()]
        assert sizes == [m["base"], m["base"] * 2, m["base"] * 4], sizes
    finally:
        for task in board.api.get("/api/tasks?archived=only").json():
            board.api.post(f"/api/tasks/{task['id']}/unarchive").raise_for_status()
