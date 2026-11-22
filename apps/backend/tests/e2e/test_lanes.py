"""Lanes in the browser: adding, renaming (click the name or the menu), deleting, the menu, live updates."""

from __future__ import annotations

import itertools

from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import Board

HINT = "A lane can only be deleted when it contains no artifacts."


def _name(board: Board, status: str) -> Locator:
    return board.lane(status).locator("[data-lane-name]")


def _title(board: Board, status: str) -> Locator:
    return board.lane(status).locator(".lane__title")


def _kebab(board: Board, status: str) -> Locator:
    return board.lane(status).locator("[data-lane-menu]")


def _menu(page: Page) -> Locator:
    return page.locator(".menu:not([hidden])")


def _item(page: Page, name: str) -> Locator:
    return _menu(page).get_by_role("menuitem", name=name)


def _editor(board: Board, status: str) -> Locator:
    return board.lane(status).locator(".inline-name__input")


def _rename(board: Board, status: str, title: str) -> None:
    _name(board, status).click()
    field = _editor(board, status)
    field.fill(title)
    field.press("Enter")


def _add_lane(board: Board, title: str) -> None:
    board.page.locator("[data-add-lane]").click()
    field = board.page.locator("#add-lane-modal-field-title")
    field.fill(title)
    field.press("Enter")


def _live(board: Board) -> Locator:
    return board.page.locator("[data-live-region]")


def test_the_sidebar_entry_is_called_board(board: Board) -> None:
    board.open()
    link = board.page.locator('.sidebar a[href="/"], nav a[href="/"]').first
    expect(link).to_contain_text("Board")
    expect(link).to_have_attribute("aria-current", "page")
    expect(board.page).to_have_title("Board · OpenArtifact")
    expect(board.page.locator(".app-header__title")).to_have_text("Board")
    expect(board.page.get_by_text("Projects")).to_have_count(0)


# ── adding ───────────────────────────────────────────────────────────


def test_a_lane_is_added_at_the_end_focused_and_stays_after_a_reload(board: Board) -> None:
    board.open()
    _add_lane(board, "Review")
    expect(board.page.locator("#add-lane-modal")).not_to_be_visible()
    lanes = board.page.locator(".lane")
    expect(lanes).to_have_count(4)
    review = board.lane("review")
    expect(review).to_have_attribute("data-lane-hue", "4")
    expect(_title(board, "review")).to_have_text("Review", use_inner_text=False)
    expect(review.locator(".lane__count")).to_have_text("0")
    expect(_name(board, "review")).to_be_focused()
    expect(_live(board)).to_have_text("Lane Review added")
    assert lanes.nth(3).get_attribute("data-status") == "review"
    board.page.reload()
    expect(board.page.locator(".lane")).to_have_count(4)
    expect(_title(board, "review")).to_have_text("Review", use_inner_text=False)
    # artifacts can be created in the new lane
    review.locator("[data-create-task]").click()
    board.page.fill("#create-task-modal-field-title", "In the new lane")
    board.page.keyboard.press("Enter")
    expect(review.locator(".task-card")).to_have_count(1)
    assert board.stored()["In the new lane"]["status"] == "review"


def test_the_add_dialog_refuses_a_bad_title_inline_and_keeps_the_text(board: Board) -> None:
    board.open()
    _add_lane(board, "done")
    dialog = board.page.locator("#add-lane-modal")
    expect(dialog).to_be_visible()
    expect(dialog.locator("[data-form-error]")).to_contain_text("already called")
    expect(dialog.locator("#add-lane-modal-field-title")).to_have_value("done")
    expect(board.page.locator(".lane")).to_have_count(3)
    board.page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()


def test_the_twelve_lane_limit_is_explained(board: Board) -> None:
    for n in range(9):
        board.api.post("/api/lanes", json={"title": f"Extra {n}"}).raise_for_status()
    board.open_with_lanes(12)
    _add_lane(board, "One too many")
    dialog = board.page.locator("#add-lane-modal")
    expect(dialog.locator("[data-form-error]")).to_contain_text("at most 12 lanes")
    expect(board.page.locator(".lane")).to_have_count(12)


# ── renaming ─────────────────────────────────────────────────────────


