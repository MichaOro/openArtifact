"""The Data storage section of Settings, Personal in the browser (ADR-084): the sizes of the database, a limit saved when the typing
pauses, the preview, the question before Clean now, what a pass did, and the question before Shrink database."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from playwright.sync_api import Page, ViewportSize, expect

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
    page.goto(f"{base_url}/settings/personal#database")
    panel = page.locator("[data-storage-panel]")
    result = panel.locator("[data-storage-result]")
    expect(panel.locator("[data-storage-facts]")).to_contain_text("Database file")
    expect(panel.locator("[data-storage-facts]")).to_contain_text("Write-ahead log")
    expect(
        panel.locator("[data-storage-tables] li").first
    ).to_be_visible()  # the biggest tables are a list with the size on the right
    expect(panel.locator("[data-storage-warning]")).to_be_hidden()
    # with no limit set nothing is hit
    panel.get_by_role("button", name="Preview").click()
    expect(result).to_contain_text("Nothing to clean")
    # a limit is saved when the typing pauses, and the preview names what it hits
    page.get_by_role("tab", name="Data storage").click()
    page.locator('input[data-field-key="storage_keep_executions"]').fill("1")
    eventually(lambda: api.get(PERSONAL).json()["storage_keep_executions"], 1)
    expect(page.locator("[data-status]")).to_have_text("Saved.")
    page.get_by_role("tab", name="Database").click()
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
    page.goto(f"{base_url}/settings/personal#storage")
    panel = page.locator("[data-storage-panel]")
    size = api.get("/api/settings/storage").json()["db"]["file_bytes"]
    assert size < 1024 * 1024 * 1024
    # a threshold of 1 MiB: the file of the test server is below it, so no warning; the setting is shown in the status. The switch is
    # off until it is switched on (a limit that is off by default is a switch, not an empty field).
    page.locator('button[data-field-key="storage_warn_mib"]').click()
    page.locator('input[data-field-key="storage_warn_mib"]').fill("1")
    eventually(lambda: api.get(PERSONAL).json()["storage_warn_mib"], 1)
    eventually(lambda: api.get("/api/settings/storage").json()["db"]["warn_bytes"], 1024 * 1024)
    page.get_by_role("tab", name="Database").click()
    expect(panel.locator("[data-storage-warning]")).to_be_hidden()
    panel.get_by_role("button", name="Shrink database").click()
    dialog = page.locator("#storage-confirm")
    expect(dialog).to_contain_text("rewrites the whole database file")
    expect(dialog).to_contain_text("Take a backup first")
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden()


# ── the tabs, the defaults, the switches ─────────────────────────────────

_OVERLAP = """(card) => {
  const box = (e) => { const r = e.getBoundingClientRect(); return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height}; };
  const shown = (b) => b.w > 0 && b.h > 0; // a hidden element has no box
  const c = box(card);
  const panel = [...card.querySelectorAll('[role=tabpanel]')].find((p) => !p.hidden);
  const blocks = [...panel.querySelectorAll('.fv-field, .st-facts, .st-tablelist, .st-actions-grid, .st-intro')].map(box).filter(shown);
  const parts = [...panel.querySelectorAll('input, button, .fv-limit, fieldset, .st-action')].map(box).filter(shown);
  const outside = parts.filter((b) => b.r > c.r + 1 || b.l < c.l - 1);
  let crossing = 0;
  for (let i = 1; i < blocks.length; i += 1) {
    const a = blocks[i - 1], b = blocks[i];
    if (b.t < a.b - 1 && b.l < a.r && b.r > a.l) crossing += 1;
  }
  return {outside: outside.length, crossing, overflow: card.scrollWidth > card.clientWidth + 1};
}"""


@pytest.mark.parametrize(
    "size", [ViewportSize(width=1280, height=900), ViewportSize(width=390, height=844)]
)
def test_no_tab_has_an_element_lying_over_another_or_out_of_its_card(
    page: Page, base_url: str, size: ViewportSize
) -> None:
    """The first layout was one long form whose fieldset was wider than its card: nothing may leave the card or lie over another element."""
    page.set_viewport_size(size)
    for tab in ("general", "storage", "database"):
        page.goto(f"{base_url}/settings/personal#{tab}")
        card = page.locator(".st-page .st-card")
        expect(page.locator(f"#st-panel-{tab}")).to_be_visible()
        expect(
            page.locator(f"#st-panel-{tab} .fv-field, #st-panel-{tab} .st-facts").first
        ).to_be_visible()
        found = card.evaluate(_OVERLAP)
        assert found == {"outside": 0, "crossing": 0, "overflow": False}, (
            f"{tab} at {size}: {found}"
        )


def test_the_three_tabs_keep_their_place_in_the_address_and_the_keys_move_between_them(
    page: Page, base_url: str
) -> None:
    page.goto(f"{base_url}/settings/personal")
    tabs = page.get_by_role("tablist").first
    expect(tabs.get_by_role("tab")).to_have_text(["General", "Data storage", "Database"])
    expect(tabs.get_by_role("tab", name="General")).to_have_attribute("aria-selected", "true")
    page.get_by_role("tab", name="Database").click()
    assert page.url.endswith("#database")
    page.reload()  # a reload and a link open the same tab
    expect(page.get_by_role("tab", name="Database")).to_have_attribute("aria-selected", "true")
    expect(page.locator("[data-storage-facts]")).to_be_visible()
    page.get_by_role("tab", name="Database").press("ArrowLeft")
    expect(page.get_by_role("tab", name="Data storage")).to_have_attribute("aria-selected", "true")
    assert page.url.endswith("#storage")
    page.goto(f"{base_url}/settings/personal#storage")
    expect(page.locator("#st-panel-storage")).to_be_visible()
    expect(page.locator("#st-panel-general")).to_be_hidden()


def test_a_field_nobody_set_shows_its_default_and_typing_the_default_back_stores_nothing(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.goto(f"{base_url}/settings/personal#storage")
    keep = page.locator('input[data-field-key="storage_keep_executions"]')
    step = page.locator('input[data-field-key="storage_step_output_kib"]')
    run = page.locator('input[data-field-key="storage_run_output_kib"]')
    expect(keep).to_have_value("50")  # the operator's number, not an empty field
    expect(step).to_have_value("256")
    expect(run).to_have_value("1024")
    reset = page.get_by_role("button", name="Reset to default: Executions kept per artifact")
    expect(reset).to_be_hidden()
    keep.fill("5")
    eventually(lambda: api.get(PERSONAL).json()["storage_keep_executions"], 5)
    expect(reset).to_be_visible()
    reset.click()  # the default is stored as 'not set' again
    expect(keep).to_have_value("50")
    eventually(lambda: api.get(PERSONAL).json()["storage_keep_executions"], None)
    expect(reset).to_be_hidden()
    keep.fill("7")
    eventually(lambda: api.get(PERSONAL).json()["storage_keep_executions"], 7)
    keep.fill(
        "50"
    )  # typing the default back stores nothing, so a later change of the default still applies
    eventually(lambda: api.get(PERSONAL).json()["storage_keep_executions"], None)


def test_a_limit_that_is_off_by_default_is_a_switch_and_its_number_shows_only_while_it_is_on(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.goto(f"{base_url}/settings/personal#storage")
    switch = page.locator('button[data-field-key="storage_step_data_days"]')
    number = page.locator('input[data-field-key="storage_step_data_days"]')
    expect(switch).to_have_attribute("aria-checked", "false")
    expect(number).to_be_hidden()
    switch.click()  # on: the suggested number, saved at once
    expect(number).to_be_visible()
    expect(number).to_have_value("30")
    expect(page.locator("#st-panel-storage")).to_contain_text("days")
    eventually(lambda: api.get(PERSONAL).json()["storage_step_data_days"], 30)
    number.fill("14")
    eventually(lambda: api.get(PERSONAL).json()["storage_step_data_days"], 14)
    switch.click()  # off forgets the number
    expect(number).to_be_hidden()
    eventually(lambda: api.get(PERSONAL).json()["storage_step_data_days"], None)


def test_the_cleaner_has_a_switch_with_its_interval_and_the_database_tab_shows_its_state(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.goto(f"{base_url}/settings/personal#database")
    cleaner = page.locator("[data-storage-facts] dd").nth(4)
    expect(cleaner).to_contain_text("off")
    expect(cleaner.get_by_role("link", name="Change")).to_be_visible()
    cleaner.get_by_role("link", name="Change").click()  # to the setting
    expect(page.locator("#st-panel-storage")).to_be_visible()
    switch = page.locator('button[data-field-key="storage_clean_interval_hours"]')
    expect(switch).to_have_attribute("aria-checked", "false")
    switch.click()
    expect(page.locator('input[data-field-key="storage_clean_interval_hours"]')).to_have_value("24")
    expect(page.locator("#st-panel-storage")).to_contain_text("every")
    eventually(lambda: api.get(PERSONAL).json()["storage_clean_interval_hours"], 24)
    page.get_by_role("tab", name="Database").click()
    expect(page.locator("[data-storage-facts] dd").nth(4)).to_contain_text("every 24 hours")
    expect(page.locator("[data-storage-facts] dd").nth(4)).to_contain_text("next pass in")
