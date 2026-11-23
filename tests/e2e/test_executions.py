"""The global execution list (/executions): what ran across all artifacts, filters in the URL, paging,
live updates, deleting, keyboard and phone layout. Reads only; the one write is a confirmed delete."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from playwright.sync_api import Locator, Page, Route, expect

from tests.e2e.conftest import SECURED_TOKEN
from tests.e2e.helpers import (
    Board,
    echo_pipeline,
    ending_in_failure,
    executions,
    run_started,
    slow_flow,
    start,
    wait_executions,
)

URL_QUERY = re.compile(r"\?(.*)$")

# The executions are started by the browser, by the integration API and by stopping, so these tests run
# against the server that has an access token: the API needs it (/api/v1), the page signs in with it.


@pytest.fixture
def api(secured_url: str) -> Iterator[httpx.Client]:
    """The REST client with the token; the server is emptied first (as the shared ``api`` fixture does)."""
    headers = {"Authorization": f"Bearer {SECURED_TOKEN}"}
    with httpx.Client(base_url=secured_url, headers=headers) as client:
        for task in client.get("/api/tasks").json():
            client.post(f"/api/tasks/{task['id']}/run/stop")
            assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
        for path in ("/api/pipelines", "/api/actions"):
            for graph in client.get(path).json():
                assert client.delete(f"{path}/{graph['id']}").status_code == 204
        yield client


@pytest.fixture(autouse=True)
def _signed_in(page: Page, secured_url: str) -> None:
    page.goto(f"{secured_url}/login")
    page.fill("#token", SECURED_TOKEN)
    page.click("button[type=submit]")
    expect(page.locator(".lane")).to_have_count(3)


def _seed(api: httpx.Client) -> dict[str, Any]:
    """Two artifacts, three pipelines, three origins; newest first the list is B#2, B#1, A#2, A#1."""
    echo, bad = echo_pipeline(api), ending_in_failure(api)
    a = api.post("/api/tasks", json={"title": "Alpha report"}).json()
    b = api.post("/api/tasks", json={"title": "Beta build"}).json()
    run_started(api, a, echo)  # A#1 done, user
    run_started(api, a, bad)  # A#2 failed, user
    api.post(f"/api/v1/artifacts/{b['number']}/run", json={"pipeline_id": echo["id"]})
    wait_executions(api, b, ["done"])  # B#1 done, API
    slow = slow_flow(api, seconds=60)
    start(api, b, slow)
    wait_executions(api, b, ["running", "done"])
    api.post(f"/api/tasks/{b['id']}/run/stop").raise_for_status()
    wait_executions(api, b, ["stopped", "done"])  # B#2 stopped, user
    return {"a": a, "b": b, "echo": echo, "bad": bad, "slow": slow}


def _open(page: Page, secured_url: str, query: str = "", wait: bool = True) -> Locator:
    page.goto(f"{secured_url}/executions{query}")
    rows = page.locator(".ex-row")
    if wait:
        expect(page.locator("[data-list]")).to_have_attribute("aria-busy", "false")
    return rows


def _titles(rows: Locator) -> list[str]:
    """Each row as '#artifact/#execution': the artifact number and the execution number."""
    return [
        f"{r.locator('[data-artifact]').inner_text().split(' ')[0]}/{r.locator('[data-open]').inner_text()}"
        for r in rows.all()
    ]


def _expect_titles(rows: Locator, expected: list[str]) -> None:
    """The rows become `expected` (polls: a filter is applied after a pause and the list reloads)."""
    Board._eventually(lambda: _titles(rows), expected, 5)


def _query(page: Page) -> str:
    match = URL_QUERY.search(page.url)
    return match.group(1) if match else ""


# ── the list ──────────────────────────────────────────────────────────


