"""The artifact dialog: read view, edit, lane and parent changes, the rail."""

from __future__ import annotations

from playwright.sync_api import expect

from tests.e2e.helpers import Board, Dialog


def test_card_opens_the_read_only_view(board: Board) -> None:
    task = board.create("Plan", body="Some text")
    dialog = board.open().open_card("Plan")
    expect(dialog.heading).to_have_text("Artifact")
    expect(dialog.view).to_be_visible()
    expect(dialog.title_input).to_be_hidden()
    expect(dialog.view_title).to_have_text("Plan")
    expect(dialog.view_body).to_have_text("Some text")
    expect(dialog.number).to_have_text(f"#{task['number']}")


def test_edit_and_save_returns_to_the_view(board: Board) -> None:
    board.create("Plan", body="Old")
    dialog = board.open().open_card("Plan").edit()
    expect(dialog.heading).to_have_text("Edit Artifact")
    dialog.title_input.fill("Plan v2")
    dialog.body_input.fill("New")
    dialog.save()
    expect(dialog.view_title).to_have_text("Plan v2")
    expect(dialog.view_body).to_have_text("New")
    expect(dialog.root).to_be_visible()  # stays open
    expect(board.card("Plan v2")).to_be_visible()
    board.expect_field("Plan v2", "body", "New")


def test_cancel_discards_the_edit(board: Board) -> None:
    board.create("Plan")
    dialog = board.open().open_card("Plan").edit()
    dialog.title_input.fill("Changed")
    dialog.root.locator("[data-cancel]").click()
    expect(dialog.view_title).to_have_text("Plan")
    assert "Plan" in board.stored()


def test_saving_without_changes_sends_no_request(board: Board) -> None:
    board.create("Plan")
    dialog = board.open().open_card("Plan").edit()
    requests: list[str] = []
    board.page.on("request", lambda r: requests.append(r.method) if r.method == "PATCH" else None)
    dialog.save()
    expect(dialog.view).to_be_visible()
    assert requests == []


def test_create_after_viewing_starts_with_an_empty_form(board: Board) -> None:
    board.create("Plan", body="text")
    dialog = board.open().open_card("Plan")
    dialog.root.locator("[data-modal-close]").first.click()
    board.page.locator('[data-create-task][data-status="backlog"]').click()
    expect(dialog.heading).to_have_text("Create Artifact")
    expect(dialog.title_input).to_have_value("")
    expect(dialog.number).to_be_hidden()


def test_lane_can_be_changed_in_the_read_view_through_the_chip(board: Board) -> None:
    board.create("Plan")
    dialog = board.open().open_card("Plan")
    dialog.lane_chip.click()
    dialog.root.locator('.lane-chips [data-status="done"]').click()
    expect(dialog.view).to_be_visible()  # still read-only
    expect(dialog.lane_chip).to_have_text("In Done")
    expect(board.lane("done").locator(".task-card")).to_have_count(1)
    board.expect_field("Plan", "status", "done")


def test_lane_can_be_changed_through_the_rail(board: Board) -> None:
    board.create("Plan")
    dialog = board.open().open_card("Plan")
    dialog.rail("lane").click()
    dialog.option("In Progress").click()
    expect(dialog.view).to_be_visible()
    board.expect_field("Plan", "status", "in_progress")


def test_chip_offers_only_the_other_lanes_in_board_order(board: Board) -> None:
    board.create("Plan", status="in_progress")
    dialog = board.open().open_card("Plan")
    dialog.lane_chip.click()
    expect(dialog.root.locator(".lane-chips [data-status]")).to_have_text(["Backlog", "Done"])


def test_create_mode_chip_picks_the_target_lane(board: Board) -> None:
    board.open().page.locator('[data-create-task][data-status="backlog"]').click()
    dialog = board.page.locator("#create-task-modal")
    dialog.locator("[data-modal-subtitle]").click()
    dialog.locator('.lane-chips [data-status="done"]').click()
    dialog.locator("#create-task-modal-field-title").fill("Straight to done")
    dialog.locator("[data-submit]").click()
    expect(board.lane("done").locator(".task-card")).to_have_count(1)


def test_parent_can_be_set_and_cleared_in_the_read_view(board: Board) -> None:
    board.create("Parent")
    board.create("Child")
    dialog = board.open().open_card("Child")
    dialog.rail("parent").click()
    dialog.option("Parent").click()
    expect(dialog.view).to_be_visible()
    board.expect_field("Child", "parent_id", board.stored()["Parent"]["id"])
    expect(board.card("Child").locator(".task-card__meta")).to_contain_text("Parent: Parent")
    dialog.rail("parent").click()
    dialog.option("No parent").click()
    board.expect_field("Child", "parent_id", None)


def test_parent_picker_excludes_the_artifact_and_its_descendants(board: Board) -> None:
    root = board.create("Root")
    child = board.create("Child", parent_id=root["id"])
    board.create("Grandchild", parent_id=child["id"])
    board.create("Other")
    dialog = board.open().open_card("Root")
    dialog.rail("parent").click()
    options = dialog.root.locator(".popover:not([hidden]) [role=option]")
    assert sorted(options.all_inner_texts()) == ["No parent", "Other"]


