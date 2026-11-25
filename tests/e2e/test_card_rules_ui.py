"""The rules editor in the browser (ADR-071): a label and a colour rule mark the cards of a lane (board and card dialog), a rule is
built in the dialog, and the board's Settings: a rule that deletes starts off and asks, with the number, before it deletes."""

from __future__ import annotations

import re

from playwright.sync_api import expect

from tests.e2e.helpers import Board, eventually

EVERY_CARD = {"type": "group", "mode": "all", "items": []}


def _open_board_settings(board: Board):  # type: ignore[no-untyped-def]
    board.page.locator("[data-board-menu]").click()
    board.page.get_by_role("menuitem", name="Settings").click()
    dialog = board.page.locator("#card-rules-modal")
    expect(dialog).to_be_visible()
    return dialog


def test_a_label_and_a_colour_rule_mark_the_cards_on_the_board_and_in_the_dialog(
    board: Board,
) -> None:
    board.create("Marked", status="done", body="Text")
    rules = [
        {"action": "label", "when": EVERY_CARD, "params": {"text": "Old", "tone": "red"}},
        {"action": "colour", "when": EVERY_CARD, "params": {"tone": "green", "mode": "border"}},
    ]
    board.api.put("/api/lanes/done/rules", json={"rules": rules}).raise_for_status()
    board.open()
    card = board.card("Marked")
    expect(card.locator(".card-label")).to_have_text(["Old"])
    expect(card).to_have_attribute("data-colour-tone", "green")
    expect(card).to_have_attribute("data-colour-mode", "border")
    shadow = card.evaluate("e => getComputedStyle(e).boxShadow")
    assert shadow != "none"
    dialog = board.open_card("Marked")
    expect(dialog.root.locator(".task-view__labels .card-label")).to_have_text(["Old"])
    expect(dialog.root.locator(".task-view__title")).not_to_have_class(re.compile("--done"))


def test_a_rule_is_built_in_the_dialog_with_its_settings_and_a_preview_card(board: Board) -> None:
    board.create("Marked", status="done")
    board.open()
    board.lane("done").locator("[data-lane-menu]").click()
    board.page.get_by_role("menuitem", name="Settings").click()
    dialog = board.page.locator("#card-rules-modal")
    dialog.get_by_role("button", name="Add rule").click()
    dialog.get_by_label("Then").select_option("label")
    dialog.get_by_label("Label text").fill("Check")
    dialog.get_by_label("Tone").select_option("yellow")
    expect(dialog.locator("[data-rule-sample] .card-label")).to_have_text(["Check"])
    dialog.get_by_role("button", name="Done", exact=True).click()
    dialog.get_by_role("button", name="Save").click()
    expect(dialog).not_to_be_visible()
    saved = board.api.get("/api/lanes/done/rules").json()["rules"]
    assert saved[0]["action"] == "label"
    assert saved[0]["params"] == {"text": "Check", "tone": "yellow"}
    expect(board.card("Marked").locator(".card-label")).to_have_text(["Check"])


def test_the_board_settings_have_no_set_as_done_and_a_delete_rule_starts_off_and_asks(
    board: Board,
) -> None:
    kept = board.create("Kept", status="done")
    board.create("Gone", status="done")
    gone = board.stored()["Gone"]
    board.api.post(f"/api/tasks/{gone['id']}/archive").raise_for_status()
    board.open()
    dialog = _open_board_settings(board)
    expect(dialog.locator(".modal__title")).to_have_text("Board settings")
    dialog.get_by_role("button", name="Add rule").click()
    options = dialog.get_by_label("Then").locator("option").all_inner_texts()
    assert "Set card as done" not in options
    assert "Delete the archived card" in options
    dialog.get_by_label("Then").select_option("delete")
    dialog.get_by_role("button", name="Add condition").click()
    dialog.get_by_label("Field").select_option(label="Time since archived")
    dialog.get_by_label("Operator").select_option(label="is below")
    dialog.get_by_role("button", name="Done", exact=True).click()
    switch = dialog.locator(".rl-row").first.get_by_role("switch")
    expect(switch).not_to_be_checked()  # a rule that deletes starts off
    dialog.get_by_role("button", name="Save").click()  # off: it deletes nothing, so it is saved
    expect(dialog).not_to_be_visible()
    assert board.api.get("/api/board/rules").json()["rules"][0]["enabled"] is False
    dialog = _open_board_settings(board)
    switch = dialog.locator(".rl-row").first.get_by_role("switch")
    switch.check()
    dialog.get_by_role("button", name="Save").click()
    expect(dialog.locator("[data-delete-warning]")).to_contain_text("delete 1 archived card")
    assert (
        board.api.get("/api/board/rules").json()["rules"][0]["enabled"] is False
    )  # nothing changes until it is confirmed
    dialog.get_by_role("button", name="Save and delete").click()
    expect(dialog).not_to_be_visible()
    assert board.api.get("/api/board/rules").json()["rules"][0]["enabled"] is True
    assert kept["title"] in board.stored()
    eventually(
        lambda: board.api.get("/api/tasks", params={"archived": "only"}).json(), []
    )  # the archived card is gone