def test_every_execution_of_every_artifact_newest_first(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    made = _seed(api)
    a, b = made["a"]["number"], made["b"]["number"]
    rows = _open(page, secured_url)
    expect(rows).to_have_count(4)
    assert _titles(rows) == [f"#{b}/#2", f"#{b}/#1", f"#{a}/#2", f"#{a}/#1"]
    expect(rows.locator(".history-chip")).to_have_text(["Stopped", "Done", "Failed", "Done"])
    expect(rows.locator("[data-origin]")).to_have_text(["User", "API", "User", "User"])
    expect(rows.locator("[data-origin]").nth(1)).to_have_attribute("data-origin", "api")
    expect(rows.locator("[data-pipeline-link]").first).to_have_text("Flow")
    expect(page.locator("[data-count]")).to_have_text("4 executions")
    # a table with a caption and column headers
    expect(page.locator("table.ex-table caption")).to_have_text(
        "Executions of all artifacts, newest first"
    )
    expect(page.locator("table.ex-table th[scope=col]")).to_have_count(
        11
    )  # a select column and ten more
    expect(rows.nth(2).locator("[data-note]")).to_contain_text("failed")
    time = rows.first.locator("time")
    assert (time.get_attribute("datetime") or "").endswith("Z")
    expect(page.locator(".sidebar a[aria-current=page]")).to_have_text("Executions")


def test_the_artifact_link_opens_it_on_the_board(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    made = _seed(api)
    rows = _open(page, secured_url)
    link = rows.first.locator("[data-artifact]")
    expect(link).to_have_attribute("href", f"/?artifact={made['b']['number']}")
    link.click()
    expect(page.locator("#create-task-modal")).to_be_visible()
    expect(page.locator("#create-task-modal")).to_contain_text("Beta build")


def test_a_row_opens_its_flow_by_mouse_and_by_keyboard(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    made = _seed(api)
    first = executions(api, made["a"])[-1]  # A#1
    rows = _open(page, secured_url)
    link = rows.nth(3).locator("[data-open]")
    expect(link).to_have_attribute(
        "href", f"/artifacts/{made['a']['number']}/executions/{first['id']}"
    )
    rows.nth(3).locator(".ex-row__time").click()  # anywhere on the row
    expect(page).to_have_url(re.compile(rf"/artifacts/{made['a']['number']}/executions/"))
    expect(page.locator(".sidebar a[aria-current=page]")).to_have_text("Executions")
    page.go_back()
    rows = _open(page, secured_url)
    rows.nth(2).locator("[data-open]").focus()
    page.keyboard.press("Enter")
    expect(page.locator("[data-head-title]")).to_contain_text("Execution #2")


def test_the_pipeline_links_to_its_editor_and_a_deleted_one_is_plain_text(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    made = _seed(api)
    api.delete(f"/api/pipelines/{made['bad']['id']}").raise_for_status()
    rows = _open(page, secured_url)
    failed = rows.filter(
        has=page.locator("[data-status=failed], .history-chip[data-status=failed]")
    )
    expect(failed.locator("a[data-pipeline-link]")).to_be_hidden()
    expect(failed.locator("[data-pipeline-text]")).to_have_text("Failing build")
    expect(failed.locator("[data-pipeline-gone]")).to_be_visible()
    done = rows.filter(has=page.get_by_text("Echo flow")).first
    link = done.locator("a[data-pipeline-link]")
    expect(link).to_have_attribute("href", f"/pipelines/{made['echo']['id']}")
    link.click()
    expect(page).to_have_url(re.compile(r"/pipelines/"))
    expect(page.locator(".ge-node").first).to_be_visible()


# ── summary ───────────────────────────────────────────────────────────


def test_the_counters_and_a_click_on_one_filters(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    _seed(api)
    rows = _open(page, secured_url)
    counts = page.locator("[data-summary-value]")
    expect(counts).to_have_text(["0", "1", "2", "4"])  # running, failed 24 h, done 24 h, total
    failed = page.locator("[data-summary=failed_24h]")
    failed.click()
    expect(rows).to_have_count(1)
    expect(failed).to_have_attribute("aria-pressed", "true")
    assert set(_query(page).split("&")) == {"status=failed", "range=24h"}
    expect(page.locator("input[name=status][value=failed]")).to_be_checked()
    expect(page.locator("[data-count]")).to_have_text("1 execution")
    expect(counts).to_have_text(["0", "1", "2", "4"])  # the counters ignore the filters
    failed.click()  # pressing it again clears it
    expect(rows).to_have_count(4)
    assert _query(page) == ""
    page.locator("[data-summary=done_24h]").click()
    expect(rows).to_have_count(2)
    page.locator("[data-summary=total]").click()
    expect(rows).to_have_count(4)


# ── filters ───────────────────────────────────────────────────────────


def test_each_filter_narrows_the_list_and_lives_in_the_url(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    made = _seed(api)
    a, b = made["a"]["number"], made["b"]["number"]
    rows = _open(page, secured_url)
    count = page.locator("[data-count]")

    page.locator(".ex-toggle", has_text="Failed").click()
    expect(rows).to_have_count(1)
    assert _query(page) == "status=failed"
    page.locator(".ex-toggle", has_text="Done").click()
    expect(rows).to_have_count(3)
    assert _query(page) == "status=done%2Cfailed"
    expect(count).to_have_text("3 executions")
    page.get_by_role("button", name="Reset filters").first.click()
    expect(rows).to_have_count(4)
    assert _query(page) == ""
    expect(page.locator("input[name=status]:checked")).to_have_count(0)

    page.locator(".ex-toggle", has_text="API").click()
    expect(rows).to_have_count(1)
    assert _titles(rows) == [f"#{b}/#1"]
    page.locator(".ex-toggle", has_text="API").click()
    expect(rows).to_have_count(4)

    page.fill("#ex-pipeline", "failing")  # debounced
    expect(rows).to_have_count(1)
    assert _query(page) == "pipeline=failing"
    page.fill("#ex-pipeline", "")
    expect(rows).to_have_count(4)

    page.fill("#ex-q", "beta")  # artifact title
    expect(rows).to_have_count(2)
    page.fill("#ex-q", f"#{a}")  # artifact number
    _expect_titles(rows, [f"#{a}/#2", f"#{a}/#1"])
    page.fill("#ex-q", "failed")  # the note
    expect(rows).to_have_count(1)
    page.fill("#ex-q", "")
    expect(rows).to_have_count(4)

    page.locator(".ex-toggle", has_text="Last hour").click()
    expect(rows).to_have_count(4)
    assert _query(page) == "range=1h"
    page.locator(".ex-toggle", has_text="All").click()
    assert _query(page) == ""

    # combined
    page.locator(".ex-toggle", has_text="Done").click()
    page.locator(".ex-toggle", has_text="User").click()
    page.fill("#ex-q", "alpha")
    expect(page).to_have_url(re.compile(r"q=alpha"))
    expect(rows).to_have_count(1)
    assert set(_query(page).split("&")) == {"status=done", "started_by=user", "q=alpha"}
    expect(page.locator("[data-filters-active]")).to_have_text("3 active")


def test_a_reload_and_the_back_button_restore_the_filters(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    _seed(api)
    rows = _open(page, secured_url, "?status=failed,done&started_by=user&q=alpha&range=7d")
    expect(rows).to_have_count(2)
    expect(page.locator("input[name=status][value=done]")).to_be_checked()
    expect(page.locator("input[name=status][value=failed]")).to_be_checked()
    expect(page.locator("input[name=started_by][value=user]")).to_be_checked()
    expect(page.locator("#ex-q")).to_have_value("alpha")
    expect(page.locator("input[name=range][value='7d']")).to_be_checked()
    page.reload()
    expect(rows).to_have_count(2)
    expect(page.locator("#ex-q")).to_have_value("alpha")

    page.locator(".ex-toggle", has_text="Failed").click()  # a new history entry
    expect(rows).to_have_count(1)
    page.go_back()
    expect(rows).to_have_count(2)
    expect(page.locator("input[name=status][value=failed]")).to_be_checked()
    page.go_back()  # to the page that was open before: the list without a query (or none)
    page.go_forward()
    expect(rows).to_have_count(2)


def test_a_range_given_by_since_and_until_is_kept_and_can_be_cleared(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    _seed(api)
    rows = _open(page, secured_url, "?since=2020-01-01T00:00:00Z&until=2020-01-02T00:00:00Z")
    expect(rows).to_have_count(0)
    expect(page.locator("[data-custom]")).to_contain_text("Custom range")
    expect(page.locator("[data-empty-match]")).to_be_visible()
    page.locator("[data-custom-clear]").click()
    expect(rows).to_have_count(4)
    assert _query(page) == ""
    rows = _open(page, secured_url, "?since=2020-01-01T00:00:00Z")
    expect(rows).to_have_count(4)  # everything started after 2020
    page.locator(".ex-toggle", has_text="24 hours").click()  # a preset replaces the custom range
    assert _query(page) == "range=24h"
    expect(page.locator("[data-custom]")).to_be_hidden()


def test_a_bad_value_in_the_url_is_ignored_not_fatal(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    _seed(api)
    rows = _open(page, secured_url, "?status=bogus&started_by=robot&range=century")
    expect(rows).to_have_count(4)
    expect(page.locator("[data-alert]")).to_be_hidden()


# ── paging ────────────────────────────────────────────────────────────


def test_load_more_appends_the_next_page_and_never_scrolls_by_itself(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    _seed(api)
    rows = _open(page, secured_url, "?page_size=3")
    expect(rows).to_have_count(3)
    more = page.locator("[data-more]")
    expect(more).to_have_text("Load more (3 of 4 shown)")
    expect(page.locator("[data-count]")).to_have_text("4 executions")
    first = rows.first.locator("[data-open]").inner_text()
    more.click()
    expect(rows).to_have_count(4)
    expect(more).to_be_hidden()
    assert rows.first.locator("[data-open]").inner_text() == first
    expect(rows.nth(3).locator("[data-open]")).to_be_focused()
    assert "page_size=3" in _query(page) or _query(page) == ""
    # a filter change starts again from the first page
    page.locator(".ex-toggle", has_text="Done").click()
    expect(rows).to_have_count(2)
    expect(more).to_be_hidden()


# ── deleting ──────────────────────────────────────────────────────────


def test_delete_needs_a_confirmation_and_a_running_row_cannot_be_deleted(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    made = _seed(api)
    start(api, made["a"], made["slow"])
    wait_executions(api, made["a"], ["running", "failed", "done"])
    rows = _open(page, secured_url)
    running = rows.first
    expect(running.locator(".history-chip")).to_have_text("Running")
    delete = running.locator("[data-delete]")
    expect(delete).to_have_attribute("aria-disabled", "true")
    expect(delete).to_have_attribute("title", "Stop it first")
    delete.click(force=True)
    expect(page.locator("#confirm-modal")).to_be_hidden()

    target = rows.nth(2)  # B#1
    target.locator("[data-delete]").click()
    dialog = page.locator("#confirm-modal")
    expect(dialog).to_be_visible()
    number = made["b"]["number"]
    expect(dialog).to_contain_text(f"Delete execution #1 of #{number}?")
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden()
    expect(rows).to_have_count(5)

    target.locator("[data-delete]").click()
    dialog.get_by_role("button", name="Delete").click()
    expect(rows).to_have_count(4)
    expect(page.locator("[data-live]")).to_have_text(f"Execution #1 of #{number} deleted")
    expect(page.locator("[data-count]")).to_have_text("4 executions")
    assert [e["number"] for e in executions(api, made["b"])] == [2]
    expect(page.locator("[data-summary=total] [data-summary-value]")).to_have_text("4")
    assert not dialog.is_visible()
    expect(rows.nth(2).locator("[data-open]")).to_be_focused()  # focus moved on to the next row


# ── live ──────────────────────────────────────────────────────────────


def test_a_new_execution_raises_a_hint_and_a_shown_one_changes_in_place(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    made = _seed(api)
    rows = _open(page, secured_url)
    expect(rows).to_have_count(4)
    before = rows.first.locator("[data-open]").inner_text()
    api.post(
        f"/api/v1/artifacts/{made['a']['number']}/run", json={"pipeline_id": made["slow"]["id"]}
    ).raise_for_status()
    hint = page.locator("[data-new]")
    expect(hint).to_have_text("1 new execution")
    expect(rows).to_have_count(4)  # nothing shifted under the cursor
    assert rows.first.locator("[data-open]").inner_text() == before
    expect(page.locator("[data-summary=running] [data-summary-value]")).to_have_text("1")
    hint.click()
    expect(rows).to_have_count(5)
    expect(hint).to_be_hidden()
    running = rows.first
    expect(running.locator(".history-chip")).to_have_text("Running")
    expect(running.locator("[data-origin]")).to_have_text("API")
    expect(running.locator("[data-duration]")).not_to_have_text("")
    api.post(f"/api/tasks/{made['a']['id']}/run/stop").raise_for_status()
    expect(running.locator(".history-chip")).to_have_text("Stopped")  # updated in place
    expect(running.locator("[data-delete]")).to_have_attribute("aria-disabled", "false")
    expect(page.locator("[data-summary=running] [data-summary-value]")).to_have_text("0")
    expect(hint).to_be_hidden()
    expect(rows).to_have_count(5)


def test_a_new_execution_appears_at_once_when_nothing_is_shown(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    task = api.post("/api/tasks", json={"title": "First"}).json()
    rows = _open(page, secured_url)
    expect(page.locator("[data-empty-none]")).to_be_visible()
    run_started(api, task, echo_pipeline(api))
    expect(rows).to_have_count(1)
    expect(page.locator("[data-empty-none]")).to_be_hidden()


def test_an_execution_deleted_elsewhere_leaves_the_list(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    made = _seed(api)
    rows = _open(page, secured_url)
    first = executions(api, made["a"])[-1]
    api.delete(f"/api/tasks/{made['a']['id']}/executions/{first['id']}").raise_for_status()
    expect(rows).to_have_count(3)
    expect(page.locator("[data-count]")).to_have_text("3 executions")


def test_a_hint_is_not_raised_for_what_the_filters_exclude(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    made = _seed(api)
    rows = _open(page, secured_url, "?status=failed")
    expect(rows).to_have_count(1)
    api.post(
        f"/api/v1/artifacts/{made['a']['number']}/run", json={"pipeline_id": made["echo"]["id"]}
    ).raise_for_status()
    wait_executions(api, made["a"], ["done", "failed", "done"])
    expect(page.locator("[data-summary=done_24h] [data-summary-value]")).to_have_text("3")
    expect(page.locator("[data-new]")).to_be_hidden()
    expect(rows).to_have_count(1)


def test_a_failed_request_keeps_what_is_shown_and_retry_works(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    _seed(api)
    rows = _open(page, secured_url)
    expect(rows).to_have_count(4)

    def refuse(route: Route) -> None:
        route.fulfill(status=500, json={"detail": "boom"})

    page.route("**/api/executions?*", refuse)
    page.locator(".ex-toggle", has_text="Done").click()
    alert = page.locator("[data-alert]")
    expect(alert).to_be_visible()
    expect(rows).to_have_count(4)  # the old content stays
    page.unroute("**/api/executions?*")
    alert.get_by_role("button", name="Retry").click()
    expect(rows).to_have_count(2)
    expect(alert).to_be_hidden()


# ── empty states ──────────────────────────────────────────────────────


def test_empty_states_differ_for_nothing_at_all_and_no_match(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    rows = _open(page, secured_url)
    expect(page.locator("[data-empty-none]")).to_be_visible()
    expect(page.locator("[data-empty-none]")).to_contain_text("No executions yet")
    expect(page.locator("[data-empty-match]")).to_be_hidden()
    expect(page.locator("[data-count]")).to_have_text("0 executions")
    expect(page.locator("table.ex-table")).to_be_hidden()
    task = api.post("/api/tasks", json={"title": "One"}).json()
    run_started(api, task, echo_pipeline(api))
    rows = _open(page, secured_url, "?q=nothing-like-this")
    expect(rows).to_have_count(0)
    match = page.locator("[data-empty-match]")
    expect(match).to_be_visible()
    expect(match).to_contain_text("No execution matches these filters")
    expect(page.locator("[data-empty-none]")).to_be_hidden()
    match.get_by_role("button", name="Reset filters").click()
    expect(rows).to_have_count(1)
    expect(match).to_be_hidden()
    assert _query(page) == ""


# ── keyboard, accessibility, phone ────────────────────────────────────


def test_the_filters_and_rows_work_from_the_keyboard(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    _seed(api)
    rows = _open(page, secured_url)
    page.locator("input[name=status][value=failed]").focus()
    page.keyboard.press("Space")
    expect(rows).to_have_count(1)
    assert _query(page) == "status=failed"
    expect(page.locator("input[name=status][value=failed]")).to_be_focused()
    page.keyboard.press("Space")
    expect(rows).to_have_count(4)
    # a summary counter is a button
    page.locator("[data-summary=running]").focus()
    page.keyboard.press("Enter")
    expect(page.locator("[data-empty-match]")).to_be_visible()
    page.get_by_role("button", name="Reset filters").first.focus()
    page.keyboard.press("Enter")
    expect(rows).to_have_count(4)
    # every control of a row is reachable by Tab, in reading order, no trap
    seen: list[str] = []
    rows.first.locator("[data-artifact]").focus()
    for _ in range(4):
        seen.append(
            page.evaluate(
                "document.activeElement.getAttribute('data-open') !== null ? 'open' : (document.activeElement.hasAttribute('data-artifact') ? 'artifact' : (document.activeElement.hasAttribute('data-pipeline-link') ? 'pipeline' : (document.activeElement.hasAttribute('data-delete') ? 'delete' : 'other')))"
            )
        )
        page.keyboard.press("Tab")
    assert seen[:2] == ["artifact", "open"]
    assert "delete" in seen
    labels = page.locator("input[name=pipeline], input[name=q]")
    for field in labels.all():
        expect(field).to_have_accessible_name(re.compile(r"Pipeline|Search"))
    expect(page.locator("[data-count]")).to_have_attribute("aria-live", "polite")
    expect(page.locator("form[role=search]")).to_have_attribute("aria-label", "Filter executions")


def test_the_page_only_reads_and_deletes(page: Page, secured_url: str, api: httpx.Client) -> None:
    _seed(api)
    methods: list[str] = []
    page.on("request", lambda r: methods.append(r.method) if "/api/" in r.url else None)
    rows = _open(page, secured_url)
    page.locator(".ex-toggle", has_text="Done").click()
    page.fill("#ex-q", "alpha")
    expect(rows).to_have_count(1)
    page.locator("[data-summary=total]").click()
    expect(rows).to_have_count(4)
    assert set(methods) == {"GET"}


def test_a_phone_shows_cards_and_the_filters_in_a_disclosure(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    _seed(api)
    page.set_viewport_size({"width": 390, "height": 844})
    rows = _open(page, secured_url)
    expect(rows).to_have_count(4)
    disclosure = page.locator("[data-filters-disclosure]")
    assert page.evaluate("document.querySelector('[data-filters-disclosure]').open") is False
    expect(page.locator("#ex-q")).to_be_hidden()
    page.locator(".ex-filters__summary").click()
    expect(page.locator("#ex-q")).to_be_visible()
    page.locator(".ex-toggle", has_text="Failed").click()
    expect(rows).to_have_count(1)
    expect(page.locator("[data-filters-active]")).to_have_text("1 active")
    assert disclosure.evaluate("el => el.open") is True
    page.locator("[data-reset]").first.click()
    expect(rows).to_have_count(4)
    assert rows.first.evaluate("el => getComputedStyle(el).display") == "grid"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    assert page.evaluate("document.querySelector('.content').scrollWidth <= window.innerWidth + 1")
    box = rows.first.locator("[data-delete]").bounding_box()
    assert box and box["x"] + box["width"] <= 390
    rows.first.locator("[data-open]").click()
    expect(page).to_have_url(re.compile(r"/artifacts/\d+/executions/"))


def test_the_page_follows_the_theme(page: Page, secured_url: str, api: httpx.Client) -> None:
    _seed(api)
    page.emulate_media(color_scheme="dark")
    rows = _open(page, secured_url)
    expect(rows).to_have_count(4)
    chip = rows.first.locator(".history-chip")
    assert chip.evaluate("el => getComputedStyle(el).backgroundColor") != "rgba(0, 0, 0, 0)"


def test_the_board_opens_the_artifact_of_the_url(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    task = api.post("/api/tasks", json={"title": "Linked"}).json()
    api.post("/api/tasks", json={"title": "Other"})
    page.goto(f"{secured_url}/?artifact={task['number']}")
    expect(page.locator("#create-task-modal")).to_be_visible()
    expect(page.locator("#create-task-modal")).to_contain_text("Linked")
    page.goto(f"{secured_url}/?artifact=9999")
    expect(page.locator(".board .task-card")).to_have_count(2)
    expect(page.locator("#create-task-modal")).to_be_hidden()


# ── several at once ───────────────────────────────────────────────────


def test_rows_are_selected_one_by_one_or_all_and_deleted_together(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    made = _seed(api)
    start(api, made["a"], made["slow"])
    wait_executions(api, made["a"], ["running", "failed", "done"])
    rows = _open(page, secured_url)
    bar = page.locator("[data-bulk]")
    expect(bar).to_be_hidden()  # nothing selected, no bar
    expect(
        rows.first.locator("[data-select]")
    ).to_be_disabled()  # the running one cannot be deleted

    rows.nth(1).locator("[data-select]").check()
    rows.nth(2).locator("[data-select]").check()
    expect(bar).to_be_visible()
    expect(page.locator("[data-bulk-count]")).to_have_text("2 selected")
    expect(rows.nth(1)).to_have_class(re.compile(r"is-selected"))
    expect(page.locator("[data-select-all]")).to_have_js_property("indeterminate", True)
    expect(page.locator("[data-bulk-all]")).to_be_hidden()  # not everything shown is selected yet
    # a click on a checkbox does not open the row
    assert "/executions" in page.url and "/artifacts/" not in page.url

    page.locator("[data-select-all]").check()  # everything shown that can go
    expect(page.locator("[data-bulk-count]")).to_have_text(
        "4 selected"
    )  # the running row is not in it
    expect(rows.first.locator("[data-select]")).not_to_be_checked()
    page.locator("[data-bulk-clear]").click()
    expect(bar).to_be_hidden()

    rows.nth(1).locator("[data-select]").check()
    rows.nth(2).locator("[data-select]").check()
    page.locator("[data-bulk-delete]").click()
    dialog = page.locator("#confirm-modal")
    expect(dialog).to_contain_text("Delete the 2 selected executions?")
    dialog.get_by_role("button", name="Cancel").click()
    expect(rows).to_have_count(5)

    page.locator("[data-bulk-delete]").click()
    dialog.get_by_role("button", name="Delete").click()
    expect(rows).to_have_count(3)
    expect(page.locator("[data-live]")).to_have_text("2 executions deleted")
    expect(bar).to_be_hidden()
    expect(page.locator("[data-count]")).to_have_text("3 executions")
    remaining = sum(len(executions(api, task)) for task in (made["a"], made["b"]))
    assert remaining == 3


def test_select_all_deletes_every_finished_execution_and_a_running_one_survives(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    made = _seed(api)
    start(api, made["a"], made["slow"])
    wait_executions(api, made["a"], ["running", "failed", "done"])
    rows = _open(page, secured_url, "?q=Alpha")  # only artifact A's executions
    expect(rows).to_have_count(3)
    page.locator("[data-select-all]").check()
    expect(page.locator("[data-bulk-count]")).to_have_text("2 selected")
    expect(
        page.locator("[data-bulk-all]")
    ).to_be_hidden()  # all matches are shown: nothing more to reach
    page.locator("[data-bulk-delete]").click()
    page.locator("#confirm-modal").get_by_role("button", name="Delete").click()
    expect(rows).to_have_count(1)  # the running execution stays
    expect(rows.first.locator(".history-chip")).to_have_text("Running")


# ── retention rules ───────────────────────────────────────────────────


def test_the_retention_dialog_builds_a_rule_says_what_it_deletes_and_saving_deletes_it(
    page: Page, secured_url: str, api: httpx.Client
) -> None:
    made = _seed(api)  # A#1 done, A#2 failed, B#1 done, B#2 stopped
    rows = _open(page, secured_url)
    expect(rows).to_have_count(4)
    page.get_by_role("button", name="Retention").click()
    dialog = page.locator("#retention-modal")
    expect(dialog).to_be_visible()
    expect(dialog.locator("[data-rule-text]")).to_have_text(
        "No conditions: nothing is deleted automatically."
    )

    dialog.get_by_role("button", name="Add condition").click()
    expect(dialog.locator(".rb-row")).to_have_count(1)
    expect(dialog.locator("[data-submit]")).to_be_disabled()  # the value is still missing
    dialog.locator(".rb-chip", has_text="Failed").click()
    expect(dialog.locator("[data-rule-text]")).to_have_text(
        "Deletes finished executions where Status is Failed."
    )
    expect(dialog.locator("[data-preview]")).to_have_text(
        "1 execution matches now: saving deletes it."
    )
    expect(dialog.locator("[data-submit-label]")).to_have_text("Save and delete 1")

    dialog.get_by_role("button", name="Add condition").click()  # a second one: Age older than 1 day
    second = dialog.locator(".rb-row").nth(1)
    second.get_by_label("Field").select_option("age")
    expect(second.get_by_label("Operator")).to_have_value("older_than")
    expect(dialog.locator(".rb-group[data-mode=all]")).to_have_count(1)
    expect(
        dialog.locator("[data-preview]")
    ).to_be_hidden()  # failed AND older than a day: nothing yet
    dialog.get_by_label("All or any of the conditions").first.select_option(
        "any"
    )  # failed OR older: both
    expect(dialog.locator("[data-preview]")).to_have_text(re.compile(r"^\d+ executions? match"))
    expect(dialog.locator("[data-submit]")).to_be_enabled()
    dialog.get_by_role("button", name="Add group").click()
    expect(dialog.locator(".rb-group")).to_have_count(2)  # an inner group
    dialog.locator(".rb-group .rb-group [aria-label='Remove this group']").click()
    expect(dialog.locator(".rb-group")).to_have_count(1)
    second.get_by_role("button", name="Remove this condition").click()  # back to: Status is Failed
    expect(dialog.locator("[data-submit-label]")).to_have_text("Save and delete 1")

    dialog.locator("[data-submit]").click()
    expect(dialog).to_be_hidden()
    expect(rows).to_have_count(3)  # the failed one is gone
    expect(page.locator("[data-live]")).to_have_text("1 execution deleted by the rules")
    assert sorted(e["status"] for e in executions(api, made["a"])) == ["done"]

    page.get_by_role("button", name="Retention").click()  # the rule is stored
    expect(dialog.locator(".rb-chip:has(input:checked)")).to_have_text(["Failed"])
