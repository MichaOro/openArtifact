"""Lane settings and the UI conventions in the browser: the lane's Settings dialog (its rules, ADR-071) and the card look they
set, the Add lane button in the board's action row, one purple primary action, one destructive style."""

from __future__ import annotations

import re

from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import Board
from tests.e2e.test_csp import _watch

DONE = "task-card--done"
#: A rule of a lane that sets its cards as done (what the switch "Cards look finished" was before ADR-071).
SET_DONE = {
    "rules": [{"action": "set_done", "when": {"type": "group", "mode": "all", "items": []}}]
}


def _open_settings(board: Board, status: str = "done") -> Locator:
    board.lane(status).locator("[data-lane-menu]").click()
    board.page.get_by_role("menuitem", name="Settings").click()
    dialog = board.page.locator("#card-rules-modal")
    expect(dialog).to_be_visible()
    return dialog


def _add_rule(dialog: Locator) -> None:
    """Add a rule (it opens) and go back to the list."""
    dialog.get_by_role("button", name="Add rule").click()
    dialog.get_by_role("button", name="Done", exact=True).click()


def _strike(card: Locator) -> str:
    return str(
        card.locator(".task-card__title").evaluate("e => getComputedStyle(e).textDecorationLine")
    )


def _settle(page: Page) -> None:
    page.evaluate("Promise.all(document.getAnimations().map((a) => a.finished.catch(() => {})))")


def _colour(page: Page, value: str) -> str:
    """A CSS colour as the browser computes it (``var(--color-danger)`` -> ``rgb(...)``)."""
    return str(
        page.evaluate(
            """v => { const e = document.createElement('i'); e.style.color = v; document.body.append(e);
        const c = getComputedStyle(e).color; e.remove(); return c; }""",
            value,
        )
    )


def test_add_lane_is_in_the_board_action_row_and_not_in_the_header(board: Board) -> None:
    board.open()
    page = board.page
    expect(page.locator(".app-header").get_by_text("Add lane")).to_have_count(0)
    expect(page.locator(".app-header [data-add-lane]")).to_have_count(0)
    button = page.locator(".action-row [data-add-lane]")
    expect(button).to_be_visible()
    box, lane = button.bounding_box(), board.lane("done").bounding_box()
    assert box is not None and lane is not None
    assert box["y"] + box["height"] <= lane["y"]  # above the board
    menu = page.locator(".action-row [data-board-menu]").bounding_box()
    assert menu is not None
    assert (
        menu["x"] + menu["width"] >= lane["x"] + lane["width"] - 1
    )  # the row ends at the board's right edge
    assert box["x"] + box["width"] <= menu["x"]  # Add lane, then the board's menu (ADR-044)
    assert box["height"] <= 34  # slim
    button.click()
    expect(page.locator("#add-lane-modal")).to_be_visible()


def test_add_lane_and_the_new_buttons_are_one_purple_primary_action(
    board: Board, base_url: str
) -> None:
    board.open()
    add = board.page.locator("[data-add-lane]")
    colour = add.evaluate("e => getComputedStyle(e).backgroundColor")
    assert re.search(r"\bbutton--primary\b", add.get_attribute("class") or "")
    assert colour == _colour(board.page, "var(--color-accent)")
    for path, selector in (
        ("/actions", "[data-new-graph]"),
        ("/pipelines", "[data-new-graph]"),
    ):
        board.page.goto(f"{base_url}{path}")
        button = board.page.locator(selector)
        expect(button).to_have_class(re.compile(r"\bbutton--primary\b"))
        assert button.evaluate("e => getComputedStyle(e).backgroundColor") == colour


def test_the_lane_menu_has_settings_between_rename_and_delete(board: Board) -> None:
    board.open()
    board.lane("done").locator("[data-lane-menu]").click()
    expect(board.page.locator(".menu:not([hidden]) [role=menuitem]")).to_have_text(
        ["Rename", "Settings", "Delete"]
    )


def test_the_rules_dialog_saves_a_rule_that_marks_the_cards_in_all_tabs(board: Board) -> None:
    board.create("Shipped thing", status="done", body="It went out.")
    board.open()
    other = Board(board.page.context.new_page(), board.base_url, board.api)
    other.open()
    board.page.bring_to_front()
    card = board.card("Shipped thing")
    assert _strike(card) == "none"
    dialog = _open_settings(board)
    expect(dialog).to_have_attribute("aria-labelledby", "card-rules-modal-title")
    expect(dialog.locator(".modal__title")).to_have_text("Lane settings")
    expect(dialog.locator("[data-modal-chip]")).to_have_text("Done")
    expect(dialog.get_by_text("No rules yet")).to_be_visible()
    dialog.get_by_role("button", name="Add rule").click()
    # the open rule: Then "Set card as done" is the first action of a lane, and a card is drawn as the rule draws it
    expect(dialog.get_by_label("Then")).to_have_value("set_done")
    sample = dialog.locator("[data-rule-sample] .task-card")
    expect(sample).to_have_class(re.compile(DONE))
    assert _strike(sample) == "line-through"
    expect(dialog.locator("[data-rule-count]")).to_have_text("1 card matches now.")
    dialog.get_by_role("button", name="Done", exact=True).click()
    dialog.get_by_role("button", name="Save").click()
    expect(dialog).not_to_be_visible()
    assert board.api.get("/api/lanes/done/rules").json()["rules"][0]["action"] == "set_done"
    expect(card).to_have_class(re.compile(DONE))
    assert _strike(card) == "line-through"
    assert (
        card.locator(".task-card__body").evaluate("e => getComputedStyle(e).textDecorationLine")
        == "none"
    )
    expect(other.card("Shipped thing")).to_have_class(re.compile(DONE))  # live
    board.page.reload()
    expect(board.card("Shipped thing")).to_have_class(re.compile(DONE))
    # and back: the other tab follows
    board.api.put("/api/lanes/done/rules", json={"rules": []}).raise_for_status()
    expect(other.card("Shipped thing")).not_to_have_class(re.compile(DONE))


