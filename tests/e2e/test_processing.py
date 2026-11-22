"""Processing an artifact in a pipeline: start and stop in the dialog, and the lock while it runs."""

from __future__ import annotations

import httpx
from playwright.sync_api import expect

from tests.e2e.helpers import Board
from tests.helpers import slow_pipeline


def test_start_and_stop_in_the_dialog_and_the_artifact_is_locked_while_it_runs(
    board: Board, api: httpx.Client
) -> None:
    slow_pipeline(api, stage_name="Gap analysis")
    task = board.create("Item")
    board.open()
    dialog = board.open_card("Item")
    run = dialog.root.locator('[data-card-action="run"]')
    expect(run).to_contain_text("Start processing")
    expect(dialog.rail("pipeline")).to_contain_text("Flow")
    expect(dialog.rail("stage")).to_contain_text("Gap analysis")

    run.click()
    expect(run).to_contain_text("Stop processing")
    expect(dialog.rail("lane")).to_have_attribute("aria-disabled", "true")
    expect(dialog.rail("stage")).to_have_attribute("aria-disabled", "true")
    expect(board.card("Item").locator(".task-card__run")).to_contain_text("Gap analysis · running")
    assert api.patch(f"/api/tasks/{task['id']}", json={"status": "done"}).status_code == 409

    run.click()
    expect(run).to_contain_text("Start processing")
    expect(dialog.rail("lane")).to_have_attribute("aria-disabled", "false")
    expect(board.card("Item").locator(".task-card__run")).to_contain_text("stopped")
    assert api.patch(f"/api/tasks/{task['id']}", json={"status": "done"}).status_code == 200


def test_the_buttons_stay_where_they_are_when_the_dialog_switches_to_editing(
    board: Board, api: httpx.Client
) -> None:
    slow_pipeline(api, stage_name="Gap analysis")
    board.create("Item")
    board.open()
    dialog = board.open_card("Item")
    close = dialog.root.locator("[data-modal-close]").last.bounding_box()
    edit = dialog.root.locator("[data-view-edit]")
    before = edit.bounding_box()
    dialog.edit()
    dialog.settle()
    save = dialog.root.locator("[data-submit]").bounding_box()
    assert close is not None and before is not None and save is not None
    assert abs(save["y"] - before["y"]) < 2  # Save sits where Edit was
