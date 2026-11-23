"""The History tab of the artifact dialog: the executions of an artifact, one execution, deleting,
the retention editor, live updates."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import ConsoleMessage, Page, Route, expect

from tests.e2e.helpers import Board, Dialog, echo_pipeline, executions, start, wait_executions
from tests.helpers import slow_pipeline


def _ran(board: Board, api: httpx.Client, runs: int = 1) -> tuple[dict[str, Any], dict[str, Any]]:
    """An artifact with `runs` finished executions of the echo pipeline."""
    pipeline = echo_pipeline(api)
    task = board.create("Item")
    for n in range(runs):
        start(api, task, pipeline)
        wait_executions(api, task, ["done"] * (n + 1))
    return task, pipeline


def _open(board: Board) -> Dialog:
    return board.open().open_card("Item").open_history()


# ── tabs ──────────────────────────────────────────────────────────────


def test_a_saved_artifact_has_aria_tabs_and_create_mode_has_none(board: Board) -> None:
    board.create("Item")
    dialog = board.open().open_card("Item")
    expect(dialog.root.locator("[role=tablist]")).to_be_visible()
    expect(dialog.tabs).to_have_text(["Details", "History", "Comments"])
    expect(dialog.tab("details")).to_have_attribute("aria-selected", "true")
    expect(dialog.tab("history")).to_have_attribute("tabindex", "-1")
    expect(dialog.root.locator("#artifact-panel-details")).to_be_visible()
    dialog.open_history()
    expect(dialog.tab("history")).to_have_attribute("aria-selected", "true")
    expect(dialog.root.locator("#artifact-panel-details")).to_be_hidden()
    expect(dialog.history).to_have_attribute("aria-labelledby", "artifact-tab-history")
    dialog.root.locator("[data-modal-close]").first.click()
    board.page.locator('[data-create-task][data-status="backlog"]').click()
    expect(dialog.root.locator("[role=tablist]")).to_be_hidden()


def test_arrow_keys_switch_the_tabs(board: Board) -> None:
    board.create("Item")
    dialog = board.open().open_card("Item")
    dialog.tab("details").focus()
    board.page.keyboard.press("ArrowRight")
    expect(dialog.tab("history")).to_have_attribute("aria-selected", "true")
    expect(dialog.tab("history")).to_be_focused()
    board.page.keyboard.press("ArrowRight")
    expect(dialog.tab("comments")).to_be_focused()
    board.page.keyboard.press("ArrowRight")  # wraps
    expect(dialog.tab("details")).to_be_focused()
    board.page.keyboard.press("End")
    expect(dialog.tab("comments")).to_be_focused()
    board.page.keyboard.press("Home")
    expect(dialog.tab("details")).to_have_attribute("aria-selected", "true")


def test_the_dialog_keeps_its_size_on_both_tabs_and_in_edit_mode(
    board: Board, api: httpx.Client
) -> None:
    board.page.set_viewport_size({"width": 1312, "height": 1000})
    _ran(board, api, runs=2)
    dialog = board.open().open_card("Item")
    dialog.settle()
    details = dialog.size()
    dialog.open_history()
    dialog.settle()
    assert dialog.size() == details
    dialog.tab("details").click()
    dialog.edit()
    dialog.settle()
    assert dialog.size() == details


def test_the_last_tab_is_remembered_while_the_page_lives(board: Board) -> None:
    board.create("Item")
    dialog = board.open().open_card("Item").open_history()
    dialog.root.locator("[data-modal-close]").first.click()
    board.card("Item").locator(".task-card__title").click()
    expect(dialog.tab("history")).to_have_attribute("aria-selected", "true")
    expect(dialog.history).to_be_visible()


def test_edit_mode_has_no_tabs_and_keeps_the_draft(board: Board) -> None:
    board.create("Item", body="Old")
    dialog = board.open().open_card("Item").open_history()
    expect(dialog.root.locator("[data-view-edit]")).to_be_hidden()  # Close only on History
    dialog.tab("details").click()
    dialog.edit()
    expect(dialog.root.locator("[role=tablist]")).to_be_hidden()
    dialog.body_input.fill("Draft")
    dialog.root.locator("[data-cancel]").click()
    expect(dialog.root.locator("[role=tablist]")).to_be_visible()
    expect(dialog.view_body).to_have_text("Old")


# ── list ──────────────────────────────────────────────────────────────


def test_the_list_shows_the_execution_and_a_restart_adds_number_two(
    board: Board, api: httpx.Client
) -> None:
    task, pipeline = _ran(board, api)
    dialog = _open(board)
    expect(dialog.rows).to_have_count(1)
    row = dialog.row(1)
    expect(row.locator(".history-chip")).to_have_text("Done")
    expect(row.locator("[data-row-pipeline]")).to_have_text("Echo flow")
    expect(row.locator("[data-row-meta]")).to_contain_text("User")
    expect(row.locator("time")).to_have_attribute("title", executions(api, task)[0]["started_at"])
    expect(dialog.root.locator("[data-history-count]")).to_have_text("1")
    start(api, task, pipeline)  # the restart, while the tab is open
    expect(dialog.rows).to_have_count(2)
    expect(dialog.rows.locator("[data-row-number]")).to_have_text(["#2", "#1"])
    expect(dialog.row(2).locator(".history-chip")).to_have_text("Done")
    expect(dialog.root.locator("[data-history-count]")).to_have_text("2")


def test_an_artifact_without_executions_says_so(board: Board) -> None:
    board.create("Item")
    dialog = _open(board)
    expect(dialog.history.locator("[data-history-empty]")).to_contain_text("No executions yet")
    expect(dialog.root.locator("[data-history-count]")).to_be_hidden()


def test_the_origin_is_a_label_and_an_unknown_one_is_shown_as_it_is(
    board: Board, api: httpx.Client
) -> None:
    task, _ = _ran(board, api, runs=3)
    origins = {1: "api", 2: "mcp", 3: "future"}

    def respond(route: Route) -> None:
        body = route.fetch().json()
        for item in body["items"]:
            item["started_by"] = origins[item["number"]]
        route.fulfill(json=body)

    board.page.route(f"**/api/tasks/{task['id']}/executions?*", respond)
    dialog = _open(board)
    expect(dialog.row(1).locator("[data-row-meta]")).to_contain_text("API")
    expect(dialog.row(2).locator("[data-row-meta]")).to_contain_text("MCP")
    expect(dialog.row(3).locator("[data-row-meta]")).to_contain_text("future")


def test_a_running_execution_cannot_be_deleted_and_flips_to_stopped(
    board: Board, api: httpx.Client
) -> None:
    pipeline = slow_pipeline(api)
    task = board.create("Item")
    start(api, task, pipeline)
    dialog = _open(board)
    row = dialog.row(1)
    expect(row.locator(".history-chip")).to_have_text("Running")
    delete = row.locator("[data-row-delete]")
    expect(delete).to_have_attribute("aria-disabled", "true")
    expect(delete).to_have_attribute("title", "Stop it first")
    delete.click(force=True)  # aria-disabled: Playwright would wait for it to be enabled
    expect(board.page.locator("#delete-execution-modal")).not_to_be_visible()
    expect(dialog.history.locator("[data-history-clear]")).to_have_attribute(
        "aria-disabled", "true"
    )
    api.post(f"/api/tasks/{task['id']}/run/stop")
    expect(row.locator(".history-chip")).to_have_text("Stopped")
    expect(delete).to_have_attribute("aria-disabled", "false")


# ── detail ────────────────────────────────────────────────────────────


def test_a_row_opens_the_detail_with_the_steps_and_back_returns_focus(
    board: Board, api: httpx.Client
) -> None:
    _ran(board, api)
    dialog = _open(board)
    dialog.row(1).locator(".history-row__open").focus()
    board.page.keyboard.press("Enter")
    expect(dialog.detail).to_be_visible()
    expect(dialog.detail.locator("[data-detail-heading]")).to_be_focused()
    expect(dialog.detail.locator("[data-detail-heading]")).to_have_text("Execution #1")
    expect(dialog.detail.locator("[data-detail-facts]")).to_contain_text("Echo flow")
    steps = dialog.detail.locator(".history-step")
    expect(steps.first).to_be_visible()
    code = dialog.detail.locator('.history-step[data-kind="code"]')
    expect(code.locator("[data-step-outcome]")).to_have_text("Pass")
    expect(code.locator("[data-step-facts]")).to_contain_text("Exit code: 0")
    block = code.locator("[data-step-output]")
    expect(block.locator("pre")).to_be_hidden()  # collapsed
    block.locator("summary").click()
    expect(block.locator("pre")).to_have_text("hello from echo\n")
    dialog.detail.locator("[data-detail-back]").click()
    expect(dialog.detail).to_be_hidden()
    expect(dialog.row(1).locator(".history-row__open")).to_be_focused()


def test_output_is_shown_as_text_never_as_markup(board: Board, api: httpx.Client) -> None:
    pipeline = echo_pipeline(api, "<b>bold</b>")
    task = board.create("Item")
    start(api, task, pipeline)
    wait_executions(api, task, ["done"])
    dialog = _open(board)
    dialog.row(1).locator(".history-row__open").click()
    code = dialog.detail.locator('.history-step[data-kind="code"]')
    code.locator("[data-step-output] summary").click()
    expect(code.locator("[data-step-output] pre")).to_contain_text("<b>bold</b>")
    assert dialog.detail.locator("pre b").count() == 0


# ── delete and clear ──────────────────────────────────────────────────


def test_delete_asks_first_and_cancel_keeps_the_execution(board: Board, api: httpx.Client) -> None:
    task, _ = _ran(board, api, runs=2)
    dialog = _open(board)
    confirm = board.page.locator("#delete-execution-modal")
    delete = dialog.row(1).locator("[data-row-delete]")
    expect(delete).to_have_attribute("aria-label", "Delete execution #1")
    delete.click()
    expect(confirm).to_be_visible()
    board.page.keyboard.press("Escape")  # closes the confirmation only
    expect(confirm).to_be_hidden()
    expect(dialog.root).to_be_visible()
    expect(delete).to_be_focused()
    expect(dialog.rows).to_have_count(2)
    delete.click()
    confirm.locator("[data-cancel]").click()
    expect(dialog.rows).to_have_count(2)

    delete.click()
    confirm.locator("[data-confirm]").click()
    expect(dialog.rows).to_have_count(1)
    expect(dialog.history.locator("[data-history-live]")).to_have_text("Execution #1 deleted")
    expect(dialog.row(2).locator(".history-row__open")).to_be_focused()
    assert [e["number"] for e in executions(api, task)] == [2]


def test_deleting_from_the_detail_goes_back_to_the_list(board: Board, api: httpx.Client) -> None:
    _ran(board, api, runs=2)
    dialog = _open(board)
    dialog.row(2).locator(".history-row__open").click()
    dialog.detail.locator("[data-detail-delete]").click()
    board.page.locator("#delete-execution-modal [data-confirm]").click()
    expect(dialog.detail).to_be_hidden()
    expect(dialog.rows).to_have_count(1)
    expect(dialog.row(1).locator(".history-row__open")).to_be_focused()


def test_clear_finished_deletes_after_confirmation_and_keeps_a_running_one(
    board: Board, api: httpx.Client
) -> None:
    task, _ = _ran(board, api, runs=2)
    dialog = _open(board)
    confirm = board.page.locator("#delete-execution-modal")
    dialog.history.locator("[data-history-clear]").click()
    expect(confirm).to_contain_text("Delete all finished executions of this artifact?")
    confirm.locator("[data-confirm]").click()
    expect(dialog.rows).to_have_count(0)
    expect(dialog.history.locator("[data-history-empty]")).to_be_visible()
    assert executions(api, task) == []


# ── retention ─────────────────────────────────────────────────────────


def test_the_retention_editor_prunes_validates_and_explains_the_default(
    board: Board, api: httpx.Client
) -> None:
    task, _ = _ran(board, api, runs=3)
    dialog = _open(board)
    policy = dialog.history.locator("[data-policy]")
    expect(policy.locator("[data-policy-state]")).to_have_text("Default: newest 50")
    policy.locator("summary").click()
    expect(policy.locator("[data-policy-help]")).to_contain_text("newest 50")
    expect(policy.locator("[data-policy-help]")).to_contain_text("younger than")

    hours = policy.get_by_label("Keep for ... hours")
    hours.fill("9000")
    policy.locator("[data-policy-save]").click()
    error = policy.locator("#history-keep-hours-error")
    expect(error).to_be_visible()
    expect(hours).to_have_value("9000")  # what was typed stays
    expect(dialog.rows).to_have_count(3)

    policy.get_by_label("Keep the newest ... executions").fill("1")
    hours.fill("24")
    policy.locator("[data-policy-save]").click()
    expect(policy.locator("[data-policy-result]")).to_have_text("2 executions removed")
    expect(policy.locator("[data-policy-state]")).to_have_text(
        "Keeping: newest 1 and not older than 24 hours"
    )
    expect(error).to_be_hidden()
    expect(dialog.rows).to_have_count(1)
    assert [e["number"] for e in executions(api, task)] == [3]

    policy.get_by_label("Keep the newest ... executions").fill("")
    hours.fill("")
    policy.locator("[data-policy-save]").click()
    expect(policy.locator("[data-policy-state]")).to_have_text("Default: newest 50")
    expect(policy.locator("[data-policy-result]")).to_have_text("0 executions removed")


# ── live ──────────────────────────────────────────────────────────────


def test_an_execution_started_elsewhere_appears_and_finishes_without_a_reload(
    board: Board, api: httpx.Client
) -> None:
    pipeline = echo_pipeline(api)
    task = board.create("Item")
    dialog = _open(board)
    expect(dialog.rows).to_have_count(0)
    start(api, task, pipeline)
    expect(dialog.rows).to_have_count(1)
    expect(dialog.row(1).locator(".history-chip")).to_have_text("Done")


def test_the_open_detail_follows_its_execution_and_a_deletion_elsewhere_closes_it(
    board: Board, api: httpx.Client
) -> None:
    pipeline = slow_pipeline(api)
    task = board.create("Item")
    start(api, task, pipeline)
    dialog = _open(board)
    dialog.row(1).locator(".history-row__open").click()
    expect(dialog.detail.locator("[data-detail-facts]")).to_contain_text("Running")
    api.post(f"/api/tasks/{task['id']}/run/stop")
    expect(dialog.detail.locator("[data-detail-facts] .history-chip")).to_have_text("Stopped")
    first = executions(api, task)[0]
    api.delete(f"/api/tasks/{task['id']}/executions/{first['id']}").raise_for_status()
    expect(dialog.detail).to_be_hidden()
    expect(dialog.history.locator("[data-history-summary]")).to_contain_text("was deleted")
    expect(dialog.rows).to_have_count(0)


def test_a_row_deleted_elsewhere_disappears(board: Board, api: httpx.Client) -> None:
    task, _ = _ran(board, api, runs=2)
    dialog = _open(board)
    first = executions(api, task)[1]
    api.delete(f"/api/tasks/{task['id']}/executions/{first['id']}").raise_for_status()
    expect(dialog.rows).to_have_count(1)
    expect(dialog.rows.locator("[data-row-number]")).to_have_text(["#2"])


def test_a_failed_load_keeps_the_content_and_offers_retry(board: Board, api: httpx.Client) -> None:
    task, _ = _ran(board, api)
    dialog = _open(board)
    expect(dialog.rows).to_have_count(1)
    board.page.route(f"**/api/tasks/{task['id']}/executions?*", lambda r: r.abort())
    policy = dialog.history.locator("[data-policy]")
    policy.locator("summary").click()
    policy.locator("[data-policy-save]").click()  # saving reloads the list, which now fails
    alert = dialog.history.locator("[data-history-alert]")
    expect(alert).to_be_visible()
    expect(dialog.rows).to_have_count(1)
    board.page.unroute(f"**/api/tasks/{task['id']}/executions?*")
    alert.locator("[data-alert-retry]").click()
    expect(alert).to_be_hidden()


# ── layout and policy ─────────────────────────────────────────────────


def test_phone_width_fits_without_horizontal_scroll(board: Board, api: httpx.Client) -> None:
    _ran(board, api, runs=2)
    board.page.set_viewport_size({"width": 390, "height": 800})
    dialog = _open(board)
    dialog.settle()
    box = dialog.root.locator(".modal__panel").bounding_box()
    assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= 390
    overflow = dialog.history.evaluate("el => el.scrollWidth - el.clientWidth")
    assert overflow <= 0
    dialog.row(1).locator(".history-row__open").click()
    assert dialog.history.evaluate("el => el.scrollWidth - el.clientWidth") <= 0


def test_the_history_runs_without_a_console_or_policy_error(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    problems: list[str] = []

    def console(message: ConsoleMessage) -> None:
        if message.type in ("error", "warning") or "Content Security Policy" in message.text:
            problems.append(message.text)

    page.on("console", console)
    page.on("pageerror", lambda e: problems.append(str(e)))
    pipeline = echo_pipeline(api)
    task = api.post("/api/tasks", json={"title": "Item"}).json()
    start(api, task, pipeline)
    wait_executions(api, task, ["done"])
    board = Board(page, base_url, api)
    dialog = board.open().open_card("Item").open_history()
    dialog.row(1).locator(".history-row__open").click()
    expect(dialog.detail.locator(".history-step").first).to_be_visible()
    page.wait_for_load_state("networkidle")
    assert problems == []