def test_parent_picker_keeps_every_option_readable_when_the_list_scrolls(board: Board) -> None:
    """With many artifacts the list is longer than its box: the rows must keep their height and scroll.

    A flex column squeezed every row to 0 px (rows hide their overflow, so nothing held them open),
    and the picker looked empty although it had all the artifacts.
    """
    for number in range(40):
        board.create(f"Artifact {number:02d}")
    dialog = board.open().open_card("Artifact 00")
    dialog.rail("parent").click()
    options = dialog.root.locator(".popover:not([hidden]) [role=option]")
    expect(options).to_have_count(40)  # "No parent" and the 39 others
    heights = [box["height"] for box in (options.nth(i).bounding_box() for i in (0, 1, 20))]  # type: ignore[index]  # the options are drawn
    assert all(height >= 24 for height in heights), heights
    popover = dialog.root.locator(".popover:not([hidden])")
    assert popover.evaluate("el => el.scrollHeight > el.clientHeight"), "the list should scroll"


def test_delete_through_the_rail(board: Board) -> None:
    board.create("Plan")
    dialog = board.open().open_card("Plan")
    dialog.root.locator('[data-card-action="delete"]').click()
    board.page.locator("#delete-task-modal [data-confirm]").click()
    expect(board.card("Plan")).to_have_count(0)
    assert board.stored() == {}


def test_rail_toggle_expands_and_keeps_form_and_toggle_in_place(board: Board) -> None:
    board.create("Plan")
    dialog = board.open().open_card("Plan").edit()
    before = (dialog.title_input.bounding_box(), dialog.rail_toggle.bounding_box())
    dialog.rail_toggle.click()
    expect(dialog.root.locator("[data-card-nav]")).to_have_attribute("data-state", "expanded")
    expect(dialog.root.locator('[data-card-action="delete"] .nav-link__label')).to_have_css(
        "opacity", "1"
    )
    dialog.settle()
    assert (dialog.title_input.bounding_box(), dialog.rail_toggle.bounding_box()) == before


def test_rail_is_a_fixed_icon_bar_on_narrow_windows(board: Board) -> None:
    board.create("Plan")
    board.page.set_viewport_size({"width": 700, "height": 800})
    dialog = board.open().open_card("Plan").edit()
    expect(dialog.rail_toggle).to_be_hidden()
    before = dialog.title_input.bounding_box()
    dialog.settle()
    assert dialog.title_input.bounding_box() == before


def test_escape_closes_the_dialog(board: Board) -> None:
    board.create("Plan")
    dialog = board.open().open_card("Plan")
    board.page.keyboard.press("Escape")
    expect(dialog.root).to_be_hidden()


def test_lane_chip_row_pushes_the_form_down_instead_of_overlaying_it(board: Board) -> None:
    board.create("Plan")
    dialog = board.open().open_card("Plan").edit()
    before = dialog.title_input.bounding_box()
    dialog.lane_chip.click()
    expect(dialog.root.locator(".lane-chips")).to_have_attribute("data-open", "")
    dialog.settle()
    after = dialog.title_input.bounding_box()
    assert before is not None and after is not None and after["y"] > before["y"] + 20


def test_lane_chips_carry_the_lane_colours(board: Board) -> None:
    board.create("Plan")
    dialog = board.open().open_card("Plan")
    dialog.lane_chip.click()
    colours = dialog.root.locator(".lane-chips [data-status]").evaluate_all(
        "els => els.map((e) => getComputedStyle(e).backgroundColor)"
    )
    assert len(colours) == 2 and len(set(colours)) == 2


def test_clicking_elsewhere_closes_the_lane_menu_but_not_the_dialog(board: Board) -> None:
    board.create("Plan")
    dialog = board.open().open_card("Plan")
    dialog.lane_chip.click()
    dialog.view_title.click()
    expect(dialog.root.locator(".lane-chips")).not_to_have_attribute("data-open", "")
    expect(dialog.root).to_be_visible()


def test_rail_lane_menu_opens_to_the_left_of_the_rail(board: Board) -> None:
    board.create("Plan")
    dialog = board.open().open_card("Plan")
    dialog.rail("lane").click()
    popover = dialog.root.locator(".popover:not([hidden])").bounding_box()
    rail = dialog.rail("lane").bounding_box()
    assert popover is not None and rail is not None and popover["x"] + popover["width"] <= rail["x"]


def test_rail_icons_and_toggle_share_one_column(board: Board) -> None:
    board.create("Plan")
    dialog = board.open().open_card("Plan")
    centres = [
        (box["x"] + box["width"] / 2)
        for box in (
            dialog.rail("lane").locator(".icon").bounding_box(),
            dialog.root.locator('[data-card-action="delete"] .icon').bounding_box(),
            dialog.rail_toggle.locator(".icon").bounding_box(),
        )
        if box is not None
    ]
    assert len(centres) == 3 and max(centres) - min(centres) <= 1.5