def test_a_lane_is_renamed_by_clicking_its_name_and_stays_after_a_reload(board: Board) -> None:
    board.create("Card", status="in_progress")
    board.open()
    _rename(board, "in_progress", "Review")
    expect(_editor(board, "in_progress")).to_have_count(0)
    expect(_title(board, "in_progress")).to_have_text("Review", use_inner_text=False)
    expect(_name(board, "in_progress")).to_have_attribute("title", "Review")
    expect(_name(board, "in_progress")).to_be_focused()
    expect(board.lane("in_progress").locator("[data-create-task]")).to_have_attribute(
        "aria-label", "Add artifact to Review"
    )
    expect(_kebab(board, "in_progress")).to_have_attribute("aria-label", "Options for lane Review")
    expect(_live(board)).to_have_text("Lane renamed to Review")
    assert board.stored()["Card"]["status"] == "in_progress"  # the key did not change
    board.page.reload()
    expect(_title(board, "in_progress")).to_have_text("Review", use_inner_text=False)


def test_a_lane_is_renamed_through_the_menu_pencil(board: Board) -> None:
    board.open()
    _kebab(board, "backlog").click()
    _item(board.page, "Rename").click()
    expect(_menu(board.page)).to_have_count(0)
    field = _editor(board, "backlog")
    expect(field).to_be_focused()
    expect(field).to_have_value("Backlog")
    field.fill("Ideas")
    field.press("Enter")
    expect(_title(board, "backlog")).to_have_text("Ideas", use_inner_text=False)
    assert board.api.get("/api/lanes").json()[0]["title"] == "Ideas"


def test_escape_cancels_the_rename_and_the_name_gets_focus_back(board: Board) -> None:
    board.open()
    _name(board, "backlog").focus()
    board.page.keyboard.press("Enter")
    field = _editor(board, "backlog")
    expect(field).to_be_focused()
    field.fill("Ideas")
    board.page.keyboard.press("Escape")
    expect(field).to_have_count(0)
    expect(_name(board, "backlog")).to_be_focused()
    expect(_title(board, "backlog")).to_have_text("Backlog", use_inner_text=False)


def test_a_refused_name_is_shown_inline_and_the_typed_text_stays(board: Board) -> None:
    board.open()
    _rename(board, "in_progress", "done")
    field = _editor(board, "in_progress")
    expect(field).to_have_value("done")
    expect(board.lane("in_progress").locator(".inline-name__error")).to_contain_text(
        "already called"
    )
    expect(field).to_have_attribute("aria-invalid", "true")
    field.fill("Doing")
    field.press("Enter")
    expect(_title(board, "in_progress")).to_have_text("Doing", use_inner_text=False)


def test_a_long_title_is_cut_with_an_ellipsis_and_keeps_the_header_in_the_lane(
    board: Board,
) -> None:
    long = "A very long lane title that goes on and on"[:40].strip()
    board.api.put("/api/lanes/backlog", json={"title": long}).raise_for_status()
    board.open()
    lane = board.lane("backlog")
    expect(_name(board, "backlog")).to_have_attribute("title", long)
    box = lane.bounding_box()
    menu_box = _kebab(board, "backlog").bounding_box()
    add_box = lane.locator("[data-create-task]").bounding_box()
    assert box is not None and menu_box is not None and add_box is not None
    assert menu_box["x"] + menu_box["width"] <= box["x"] + box["width"]
    assert add_box["x"] + add_box["width"] <= menu_box["x"]  # the plus sits left of the menu
    clipped = _name(board, "backlog").evaluate("(el) => el.scrollWidth > el.clientWidth")
    assert clipped


# ── the menu ─────────────────────────────────────────────────────────


def test_the_menu_works_with_the_keyboard(board: Board) -> None:
    board.open()
    button = _kebab(board, "done")
    expect(button).to_have_attribute("aria-haspopup", "menu")
    expect(button).to_have_attribute("aria-expanded", "false")
    button.focus()
    board.page.keyboard.press("Enter")
    expect(button).to_have_attribute("aria-expanded", "true")
    menu = _menu(board.page)
    expect(menu).to_have_attribute("role", "menu")
    expect(_item(board.page, "Rename")).to_be_focused()
    board.page.keyboard.press("ArrowDown")
    expect(_item(board.page, "Delete")).to_be_focused()
    board.page.keyboard.press("ArrowDown")
    expect(_item(board.page, "Rename")).to_be_focused()  # wraps
    board.page.keyboard.press("End")
    expect(_item(board.page, "Delete")).to_be_focused()
    board.page.keyboard.press("Home")
    expect(_item(board.page, "Rename")).to_be_focused()
    board.page.keyboard.press("Escape")
    expect(menu).to_have_count(0)
    expect(button).to_be_focused()
    expect(button).to_have_attribute("aria-expanded", "false")
    board.page.keyboard.press("ArrowDown")  # the arrow key opens it too
    expect(_item(board.page, "Rename")).to_be_focused()
    board.page.keyboard.press("Enter")  # Rename starts the inline editor
    expect(_editor(board, "done")).to_be_focused()


