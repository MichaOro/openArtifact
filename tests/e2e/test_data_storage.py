"""The Data storage section of Settings, Personal in the browser (ADR-084): the sizes of the database, a limit saved when the typing
pauses, the preview, the question before Clean now, what a pass did, and the question before Shrink database."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import echo_pipeline, eventually, executions, start, wait_executions

PERSONAL = "/api/settings/personal"
LIMITS = (
    "storage_keep_executions",
    "storage_step_data_days",
    "storage_run_data_mib",
    "storage_step_output_kib",
    "storage_run_output_kib",
    "storage_clean_interval_hours",
    "storage_warn_mib",
)


def _reset(api: httpx.Client) -> None:
    api.put(PERSONAL, json=dict.fromkeys(LIMITS)).raise_for_status()


@pytest.fixture(autouse=True)
def _clean(api: httpx.Client) -> Iterator[None]:
    """The servers of the browser tests are shared: every limit is empty again afterwards."""
    _reset(api)
    yield
    _reset(api)


def test_a_limit_is_saved_previewed_and_applied_after_a_question_and_the_sizes_are_shown(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    task = api.post("/api/tasks", json={"title": "Runs"}).json()
    pipeline = echo_pipeline(api)
    for count in (1, 2, 3):
        start(api, task, pipeline)
        wait_executions(api, task, ["done"] * count)
    page.goto(f"{base_url}/settings/personal")
    panel = page.locator("[data-storage-panel]")
    result = panel.locator("[data-storage-result]")
    expect(panel.locator("[data-storage-facts]")).to_contain_text("Database file")
    expect(panel.locator("[data-storage-facts]")).to_contain_text("Write-ahead log")
    expect(panel.locator("[data-storage-tables] li").first).to_be_visible()
    expect(panel.locator("[data-storage-warning]")).to_be_hidden()
    # with no limit set nothing is hit
    panel.get_by_role("button", name="Preview").click()
    expect(result).to_contain_text("Nothing to clean")
    # a limit is saved when the typing pauses, and the preview names what it hits
    page.get_by_label("Executions kept per artifact").fill("1")
    eventually(lambda: api.get(PERSONAL).json()["storage_keep_executions"], 1)
    expect(page.locator("[data-status]")).to_have_text("Saved.")
    panel.get_by_role("button", name="Preview").click()
    expect(result).to_contain_text("A pass would delete or empty 2 entries")
    assert len(executions(api, task)) == 3  # a preview changes nothing
    # Clean now asks first and says what it does; Cancel does nothing
    panel.get_by_role("button", name="Clean now").click()
    dialog = page.locator("#storage-confirm")
    expect(dialog).to_contain_text("This deletes or empties 2 entries")
    expect(dialog).to_contain_text("Cards, comments and their history stay")
    dialog.get_by_role("button", name="Cancel").click()
    assert len(executions(api, task)) == 3
    panel.get_by_role("button", name="Clean now").click()
    dialog.get_by_role("button", name="Clean now").click()
    wait_executions(api, task, ["done"])  # only the newest one is left
    expect(result).to_contain_text("The database file went from")
    expect(panel.locator("[data-storage-facts]")).to_contain_text("Last pass")
    expect(panel.locator("[data-storage-facts] dd").nth(5)).not_to_have_text("none yet")


def test_the_warning_shows_when_the_file_is_larger_than_the_set_size_and_shrink_asks_first(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.goto(f"{base_url}/settings/personal")
    panel = page.locator("[data-storage-panel]")
    expect(panel.locator("[data-storage-warning]")).to_be_hidden()
    size = api.get("/api/settings/storage").json()["db"]["file_bytes"]
    assert size < 1024 * 1024 * 1024
    # a threshold of 1 MiB: the file of the test server is below it, so no warning; the setting is shown in the status
    page.get_by_label("Warn when the database is larger than (MiB)").fill("1")
    eventually(lambda: api.get(PERSONAL).json()["storage_warn_mib"], 1)
    eventually(lambda: api.get("/api/settings/storage").json()["db"]["warn_bytes"], 1024 * 1024)
    panel.get_by_role("button", name="Shrink database").click()
    dialog = page.locator("#storage-confirm")
    expect(dialog).to_contain_text("rewrites the whole database file")
    expect(dialog).to_contain_text("Take a backup first")
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden()