def test_rail_toggle_announces_its_state(board: Board) -> None:
    board.create("Plan")
    dialog = board.open().open_card("Plan")
    expect(dialog.rail_toggle).to_have_attribute("aria-expanded", "false")
    dialog.rail_toggle.click()
    expect(dialog.rail_toggle).to_have_attribute("aria-expanded", "true")
    expect(dialog.rail_toggle).to_have_attribute("aria-label", "Collapse artifact details")


BASE_WIDTH = 556  # 34.75rem: form column plus the collapsed rail
LONG_BODY = "word " * 1200  # 6000 characters


def _size(dialog: Dialog) -> tuple[float, float]:
    box = dialog.root.locator(".modal__panel").bounding_box()
    assert box is not None
    return box["width"], box["height"]


def test_a_short_artifact_keeps_the_base_width(board: Board) -> None:
    board.page.set_viewport_size({"width": 1312, "height": 1400})
    board.create("Plan", body="Some text")
    dialog = board.open().open_card("Plan")
    dialog.settle()
    width, height = _size(dialog)
    assert abs(width - BASE_WIDTH) <= 1
    assert height < 700  # as tall as its content, not as tall as the window


def test_a_medium_artifact_leaves_no_empty_space_below_the_text(board: Board) -> None:
    """The height is measured at the width the dialog ends up with, so the text fills it."""
    board.page.set_viewport_size({"width": 1312, "height": 1400})
    board.create(
        "Plan",
        body="A line of text that is long enough to wrap in a narrow card. " * 3 + "Item\n" * 28,
    )
    dialog = board.open().open_card("Plan")
    dialog.settle()
    body = dialog.root.locator("#artifact-panel-details")
    spare = body.evaluate("el => el.clientHeight - el.scrollHeight")
    assert 0 <= spare <= 48, f"{spare}px empty below the text, panel {_size(dialog)}"
    assert _size(dialog)[1] < 1400 * 0.9


def test_the_size_is_identical_in_view_and_edit_and_after_saving(board: Board) -> None:
    board.page.set_viewport_size({"width": 1312, "height": 1400})
    board.create("Plan", body="Some text\n" * 12)
    dialog = board.open().open_card("Plan")
    dialog.settle()
    view = _size(dialog)
    dialog.edit()
    dialog.settle()
    assert _size(dialog) == view
    dialog.body_input.fill("Short")
    dialog.save()
    expect(dialog.view_title).to_have_text("Plan")
    dialog.settle()
    assert _size(dialog) == view  # fixed until the dialog is closed


def test_a_long_artifact_is_height_limited_wider_and_scrolls(board: Board) -> None:
    board.page.set_viewport_size({"width": 1312, "height": 1400})
    board.create("Plan", body=LONG_BODY)
    dialog = board.open().open_card("Plan")
    dialog.settle()
    width, height = _size(dialog)
    assert abs(height - 1400 * 0.9) <= 1
    assert BASE_WIDTH < width <= 800
    assert width / height <= 0.62 + 0.01
    scrolls = dialog.root.locator("#artifact-panel-details").evaluate(
        "el => el.scrollHeight > el.clientHeight"
    )
    assert scrolls
    dialog.edit()
    dialog.settle()
    assert _size(dialog) == (width, height)
    assert dialog.body_input.evaluate("el => el.scrollHeight > el.clientHeight")


def test_the_width_is_capped_at_800_on_a_large_screen(board: Board) -> None:
    board.page.set_viewport_size({"width": 1920, "height": 1080})
    board.create("Plan", body=LONG_BODY)
    dialog = board.open().open_card("Plan")
    dialog.settle()
    width, height = _size(dialog)
    assert abs(height - 1080 * 0.9) <= 1
    assert BASE_WIDTH <= width <= 800


def test_the_dialog_is_full_width_on_a_phone(board: Board) -> None:
    board.page.set_viewport_size({"width": 390, "height": 800})
    board.create("Plan", body=LONG_BODY)
    dialog = board.open().open_card("Plan")
    dialog.settle()
    width, height = _size(dialog)
    assert abs(width - (390 - 24)) <= 1
    assert height <= 800 * 0.9 + 1
    dialog.edit()
    dialog.settle()
    assert _size(dialog) == (width, height)


def test_creating_keeps_the_small_fixed_size(board: Board) -> None:
    board.page.set_viewport_size({"width": 1312, "height": 1400})
    board.create("Plan", body=LONG_BODY)
    dialog = board.open().open_card("Plan")
    dialog.root.locator("[data-modal-close]").first.click()
    board.page.locator('[data-create-task][data-status="backlog"]').click()
    dialog.settle()
    width, height = _size(dialog)
    assert width < BASE_WIDTH  # no rail
    assert height < 700


def test_the_create_button_says_create(board: Board) -> None:
    board.open().page.locator('[data-create-task][data-status="backlog"]').click()
    expect(board.page.locator("#create-task-modal [data-submit]")).to_have_text("Create")
    board.page.keyboard.press("Escape")
    board.create("Plan")
    board.open().open_card("Plan").edit()
    expect(board.page.locator("#create-task-modal [data-submit]")).to_have_text("Save")
