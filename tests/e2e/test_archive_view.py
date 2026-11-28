"""The archive in the browser (ADR-071): the board's menu shows and hides it, it lists only archived cards read only with a panel of
four tabs, "Remove from archive" puts a card back on top of its lane, and a card is archived by hand from the rail of its dialog."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import Board, Dialog, eventually


@pytest.fixture(autouse=True)
def _empty_archive(board: Board) -> Iterator[None]:
    """The shared clean-up only sees the board's cards and an archived one cannot be deleted (409): take them out first."""
    yield
    for task in board.api.get("/api/tasks?archived=only").json():
        board.api.post(f"/api/tasks/{task['id']}/unarchive").raise_for_status()


def _menu(board: Board, label: str) -> None:
    board.page.locator("[data-board-menu]").click()
    board.page.get_by_role("menuitem", name=label).click()


def _archive(board: Board, task: dict[str, Any]) -> None:
    board.api.post(f"/api/tasks/{task['id']}/archive").raise_for_status()


def test_the_menu_shows_the_archive_with_archived_cards_only_and_hides_it_again(
    board: Board,
) -> None:
    kept = board.create("Stays on the board")
    gone = board.create("Old one")
    board.api.post(
        f"/api/tasks/{gone['id']}/comments", json={"body": "a comment"}
    ).raise_for_status()
    _archive(board, gone)
    board.open()
    expect(board.card("Stays on the board")).to_be_visible()
    expect(board.card("Old one")).to_have_count(0)  # an archived card is not on the board
    _menu(board, "Show archive")
    archive = board.page.locator("[data-archive-view]")
    expect(archive).to_be_visible()
    expect(board.page.locator(".board")).to_be_hidden()  # no lanes in the archive
    tiles = archive.locator(".mg-card")
    expect(tiles).to_have_count(1)
    expect(tiles.first).to_contain_text("Old one")
    expect(tiles.first.locator("[data-edit], .is-danger")).to_have_count(0)  # read only
    tiles.first.click()
    panel = archive.locator(".mg__panel")
    expect(panel.locator(".mg-tabs__tab")).to_have_text(
        ["Details", "Comments", "History", "Context"]
    )
    panel.get_by_role("tab", name="Comments").click()
    expect(panel).to_contain_text("a comment")
    panel.get_by_role("tab", name="History").click()
    expect(panel).to_contain_text("moved it to the archive")
    panel.get_by_role("tab", name="Context").click()
    expect(panel).to_contain_text("Backlog")
    expect(panel).not_to_contain_text("Pipeline")
    _menu(board, "Hide archive")
    expect(archive).to_be_hidden()
    expect(board.card(kept["title"])).to_be_visible()


def test_remove_from_archive_puts_the_card_on_top_of_its_lane(board: Board) -> None:
    board.create("First in lane")
    back = board.create("Coming back")
    _archive(board, back)
    board.open()
    _menu(board, "Show archive")
    archive = board.page.locator("[data-archive-view]")
    archive.locator(".mg-card").first.click()
    archive.get_by_role("button", name="Remove from archive").click()
    expect(archive.locator(".mg-card")).to_have_count(0)
    eventually(lambda: board.api.get(f"/api/tasks/{back['id']}").json()["archived_at"], None)
    _menu(board, "Hide archive")
    expect(board.lane("backlog").locator(".task-card__title").first).to_have_text("Coming back")


def test_the_open_archive_shows_a_card_the_sweep_of_a_card_rule_archived(board: Board) -> None:
    """The sweep announces only ``board.updated`` (no ``task.updated`` per card): the open archive reads itself again on it."""
    by_hand = board.create("Archived by hand")
    board.create("Swept by a rule")
    board.open()
    _menu(board, "Show archive")
    tiles = board.page.locator("[data-archive-view] .mg-card")
    expect(tiles).to_have_count(0)
    # first a hand archive (``task.updated``): the live stream of the page is connected before the sweep runs
    _archive(board, by_hand)
    expect(tiles).to_have_count(1)
    rule = {
        "action": "archive",
        "when": {
            "type": "group",
            "mode": "all",
            "items": [
                {"type": "condition", "field": "title", "op": "is", "value": "Swept by a rule"}
            ],
        },
    }
    board.api.put(
        "/api/lanes/backlog/rules", json={"rules": [rule]}
    ).raise_for_status()  # a sweep follows
    expect(tiles).to_have_count(2)
    expect(tiles.filter(has_text="Swept by a rule")).to_have_count(1)