def test_a_click_outside_closes_the_menu(board: Board) -> None:
    board.open()
    _kebab(board, "done").click()
    expect(_menu(board.page)).to_be_visible()
    board.page.locator(".app-header__title").click()
    expect(_menu(board.page)).to_have_count(0)
    expect(_kebab(board, "done")).to_have_attribute("aria-expanded", "false")


def test_delete_is_greyed_out_with_a_hint_while_the_lane_has_artifacts(board: Board) -> None:
    board.create("Card", status="done")
    board.open()
    _kebab(board, "done").click()
    delete = _item(board.page, "Delete")
    expect(delete).to_have_attribute("aria-disabled", "true")
    hint = board.page.locator(".menu__hint")
    expect(hint).to_be_hidden()
    delete.hover()  # on hover
    expect(hint).to_be_visible()
    expect(hint).to_have_text(HINT)
    expect(delete).to_have_attribute("aria-describedby", hint.get_attribute("id") or "")
    board.page.locator(".menu__item", has_text="Rename").hover()
    expect(hint).to_be_hidden()
    board.page.keyboard.press("ArrowDown")  # on keyboard focus
    expect(delete).to_be_focused()
    expect(hint).to_be_visible()
    expect(hint).to_have_text(HINT)
    delete.click(force=True)  # does nothing: no dialog, the menu stays
    expect(board.page.locator("#delete-lane-modal")).not_to_be_visible()
    expect(board.page.locator(".lane")).to_have_count(3)


def test_an_empty_lane_is_deleted_after_a_confirmation(board: Board) -> None:
    board.api.post("/api/lanes", json={"title": "Review"}).raise_for_status()
    board.open_with_lanes(4)
    _kebab(board, "review").click()
    _item(board.page, "Delete").click()
    dialog = board.page.locator("#delete-lane-modal")
    expect(dialog).to_be_visible()
    expect(dialog.locator("[data-confirm-message]")).to_have_text("Delete lane Review?")
    dialog.locator("[data-cancel]").click()  # cancel keeps it
    expect(dialog).not_to_be_visible()
    expect(board.page.locator(".lane")).to_have_count(4)
    expect(_kebab(board, "review")).to_be_focused()
    _kebab(board, "review").click()
    _item(board.page, "Delete").click()
    dialog.locator("[data-confirm]").click()
    expect(dialog).not_to_be_visible()
    expect(board.page.locator(".lane")).to_have_count(3)
    expect(board.lane("review")).to_have_count(0)
    expect(_live(board)).to_have_text("Lane Review deleted")
    assert [lane["status"] for lane in board.api.get("/api/lanes").json()] == [
        "backlog",
        "in_progress",
        "done",
    ]


def test_the_last_lane_cannot_be_deleted(board: Board) -> None:
    board.api.delete("/api/lanes/in_progress").raise_for_status()
    board.api.delete("/api/lanes/done").raise_for_status()
    board.open_with_lanes(1)
    _kebab(board, "backlog").click()
    delete = _item(board.page, "Delete")
    expect(delete).to_have_attribute("aria-disabled", "true")
    delete.hover()
    expect(board.page.locator(".menu__hint")).to_have_text("The last lane cannot be deleted.")


def test_a_lane_that_is_gone_elsewhere_disappears_when_deleting_it_here(board: Board) -> None:
    board.api.post("/api/lanes", json={"title": "Review"}).raise_for_status()
    board.open_with_lanes(4)
    _kebab(board, "review").click()
    _item(board.page, "Delete").click()
    board.api.delete("/api/lanes/review").raise_for_status()
    board.page.locator("#delete-lane-modal [data-confirm]").click()
    expect(board.page.locator(".lane")).to_have_count(3)


# ── artifacts and lanes ──────────────────────────────────────────────


def test_a_card_dragged_into_a_new_lane_stays_there_after_a_reload(board: Board) -> None:
    board.api.post("/api/lanes", json={"title": "Review"}).raise_for_status()
    board.create("Card", status="done")
    board.open_with_lanes(4)
    board.lane("review").scroll_into_view_if_needed()  # four lanes scroll sideways at this width
    board.drag(board.card("Card"), board.lane("review").locator(".empty-state"))
    expect(board.lane("review").locator(".task-card")).to_have_count(1)
    board.expect_field("Card", "status", "review")
    board.page.reload()
    expect(board.lane("review").locator(".task-card")).to_have_count(1)
    expect(board.lane("review").locator(".lane__count")).to_have_text("1")


def test_a_card_moves_to_a_lane_added_while_the_page_is_open(board: Board) -> None:
    board.create("Card", status="done")
    board.open()
    _add_lane(board, "Review")
    board.lane("review").scroll_into_view_if_needed()
    board.drag(board.card("Card"), board.lane("review").locator(".empty-state"))
    board.expect_field("Card", "status", "review")
    expect(board.lane("review").locator(".task-card")).to_have_count(1)


