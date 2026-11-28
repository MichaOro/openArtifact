"""Archived children in the Grouped board view (ADR-095 add.1): the last row of an accordion says "+N archived" and opens a list of those cards; a
row of the list shows the archive with that card open and "Back to board" beside its close button; archiving or restoring a card changes the
row at once; the setting *Accordions* decides what an accordion without a choice does, and a change of it forgets the choices made by hand."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import Board, eventually

URL = "/api/settings/personal"


@pytest.fixture
def epic(board: Board) -> Iterator[Board]:
    """An epic with one live child and two archived ones (the older archived first), in the Grouped view. The settings are the default afterwards."""
    parent = board.create("Epic", "in_progress")
    board.create("Live", "backlog", parent_id=parent["id"])
    for title, lane in (("Old one", "backlog"), ("Old two", "done")):
        child = board.create(title, lane, parent_id=parent["id"])
        board.api.post(f"/api/tasks/{child['id']}/archive").raise_for_status()
    board.api.put(
        URL, json={"board_view": "grouped", "board_groups_open": "closed"}
    ).raise_for_status()
    yield board
    board.api.put(URL, json={"board_view": "classic", "board_groups_open": "closed"})


def _open_epic(board: Board) -> None:
    board.open()
    toggle = board.card("Epic").locator("[data-group-toggle]")
    expect(toggle).to_have_attribute("aria-expanded", "false")  # closed by default
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")


def test_the_last_row_counts_the_archived_children_and_leads_to_the_archived_card_and_back(
    epic: Board,
) -> None:
    _open_epic(epic)
    rows = epic.card("Epic").locator("[data-group-list] li")
    expect(rows).to_have_count(2)  # the live child, then the archive row
    expect(rows.nth(0).locator("[data-group-row]")).to_contain_text("Live")
    archived_row = rows.nth(1).locator("[data-archived-row]")
    expect(archived_row).to_have_text(
        "+2 archived"
    )  # the last row, with the number of archived children
    expect(epic.card("Epic").locator("[data-group-count]")).to_have_text(
        "1"
    )  # the header counts the visible children only

    archived_row.click()
    modal = epic.page.locator("#archived-children-modal")
    expect(modal).to_be_visible()
    listed = modal.locator("[data-archived-id]")
    expect(listed).to_have_count(2)
    expect(listed.nth(0).locator(".group-row__title")).to_contain_text(
        "Old two"
    )  # the newest archived first
    expect(listed.nth(0).locator(".group-row__lane")).to_have_text(
        "Done"
    )  # the lane it was archived from
    expect(listed.nth(1).locator(".group-row__lane")).to_have_text("Backlog")

    listed.nth(0).click()
    expect(modal).to_be_hidden()
    expect(
        epic.page.locator("[data-archive-view]")
    ).to_be_visible()  # the archive replaced the lanes
    expect(epic.page.locator(".board")).to_be_hidden()
    card = epic.page.locator("#create-task-modal")
    expect(card.locator("[data-view-title]")).to_have_text("Old two")  # that card is open at once
    back = card.locator("[data-modal-origin]")
    expect(back).to_have_text("Back to board")

    back.click()
    expect(card).to_be_hidden()
    expect(epic.page.locator(".board")).to_be_visible()
    expect(epic.page.locator("[data-archive-view]")).to_be_hidden()
    expect(modal).to_be_hidden()  # the list stays closed: back leads to the board

    epic.card("Epic").locator("[data-archived-row]").click()
    epic.page.locator("#archived-children-modal [data-archived-id]").nth(1).click()
    expect(card.locator("[data-view-title]")).to_have_text("Old one")
    epic.page.keyboard.press(
        "Escape"
    )  # close: the user stays in the archive and may pick another card
    expect(card).to_be_hidden()
    expect(epic.page.locator("[data-archive-view]")).to_be_visible()

    epic.page.locator(
        "[data-board-menu]"
    ).click()  # back on the board by the menu; a card opened the normal way has no way back to offer
    epic.page.get_by_role("menuitem", name=re.compile("Hide archive")).click()
    expect(epic.page.locator(".board")).to_be_visible()
    epic.card("Epic").locator(".task-card__title").click()
    expect(card.locator("[data-view-title]")).to_have_text("Epic")
    expect(card.locator("[data-modal-origin]")).to_be_hidden()


def test_archiving_and_restoring_a_child_change_the_row_at_once(epic: Board) -> None:
    _open_epic(epic)
    row = epic.card("Epic").locator("[data-archived-row]")
    expect(row).to_have_text("+2 archived")
    live = epic.stored()["Live"]
    epic.api.post(f"/api/tasks/{live['id']}/archive").raise_for_status()  # live, from another place
    expect(row).to_have_text("+3 archived")
    expect(epic.card("Epic").locator("[data-group-count]")).to_have_text(
        "0"
    )  # no visible child left, the accordion stays with its row
    epic.api.post(f"/api/tasks/{live['id']}/unarchive").raise_for_status()
    expect(row).to_have_text("+2 archived")
    expect(epic.card("Epic").locator("[data-group-count]")).to_have_text("1")


def test_a_parent_whose_children_are_all_archived_still_has_an_accordion_with_the_archive_row_only(
    epic: Board,
) -> None:
    solo = epic.create("Solo", "backlog")
    child = epic.create("Gone", "backlog", parent_id=solo["id"])
    epic.api.post(f"/api/tasks/{child['id']}/archive").raise_for_status()
    epic.open()
    toggle = epic.card("Solo").locator("[data-group-toggle]")
    expect(toggle).to_be_visible()
    expect(epic.card("Solo").locator("[data-group-count]")).to_have_text("0")
    toggle.click()
    expect(epic.card("Solo").locator("[data-group-list] li")).to_have_count(1)
    expect(epic.card("Solo").locator("[data-archived-row]")).to_have_text("+1 archived")


def test_the_classic_view_names_the_archived_children_next_to_the_visible_ones_and_opens_the_same_list(
    epic: Board,
) -> None:
    epic.api.put(URL, json={"board_view": "classic"}).raise_for_status()
    epic.open()
    meta = epic.card("Epic").locator(".task-card__meta")
    expect(meta).to_have_text("1 sub-artifact · 2 archived")  # not counted in the 1
    epic.card("Epic").locator("[data-archived-link]").click()
    expect(epic.page.locator("#archived-children-modal [data-archived-id]")).to_have_count(2)


def test_the_accordion_setting_is_greyed_in_the_classic_view_and_decides_the_default_and_a_change_forgets_the_hand_made_choices(
    epic: Board, base_url: str
) -> None:
    epic.api.put(URL, json={"board_view": "classic"}).raise_for_status()
    page = epic.page
    page.goto(f"{base_url}/settings/personal")
    accordions = page.get_by_label("Accordions")
    expect(accordions).to_be_disabled()
    expect(
        page.get_by_text("Only the Grouped board view has accordions.")
    ).to_be_visible()  # the reason stands under it
    page.get_by_label("Board view").select_option(label="Grouped")
    expect(accordions).to_be_enabled()
    expect(page.get_by_text("Only the Grouped board view has accordions.")).to_have_count(0)
    accordions.select_option(label="Open")
    eventually(lambda: epic.api.get(URL).json()["board_groups_open"], "open")

    epic.open()
    toggle = epic.card("Epic").locator("[data-group-toggle]")
    expect(toggle).to_have_attribute("aria-expanded", "true")  # open without a choice of the user
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "false")  # a choice by hand
    epic.page.reload()
    expect(epic.card("Epic").locator("[data-group-toggle]")).to_have_attribute(
        "aria-expanded", "false"
    )  # kept, though the default is open

    epic.api.put(URL, json={"board_groups_open": "closed"}).raise_for_status()
    expect(epic.card("Epic").locator("[data-group-toggle]")).to_have_attribute(
        "aria-expanded", "false"
    )
    epic.api.put(URL, json={"board_groups_open": "open"}).raise_for_status()
    # without the change having forgotten the choice, the card would stay closed under "open"
    expect(epic.card("Epic").locator("[data-group-toggle]")).to_have_attribute(
        "aria-expanded", "true"
    )