def test_a_card_is_archived_by_hand_from_the_rail_of_its_dialog(board: Board) -> None:
    board.create("Archive me")
    board.open()
    dialog = board.open_card("Archive me")
    dialog.root.locator("[data-card-nav-toggle]").click()
    dialog.root.locator('[data-card-action="archive"]').click()
    expect(board.card("Archive me")).to_have_count(0)
    task = next(
        t for t in board.api.get("/api/tasks?archived=only").json() if t["title"] == "Archive me"
    )
    assert task["archived_at"] is not None


def test_show_more_opens_the_card_in_its_dialog_read_only_with_remove_from_archive(
    board: Board,
) -> None:
    body = "\n".join(f"line {n} of a long text" for n in range(1, 41))
    card = board.create("Long and old", body=body)
    _archive(board, card)
    board.open()
    _menu(board, "Show archive")
    archive = board.page.locator("[data-archive-view]")
    archive.locator(".mg-card").first.click()
    archive.get_by_role("button", name="Show more").click()
    dialog = Dialog(board.page)
    expect(dialog.root).to_be_visible()
    expect(dialog.view_title).to_have_text("Long and old")
    expect(dialog.view_body).to_contain_text(
        "line 40 of a long text"
    )  # the whole text, not six lines
    # nothing in the window writes: no Edit, no Run, no comment box or Send, no input in the rail, no Archive, no Delete
    for writes in (
        "[data-view-edit]",
        '[data-card-action="run"]',
        "[data-comments-form]",
        "[data-comments-send]",
        '[data-card-action="delete"]',
    ):
        expect(dialog.root.locator(writes)).to_be_hidden()
    expect(
        dialog.root.locator('[data-card-action="archive"]')
    ).to_be_hidden()  # invisible, but its place stays
    for field in ("lane", "parent", "pipeline", "stage", "action"):
        expect(dialog.root.locator(f'[data-card-field="{field}"]')).to_be_disabled()
    dialog.root.locator("[data-card-nav-toggle]").click()
    remove = dialog.root.locator('[data-card-action="unarchive"]')
    expect(remove).to_be_visible()
    expect(remove).to_contain_text("Remove from archive")
    # it sits where Delete sits on a normal card: the last entry of the rail
    last = dialog.root.locator(".card-nav__actions li").last
    assert last.locator('[data-card-action="unarchive"]').count() == 1
    remove.click()
    expect(dialog.root).to_be_hidden()
    expect(archive.locator(".mg-card")).to_have_count(0)
    eventually(lambda: board.api.get(f"/api/tasks/{card['id']}").json()["archived_at"], None)


def test_a_card_of_the_board_keeps_its_edit_and_delete_after_an_archived_one_was_shown(
    board: Board,
) -> None:
    """The read-only mode is opt-in per opening: the next regular card is writable again."""
    old = board.create("Old and read only", body="\n".join(f"row {n}" for n in range(1, 41)))
    board.create("Plain card")
    _archive(board, old)
    board.open()
    _menu(board, "Show archive")
    archive = board.page.locator("[data-archive-view]")
    archive.locator(".mg-card").first.click()
    archive.get_by_role("button", name="Show more").click()
    dialog = Dialog(board.page)
    expect(dialog.root).to_be_visible()
    dialog.root.get_by_role("button", name="Close", exact=True).click()
    _menu(board, "Hide archive")
    dialog = board.open_card("Plain card")
    expect(dialog.root.locator("[data-view-edit]")).to_be_visible()
    dialog.root.locator("[data-card-nav-toggle]").click()
    expect(dialog.root.locator('[data-card-action="delete"]')).to_be_visible()
    expect(dialog.root.locator('[data-card-action="archive"]')).to_be_visible()
    expect(dialog.root.locator('[data-card-action="unarchive"]')).to_be_hidden()
    expect(dialog.root.locator('[data-card-field="lane"]')).to_be_enabled()


_BOXES = """(root) => {
  const box = (sel) => { const e = root.querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect(); return {l: r.left, r: r.right, t: r.top, b: r.bottom}; };
  const row = root.getBoundingClientRect();
  const style = getComputedStyle(root);
  return {
    row: {l: row.left, r: row.right, t: row.top, b: row.bottom},
    padRight: parseFloat(style.paddingRight), padLeft: parseFloat(style.paddingLeft),
    name: box('.mg-card__name'), number: box('.mg-card__chips .mg-chip'),
    lane: box('.mg-card__facts'), date: box('.mg-card__date'),
  };
}"""


