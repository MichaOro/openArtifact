"""The body with its ${card.x} filled in, in the browser (ADR-064 addendum): the read view shows the finished text
with a calm marker and a toggle, Edit shows the original, the board's card shows the filled in first words, a
reference to nothing is named after the save, and an open dialog follows a field that changes."""

from __future__ import annotations

from playwright.sync_api import expect

from tests.e2e.helpers import Board, eventually

FIELDS = [{"name": "test", "label": "Test", "kind": "text"}]
BODY = "Elias: ${card.test} in ${card.title}"


def _define(board: Board) -> None:
    board.api.put("/api/artifact-fields", json={"fields": FIELDS}).raise_for_status()


def test_the_read_view_shows_the_finished_text_and_edit_the_original(board: Board) -> None:
    _define(board)
    board.api.post(
        "/api/tasks",
        json={"title": "Leuchtturm", "body": BODY, "fields": {"test": "erwachte"}},
    ).raise_for_status()
    board.open()
    card = board.card("Leuchtturm")
    expect(card.locator(".task-card__body")).to_have_text("Elias: erwachte in Leuchtturm")
    dialog = board.open_card("Leuchtturm")
    body = dialog.root.locator("[data-view-body]")
    marker = dialog.root.locator("[data-view-note]")
    expect(body).to_have_text("Elias: erwachte in Leuchtturm")
    expect(marker).to_contain_text("References resolved")
    toggle = marker.get_by_role("button", name="Show as written")
    toggle.click()
    expect(body).to_have_text(BODY)
    marker.get_by_role("button", name="Show resolved").click()
    expect(body).to_have_text("Elias: erwachte in Leuchtturm")
    dialog.root.locator("[data-view-edit]").click()
    expect(dialog.root.locator("[name=body]")).to_have_value(BODY)


def test_a_body_without_a_reference_has_no_marker(board: Board) -> None:
    _define(board)
    board.create("Plain", body="just words")
    board.open()
    dialog = board.open_card("Plain")
    expect(dialog.root.locator("[data-view-body]")).to_have_text("just words")
    expect(dialog.root.locator("[data-view-note]")).to_be_hidden()


def test_saving_a_reference_to_nothing_saves_and_says_so_calmly(board: Board) -> None:
    _define(board)
    board.create("Card", body="plain")
    board.open()
    dialog = board.open_card("Card")
    dialog.root.locator("[data-view-edit]").click()
    dialog.root.locator("[name=body]").fill("see ${card.nope}")
    dialog.root.get_by_role("button", name="Save").click()
    warning = dialog.root.locator("[data-view-warning]")
    expect(warning).to_contain_text("the artifact has no field 'nope'")
    expect(dialog.root.locator("[data-view-body]")).to_have_text("see ${card.nope}")
    expect(dialog.root.locator("[data-view-note]")).to_be_hidden()


def test_an_open_dialog_follows_the_field_it_refers_to(board: Board) -> None:
    _define(board)
    task = board.api.post(
        "/api/tasks", json={"title": "Live", "body": "now: ${card.test}", "fields": {"test": "one"}}
    ).json()
    board.open()
    dialog = board.open_card("Live")
    body = dialog.root.locator("[data-view-body]")
    expect(body).to_have_text("now: one")
    board.api.patch(f"/api/tasks/{task['id']}", json={"fields": {"test": "two"}}).raise_for_status()
    eventually(lambda: body.inner_text(), "now: two")
