"""The Grouped board view in the browser (ADR-095): the personal setting *Board view* switches it live; a card with a parent leaves its lane and
is a row in the accordion of its parent, with its own lane named on the row; a click on a row opens that card; a search finds a card that is a
row; a child of an archived parent is a card of its lane again; the classic view puts every card back. Nothing about a card changes."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import Board, eventually

URL = "/api/settings/personal"


@pytest.fixture
def tree(board: Board) -> Iterator[Board]:
    """An epic with a work package that has a task: three levels, each in a lane of its own. The view is classic again afterwards."""
    epic = board.create("Epic", "in_progress")
    package = board.create("Package", "backlog", parent_id=epic["id"])
    board.create("Task", "done", parent_id=package["id"])
    board.api.put(URL, json={"board_view": "classic"}).raise_for_status()
    yield board
    board.api.put(URL, json={"board_view": "classic"})


def _numbers(board: Board) -> dict[str, int]:
    return {title: task["number"] for title, task in board.stored().items()}


def test_the_personal_page_offers_the_two_views_and_saves_the_choice(
    tree: Board, base_url: str
) -> None:
    page = tree.page
    page.goto(f"{base_url}/settings/personal")
    select = page.get_by_label("Board view")
    expect(select).to_have_value("classic")  # the default
    select.select_option(label="Grouped")
    eventually(lambda: tree.api.get(URL).json()["board_view"], "grouped")
    page.reload()
    expect(page.get_by_label("Board view")).to_have_value("grouped")  # kept
    expect(page.get_by_label("Board view").locator("option")).to_have_text(["Classic", "Grouped"])


def test_a_child_is_a_row_under_its_parent_while_the_view_is_grouped_and_a_card_of_its_lane_in_the_classic_view(
    tree: Board,
) -> None:
    numbers = _numbers(tree)
    tree.open()
    for title in ("Epic", "Package", "Task"):
        expect(tree.card(title)).to_be_visible()  # classic: every card in its lane
    expect(tree.page.locator("[data-group-toggle]:visible")).to_have_count(0)

    tree.api.put(
        URL, json={"board_view": "grouped"}
    ).raise_for_status()  # live: the page is not reloaded
    expect(
        tree.card("Task")
    ).to_be_hidden()  # a task with a parent on the board is not drawn in its lane ...
    expect(
        tree.card("Package")
    ).to_be_visible()  # ... a package that has a task of its own stays: it is a parent
    expect(tree.card("Epic")).to_be_visible()
    expect(tree.lane("done").locator(".lane__count")).to_have_text(
        "0"
    )  # the badge counts what the lane draws
    expect(tree.lane("done").locator(".lane__count")).to_have_attribute(
        "title", re.compile(r"1 more in the accordions")
    )

    epic_toggle = tree.card("Epic").locator("[data-group-toggle]")
    expect(epic_toggle).to_have_attribute("aria-expanded", "false")  # closed by default
    expect(tree.card("Epic").locator("[data-group-row]")).to_have_count(0)
    epic_toggle.click()
    expect(epic_toggle).to_have_attribute("aria-expanded", "true")
    row = tree.card("Epic").locator("[data-group-row]")
    expect(row).to_have_count(1)  # the direct child only, not the task below it
    expect(row.locator(".group-row__title")).to_have_text(f"#{numbers['Package']} Package")
    expect(row.locator(".group-row__lane")).to_have_text(
        "Backlog"
    )  # the lane of the child itself, though it is drawn under its parent

    tree.card("Package").locator("[data-group-toggle]").click()
    task_row = tree.card("Package").locator("[data-group-row]")
    expect(task_row.locator(".group-row__lane")).to_have_text("Done")
    task_row.click()  # a row opens its card, not the card around it
    dialog_title = tree.page.locator("#create-task-modal [data-view-title]")
    expect(dialog_title).to_have_text("Task")
    expect(tree.page.locator('#create-task-modal [data-card-field="parent"]')).to_contain_text(
        f"#{numbers['Package']} Package"
    )  # the number stands before the title
    tree.page.keyboard.press("Escape")

    stored = tree.stored()["Task"]  # presentation only: the card is as it was
    assert (stored["status"], stored["parent_id"]) == ("done", tree.stored()["Package"]["id"])

    tree.api.put(URL, json={"board_view": "classic"}).raise_for_status()
    expect(tree.card("Task")).to_be_visible()  # back in its lane, at once
    expect(tree.lane("done").locator(".lane__count")).to_have_text("1")
    expect(tree.page.locator("[data-group-toggle]:visible")).to_have_count(0)


def test_a_search_finds_a_card_that_is_a_row_and_the_child_of_an_archived_parent_is_drawn_in_its_lane(
    tree: Board,
) -> None:
    tree.api.put(URL, json={"board_view": "grouped"}).raise_for_status()
    tree.open()
    expect(tree.card("Task")).to_be_hidden()
    tree.page.locator("[data-board-search]").fill("Task")
    expect(tree.card("Package")).to_be_visible()  # the parent of the card that matches is shown ...
    expect(tree.card("Epic")).to_be_hidden()  # ... and what has no match and no row with one is not
    row = tree.card("Package").locator("[data-group-row]")
    expect(row).to_have_count(1)  # the accordion opens by itself and holds the matching row only
    expect(row.locator(".group-row__title")).to_contain_text("Task")
    tree.page.locator("[data-board-search]").fill("")

    package = tree.stored()["Package"]
    tree.api.post(f"/api/tasks/{package['id']}/archive").raise_for_status()
    expect(tree.card("Package")).to_have_count(0)  # archived: not on the board
    expect(
        tree.card("Task")
    ).to_be_visible()  # its child has no parent on the board now: a card of its lane again
    tree.api.post(f"/api/tasks/{package['id']}/unarchive").raise_for_status()
    expect(tree.card("Task")).to_be_hidden()  # the parent is back: the child is a row again
