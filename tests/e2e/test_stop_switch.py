"""The STOP switch in the browser (ADR-076): the red switch next to Retention, the question before it goes on, the banner on
every page and live, the refused start of a card, and the personal setting that offers it."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import Board, eventually, executions, slow_flow, start, wait_executions
from tests.helpers import slow_pipeline

STOP = "/api/settings/stop"
PERSONAL = "/api/settings/personal"
BANNER = "[data-stop-banner]"
SWITCH = "#ex-stop [role=switch]"


def _reset(api: httpx.Client) -> None:
    api.put(STOP, json={"active": False}).raise_for_status()  # off is always allowed
    api.put(PERSONAL, json={"show_stop_switch": False}).raise_for_status()


@pytest.fixture(autouse=True)
def _clean(api: httpx.Client) -> Iterator[None]:
    """The servers of the browser tests are shared: STOP and the setting that offers it are off again afterwards."""
    _reset(api)
    yield
    _reset(api)


def _offer(api: httpx.Client) -> None:
    api.put(PERSONAL, json={"show_stop_switch": True}).raise_for_status()


def _running(api: httpx.Client, title: str = "Runner") -> dict[str, object]:
    task = api.post("/api/tasks", json={"title": title}).json()
    start(api, task, slow_flow(api, seconds=60))
    wait_executions(api, task, ["running"])
    return task  # type: ignore[no-any-return]


def _is_danger_red(page: Page, selector: str, property_name: str) -> bool:
    """Whether a computed colour of the element is the --color-danger token of the page (not a literal in the component)."""
    return bool(
        page.evaluate(
            """([selector, property]) => {
              const probe = document.createElement('i');
              probe.style.color = 'var(--color-danger)';
              document.body.append(probe);
              const want = getComputedStyle(probe).color;
              probe.remove();
              return getComputedStyle(document.querySelector(selector))[property] === want;
            }""",
            [selector, property_name],
        )
    )


# ── the switch on the Executions page ─────────────────────────────────


def test_the_switch_is_not_there_until_the_setting_offers_it_and_then_it_is_next_to_retention(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.goto(f"{base_url}/executions")
    expect(page.locator("[data-retention]")).to_be_visible()
    expect(page.locator("#ex-stop")).to_be_hidden()
    _offer(api)  # live: no reload
    holder = page.locator("#ex-stop")
    expect(holder).to_be_visible()
    expect(holder).to_contain_text("STOP")
    switch = page.locator(SWITCH)
    expect(switch).to_have_attribute("aria-checked", "false")
    stop_box, retention_box = holder.bounding_box(), page.locator("[data-retention]").bounding_box()
    assert stop_box and retention_box
    assert (
        stop_box["x"] + stop_box["width"] <= retention_box["x"] + 1
    )  # left of Retention, in the same tools row
    assert (
        abs(
            stop_box["y"]
            + stop_box["height"] / 2
            - retention_box["y"]
            - retention_box["height"] / 2
        )
        < 12
    )
    api.put(PERSONAL, json={"show_stop_switch": False}).raise_for_status()
    expect(holder).to_be_hidden()  # and gone live when it is no longer offered


def test_switching_on_asks_naming_the_running_executions_and_aborts_them_and_off_asks_nothing(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    task = _running(api)
    _offer(api)
    page.goto(f"{base_url}/executions")
    switch = page.locator(SWITCH)
    expect(page.locator(".ex-row .history-chip")).to_have_text("Running")
    dialog = page.locator("#confirm-modal")

    switch.click()
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("STOP aborts 1 running execution and refuses every start")
    expect(dialog.get_by_role("button", name="Switch STOP on")).to_be_visible()
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden()
    expect(switch).to_have_attribute(
        "aria-checked", "false"
    )  # a cancelled question changes nothing
    assert api.get(STOP).json()["active"] is False
    assert executions(api, task)[0]["status"] == "running"

    switch.click()
    dialog.get_by_role("button", name="Switch STOP on").click()
    expect(dialog).to_be_hidden()
    expect(switch).to_have_attribute("aria-checked", "true")
    assert _is_danger_red(page, SWITCH, "color")  # the red of the trash button, not the accent
    row = page.locator(".ex-row").first
    expect(row.locator(".history-chip")).to_have_text("Stopped")
    expect(row.locator("[data-note]")).to_have_text("STOP switch")
    expect(page.locator(BANNER)).to_be_visible()
    assert api.get(STOP).json()["active"] is True

    switch.click()  # off: no question
    expect(dialog).to_be_hidden()
    expect(switch).to_have_attribute("aria-checked", "false")
    expect(page.locator(BANNER)).to_be_hidden()
    assert api.get(STOP).json()["active"] is False


def test_the_question_says_so_when_nothing_runs(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _offer(api)
    page.goto(f"{base_url}/executions")
    page.locator(SWITCH).click()
    expect(page.locator("#confirm-modal")).to_contain_text(
        "No execution is running. STOP refuses every start"
    )
    page.locator("#confirm-modal").get_by_role("button", name="Cancel").click()


# ── the banner ────────────────────────────────────────────────────────


def test_the_banner_is_at_the_top_centre_of_every_page_and_follows_the_switch_live_in_every_tab(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _offer(api)
    board = page
    board.goto(base_url)
    other = page.context.new_page()
    other.goto(f"{base_url}/executions")
    expect(board.locator(BANNER)).to_be_hidden()
    expect(other.locator(BANNER)).to_be_hidden()

    api.put(STOP, json={"active": True}).raise_for_status()  # from outside, like an agent over MCP
    for tab in (board, other):
        banner = tab.locator(BANNER)
        expect(banner).to_be_visible()  # live, no reload
        expect(banner).to_contain_text("Pipeline processing is stopped")
        box, size = banner.bounding_box(), tab.viewport_size
        assert box and size
        assert abs(box["x"] + box["width"] / 2 - size["width"] / 2) < 3  # centre
        assert box["y"] < 40  # top
    other.reload()
    expect(
        other.locator(BANNER)
    ).to_be_visible()  # the state comes with the page load too, not only with an event

    board.locator(BANNER).get_by_role("button", name="Switch STOP off").click()
    for tab in (board, other):
        expect(tab.locator(BANNER)).to_be_hidden()
    assert api.get(STOP).json()["active"] is False
    other.close()


# ── a card cannot be started ──────────────────────────────────────────


def test_a_card_cannot_be_started_while_stop_is_on_and_says_why(
    board: Board, api: httpx.Client
) -> None:
    slow_pipeline(api, stage_name="Gap analysis")
    task = board.create("Item")
    _offer(api)
    api.put(STOP, json={"active": True}).raise_for_status()
    board.open()
    dialog = board.open_card("Item")
    run = dialog.root.locator('[data-card-action="run"]')
    run.click()
    expect(board.page.get_by_text("Pipeline processing is stopped (STOP is on).")).to_be_visible()
    expect(run).to_contain_text("Start processing")  # nothing started
    assert [r for r in api.get("/api/runs").json() if r["task_id"] == task["id"]] == []
    api.put(STOP, json={"active": False}).raise_for_status()
    run.click()
    expect(run).to_contain_text("Stop processing")  # the same click starts it now
    run.click()


# ── the setting that offers it ────────────────────────────────────────


def test_the_personal_page_offers_the_switch_and_will_not_hide_it_while_stop_is_on(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.goto(f"{base_url}/settings/personal")
    setting = page.get_by_label("Show the STOP switch")
    expect(setting).not_to_be_checked()
    setting.check()
    eventually(lambda: api.get(PERSONAL).json()["show_stop_switch"], True)
    api.put(STOP, json={"active": True}).raise_for_status()
    setting.uncheck()
    expect(page.locator("[data-form-error]")).to_contain_text(
        "switch STOP off before you hide the switch"
    )
    expect(setting).to_be_checked()  # the form shows what the server holds
    assert api.get(PERSONAL).json()["show_stop_switch"] is True