def test_hovering_a_rule_shows_the_card_it_makes(board: Board) -> None:
    board.create("Shipped thing", status="done")
    board.api.put("/api/lanes/done/rules", json=SET_DONE).raise_for_status()
    board.open()
    dialog = _open_settings(board)
    dialog.locator(".rl-row").first.hover()
    popover = dialog.locator("[data-popover]")
    expect(popover).to_be_visible()
    expect(popover.locator(".task-card")).to_have_class(re.compile(DONE))
    expect(popover.locator("[data-popover-caption]")).to_contain_text("1 card matches now.")


def test_a_card_takes_the_look_of_the_lane_it_is_moved_into(board: Board) -> None:
    board.create("Moving", status="backlog")
    board.api.put("/api/lanes/done/rules", json=SET_DONE).raise_for_status()
    board.open()
    card = board.card("Moving")
    assert _strike(card) == "none"
    board.drag(card, board.lane("done").locator(".empty-state"))
    expect(board.lane("done").locator(".task-card")).to_have_count(1)
    # the server's answer brings the marks of the new lane (the rules decide, not the lane): wait for it
    expect(board.card("Moving")).to_have_class(re.compile(DONE))
    assert _strike(board.card("Moving")) == "line-through"


def test_cancel_and_escape_discard_and_focus_returns_to_the_menu_button(board: Board) -> None:
    board.open()
    page = board.page
    button = board.lane("done").locator("[data-lane-menu]")
    dialog = _open_settings(board)
    _add_rule(dialog)
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).not_to_be_visible()
    expect(button).to_be_focused()
    assert board.api.get("/api/lanes/done/rules").json()["rules"] == []
    dialog = _open_settings(board)
    expect(dialog.get_by_text("No rules yet")).to_be_visible()  # the discarded rule is gone
    _add_rule(dialog)
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    expect(button).to_be_focused()
    assert board.api.get("/api/lanes/done/rules").json()["rules"] == []
    # the dialog is modal
    dialog = _open_settings(board)
    assert dialog.evaluate("d => d.matches(':modal')")


def test_the_settings_dialog_keeps_its_size_and_fits_a_phone(board: Board) -> None:
    problems = _watch(board.page)
    board.open()
    dialog = _open_settings(board)
    panel = dialog.locator(".modal__panel")
    _settle(board.page)
    board.page.set_viewport_size({"width": 390, "height": 800})
    box = panel.bounding_box()
    assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= 390
    assert board.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    board.page.wait_for_load_state("networkidle")
    assert problems == []


def test_the_dark_theme_keeps_the_done_look_readable(board: Board) -> None:
    board.create("Shipped thing", status="done", body="It went out.")
    board.api.put("/api/lanes/done/rules", json=SET_DONE).raise_for_status()
    board.page.emulate_media(color_scheme="dark")
    board.open()
    board.page.evaluate("document.documentElement.dataset.theme = 'dark'")
    card = board.card("Shipped thing")
    assert _strike(card) == "line-through"
    opacity = card.evaluate("e => getComputedStyle(e).opacity")
    assert 0.6 <= float(opacity) <= 0.8


def test_every_delete_control_uses_the_one_destructive_style(board: Board, base_url: str) -> None:
    board.create("Card", status="done")
    board.api.post("/api/pipelines", json={"name": "Pipe"}).raise_for_status()
    board.api.post("/api/actions", json={"name": "Act"}).raise_for_status()
    page = board.page
    board.open()
    danger = _colour(page, "var(--color-danger)")
    tint = _colour(page, "color-mix(in srgb, var(--color-danger) 12%, transparent)")
    # menu item: red at rest (when it can be used), a red background only on hover
    board.api.post("/api/lanes", json={"title": "Empty"}).raise_for_status()
    page.reload()
    page.locator('[data-lane][data-status="empty"] [data-lane-menu]').click()
    item = page.get_by_role("menuitem", name="Delete")
    expect(item).to_have_class(re.compile(r"\bis-danger\b"))
    expect(item).to_have_css("color", danger)
    expect(item.locator(".icon")).to_have_css("color", danger)
    assert item.evaluate("e => getComputedStyle(e).backgroundColor") != tint
    page.locator(".menu__item", has_text="Rename").hover()
    assert item.evaluate("e => getComputedStyle(e).backgroundColor") == "rgba(0, 0, 0, 0)"
    item.hover()
    expect(item).to_have_css("background-color", tint)
    page.keyboard.press("Escape")
    # icon buttons: red on hover
    card = board.card("Card")
    card.hover()
    trash = card.locator("[data-delete-task]")
    trash.hover()
    expect(trash).to_have_css("color", danger)
    for path, selector in (
        ("/actions", ".mg-card [data-delete]"),
        ("/pipelines", ".mg-card [data-delete]"),
    ):
        page.goto(f"{base_url}{path}")
        control = page.locator(selector).first
        expect(control).to_have_class(re.compile(r"\bis-danger\b"))
        control.hover()
        expect(control).to_have_css("color", danger)
        expect(control).to_have_css("background-color", tint)


def test_scroll_areas_have_a_transparent_track(board: Board) -> None:
    board.open()
    colour = (
        board.lane("done")
        .locator(".lane__cards")
        .evaluate("e => getComputedStyle(e).scrollbarColor")
    )
    assert colour.endswith("rgba(0, 0, 0, 0)")
    assert not colour.startswith("auto")