def test_the_dialog_chip_and_the_lane_picker_list_the_new_lane(board: Board) -> None:
    board.create("Card")
    board.open()
    _add_lane(board, "Review")
    _rename(board, "done", "Shipped")
    expect(_title(board, "done")).to_have_text("Shipped", use_inner_text=False)
    dialog = board.open_card("Card")
    expect(dialog.lane_chip).to_have_text("In Backlog")
    dialog.lane_chip.click()
    chips = dialog.root.locator("[data-lane-chips] [role=option]")
    expect(chips).to_have_text(["In Progress", "Shipped", "Review"])
    dialog.lane_chip.click()
    dialog.rail("lane").click()
    expect(dialog.option("Review")).to_be_visible()
    dialog.option("Review").click()
    expect(dialog.lane_chip).to_have_text("In Review")
    board.expect_field("Card", "status", "review")
    expect(_live(board)).to_have_text("Card moved to Review")


# ── other tabs ───────────────────────────────────────────────────────


def test_a_second_tab_follows_added_renamed_and_deleted_lanes(board: Board) -> None:
    board.create("Card")
    board.open()
    other = Board(board.page.context.new_page(), board.base_url, board.api)
    other.open()
    dialog = other.open_card("Card")
    expect(dialog.lane_chip).to_have_text("In Backlog")
    board.page.bring_to_front()
    _add_lane(board, "Review")
    expect(other.lane("review")).to_be_visible()
    expect(other.page.locator(".lane")).to_have_count(4)
    _rename(board, "backlog", "Ideas")
    expect(_title(other, "backlog")).to_have_text("Ideas", use_inner_text=False)
    expect(dialog.lane_chip).to_have_text("In Ideas")  # an open dialog follows too
    board.page.bring_to_front()
    _kebab(board, "review").click()
    _item(board.page, "Delete").click()
    board.page.locator("#delete-lane-modal [data-confirm]").click()
    expect(other.page.locator(".lane")).to_have_count(3)
    expect(other.lane("review")).to_have_count(0)
    # a change through the API reaches the open tabs as well
    board.api.put("/api/lanes/backlog", json={"title": "Backlog"}).raise_for_status()
    expect(_title(other, "backlog")).to_have_text("Backlog", use_inner_text=False)


# ── layout ───────────────────────────────────────────────────────────


def test_three_lanes_share_the_width_and_more_lanes_scroll_sideways(board: Board) -> None:
    board.open()
    page = board.page
    widths = [b["width"] for b in (board.lane(s).bounding_box() for s in ("backlog", "done")) if b]
    assert abs(widths[0] - widths[1]) < 1
    scrolls = page.locator(".board").evaluate("(el) => el.scrollWidth > el.clientWidth + 1")
    assert not scrolls
    for n in range(3):
        board.api.post("/api/lanes", json={"title": f"Extra {n}"}).raise_for_status()
    board.open_with_lanes(6)
    assert page.locator(".board").evaluate("(el) => el.scrollWidth > el.clientWidth + 1")
    boxes = [lane.bounding_box() for lane in page.locator(".lane").all()]
    assert all(b is not None and b["width"] >= 270 for b in boxes)
    for left, right in itertools.pairwise(boxes):
        assert left is not None and right is not None
        assert left["x"] + left["width"] <= right["x"] + 1  # no overlap
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_five_lanes_at_phone_width_scroll_without_overflowing_the_page(board: Board) -> None:
    board.page.set_viewport_size({"width": 390, "height": 800})
    for n in range(2):
        board.api.post(
            "/api/lanes", json={"title": f"A rather long lane name {n}"}
        ).raise_for_status()
    board.open_with_lanes(5)
    page = board.page
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for status in ("backlog", "a_rather_long_lane_name_1"):
        lane = board.lane(status)
        lane.scroll_into_view_if_needed()
        box = lane.locator(".lane__header").bounding_box()
        menu = _kebab(board, status).bounding_box()
        add = lane.locator("[data-create-task]").bounding_box()
        assert box is not None and menu is not None and add is not None
        assert add["x"] + add["width"] <= menu["x"] + 1
        assert menu["x"] + menu["width"] <= box["x"] + box["width"] + 1
    _kebab(board, "backlog").click()
    menu_box = _menu(page).bounding_box()
    assert menu_box is not None and menu_box["x"] >= 0
    assert menu_box["x"] + menu_box["width"] <= 390
    page.keyboard.press("Escape")
    expect(page.locator("[data-add-lane]")).to_be_visible()