def _archived(board: Board, title: str, lane: str = "backlog") -> dict[str, Any]:
    task = board.create(title, status=lane)
    _archive(board, task)
    return task


def _open_archive(board: Board, view: str) -> Any:
    board.open()
    _menu(board, "Show archive")
    archive = board.page.locator("[data-archive-view]")
    expect(archive).to_be_visible()
    board.page.get_by_role("button", name=view, exact=True).click()
    return archive


def test_an_archive_row_has_the_title_and_number_on_one_line_and_the_lane_and_day_below(
    board: Board,
) -> None:
    _archived(board, "A title that is long enough to be a title of a real card")
    archive = _open_archive(board, "List")
    row = archive.locator(".mg-card").first
    expect(row).to_be_visible()
    m = row.evaluate(_BOXES)
    right = m["row"]["r"] - m["padRight"]
    left = m["row"]["l"] + m["padLeft"]
    assert m["name"]["l"] <= left + 2, f"the title starts at the left of the row: {m}"
    assert abs(m["number"]["r"] - right) <= 2, f"the number is flush right: {m}"
    assert m["number"]["l"] > m["name"]["l"], "the number stands to the right of the title"
    assert abs(m["number"]["t"] - m["name"]["t"]) < 12, "the number is on the line of the title"
    assert m["lane"]["t"] >= m["name"]["b"] - 2, f"the lane is below the title: {m}"
    assert abs(m["lane"]["l"] - m["name"]["l"]) <= 2, "the lane starts under the title"
    assert abs(m["date"]["r"] - right) <= 2, f"the day of archiving is flush right: {m}"
    assert m["date"]["t"] >= m["number"]["b"] - 2, "the day stands under the number"
    expect(row.locator(".mg-card__facts")).to_have_text("From lane: Backlog")
    expect(row.locator(".mg-card__date")).to_contain_text("Archived")


def test_the_lane_of_an_archived_card_says_from_lane_in_tiles_and_in_the_context(
    board: Board,
) -> None:
    _archived(board, "A card from the backlog")
    archive = _open_archive(board, "Cards")
    tile = archive.locator(".mg-card").first
    expect(tile.locator(".mg-card__facts")).to_have_text("From lane: Backlog")
    tile.click()
    panel = archive.locator(".mg__panel")
    panel.get_by_role("tab", name="Context").click()
    context = panel.get_by_role("tabpanel", name="Context")
    expect(context.locator("dt").first).to_have_text("From lane")
    expect(context.locator("dd").first).to_have_text("Backlog")


def test_a_card_whose_lane_is_gone_says_so_instead_of_showing_nothing(board: Board) -> None:
    _archived(board, "From a lane that no longer exists")

    def without_lane(route: Any) -> None:
        response = route.fetch()
        items = response.json()
        for item in items:
            item["archived_from_lane"] = None  # what the API sends when the lane is gone
        route.fulfill(response=response, json=items)

    board.page.route("**/api/tasks?archived=only*", without_lane)
    archive = _open_archive(board, "Cards")
    expect(archive.locator(".mg-card__facts").first).to_have_text(
        "From lane: (lane no longer exists)"
    )
    # the stub may still be answering a request when the test ends: let it finish quietly instead of failing the next test
    board.page.unroute_all(behavior="ignoreErrors")


def test_archive_rows_do_not_overlap_at_a_narrow_width(board: Board) -> None:
    _archived(board, "A very long title " * 6)
    board.page.set_viewport_size({"width": 390, "height": 800})
    archive = _open_archive(board, "List")
    row = archive.locator(".mg-card").first
    expect(row).to_be_visible()
    m = row.evaluate(_BOXES)
    for a, b in (("name", "number"), ("lane", "date"), ("name", "lane"), ("number", "date")):
        x, y = m[a], m[b]
        overlap = (
            x["l"] < y["r"] - 1
            and y["l"] < x["r"] - 1
            and x["t"] < y["b"] - 1
            and y["t"] < x["b"] - 1
        )
        assert not overlap, f"{a} and {b} overlap: {m}"
    assert m["number"]["r"] <= m["row"]["r"] + 1 and m["date"]["r"] <= m["row"]["r"] + 1
