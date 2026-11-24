"""Guards in the browser (ADR-060): the Guard entries of the editor open the Guard window (the pipeline's "+" menu, the
"+" of a stage, the menu of an action), a saved guard is a shield chip and never a node, and a run proves what the
guards do: a round guard with an escalation table fires at round 5 and 8 and pauses the run, a stall guard stops a
sleeping Code node; the History shows each firing with its facts. (Replaces the tests of the Guard placeholders.)"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import _serve
from tests.e2e.helpers import Board, add_action, code_definition
from tests.helpers import build_pipeline, connect, graph_url, link, node


def _pipeline(client: httpx.Client, with_action: bool = False) -> dict[str, Any]:
    pipeline: dict[str, Any] = client.post("/api/pipelines", json={"name": "Watched"}).json()
    stage = node(client, pipeline, "stage", name="Gap Analysis", x=240, y=40)
    if with_action:
        action = node(client, pipeline, "action", stage_id=stage["id"], x=60, y=48, name="Draft")
        connect(client, pipeline, stage, "start", action, "in")
    return pipeline


def _counts(api: httpx.Client, pipeline: dict[str, Any]) -> tuple[int, int]:
    graph = api.get(graph_url(pipeline)).json()
    return len(graph["nodes"]), len(graph["edges"])


def _open(page: Page, base_url: str, path: str) -> None:
    page.goto(f"{base_url}{path}")
    expect(page.locator(".ge-node").first).to_be_visible()


def _window(page: Page) -> Any:
    window = page.locator("#guard-modal")
    expect(window).to_be_visible()
    return window


# ── the entries open the Guard window ─────────────────────────────────


def test_the_add_menu_offers_guard_after_pipeline_and_opens_a_guard_of_the_pipeline(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    before = _counts(api, pipeline)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    page.click("[data-add-menu]")
    page.locator('.ge-add__group[data-group="Structure"]').click()
    items = page.locator(".ge-add__item")
    assert [i.split("\n")[0] for i in items.all_inner_texts()][:3] == ["Stage", "Pipeline", "Guard"]
    guard = page.locator("[data-placeholder=guard]")
    expect(guard.locator(".tag")).to_have_count(0)  # no longer "Soon"
    guard.click()
    window = _window(page)
    expect(window.locator(".modal__title")).to_have_text("New guard")
    expect(window).to_contain_text("Watches the pipeline Watched while it runs.")
    page.keyboard.press("Escape")
    expect(window).to_be_hidden()
    assert _counts(api, pipeline) == before, "a guard is never a node"


def test_a_guard_is_found_by_its_name_and_enter_opens_the_window(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    page.click("[data-add-menu]")
    page.fill(".ge-add__search", "guard")
    expect(page.locator(".ge-add__item")).to_have_count(1)
    page.keyboard.press("Enter")
    expect(_window(page).locator(".modal__title")).to_have_text("New guard")


def test_a_guard_of_a_stage_is_made_in_the_window_shown_as_a_chip_reopened_and_deleted(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    before = _counts(api, pipeline)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    plus = page.locator("[data-stage-add]")
    plus.focus()
    page.keyboard.press("Enter")  # the keyboard reaches the menu as before
    menu = page.get_by_role("menu", name="Add to stage")
    page.keyboard.press("ArrowDown")
    expect(menu.get_by_role("menuitem", name="Guard")).to_be_focused()
    expect(menu.get_by_role("menuitem", name="Guard").locator(".tag")).to_have_count(0)
    page.keyboard.press("Enter")
    window = _window(page)
    expect(window).to_contain_text("Watches the stage Gap Analysis while it runs.")
    window.get_by_label("Name", exact=True).fill("Round guard")
    window.get_by_role("button", name="Add condition").click()  # Rounds of the scope, is at least
    window.locator(".rb-row input[type=number]").fill("5")
    window.get_by_role("button", name="Add step").click()
    window.get_by_role("button", name="Add step").click()
    window.get_by_label("How many").nth(1).fill("3")
    consequence = window.get_by_label("Consequence")
    expect(consequence.locator("option[value=notify]")).to_be_disabled()
    expect(consequence.locator("option[value=handover]")).to_be_disabled()
    expect(window).to_contain_text("needs notifications")
    consequence.select_option("pause")
    window.get_by_role("button", name="Save").click()
    expect(window).to_be_hidden()

    chip = page.locator(".ge-stage__header .ge-guards__chip")
    expect(chip).to_have_text("Round guard")
    expect(chip).to_have_accessible_name("Guard Round guard")
    [saved] = api.get("/api/guards", params={"pipeline_id": pipeline["id"]}).json()
    assert (saved["scope_type"], saved["consequence"]) == ("stage", "pause")
    assert saved["when"]["items"][0] == {
        "type": "condition",
        "field": "runs",
        "op": "at_least",
        "value": 5,
    }
    assert saved["escalation"] == [
        {"from_firing": 1, "every_runs": 5},
        {"from_firing": 2, "every_runs": 3},
    ]
    assert _counts(api, pipeline) == before, "a guard is never a node of the canvas"

    page.reload()
    chip = page.locator(".ge-stage__header .ge-guards__chip")
    chip.click()
    window = _window(page)
    expect(window.locator(".modal__title")).to_have_text("Guard Round guard")
    window.locator("[data-delete]").click()
    page.locator("#confirm-modal [data-confirm], #confirm-modal [data-submit]").first.click()
    expect(window).to_be_hidden()
    expect(page.locator(".ge-guards__chip")).to_have_count(0)
    assert api.get("/api/guards", params={"pipeline_id": pipeline["id"]}).json() == []


def test_the_menu_and_the_settings_of_an_action_offer_a_guard_of_that_action(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api, with_action=True)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    page.locator(".ge-node--action .ge-node__name").click(button="right")
    menu = page.get_by_role("menu")
    labels = [e.split("\n")[0] for e in menu.get_by_role("menuitem").all_inner_texts()]
    assert labels.index("Guard") == len(labels) - 2 and labels[-1] == "Delete", labels
    menu.get_by_role("menuitem", name="Guard").click()
    window = _window(page)
    expect(window).to_contain_text("Watches the action Draft while it runs.")
    page.keyboard.press("Escape")
    page.locator(".ge-node--action .ge-node__name").dblclick()
    section = page.locator("[data-guard-section]")
    expect(section).to_contain_text("No guard watches this action.")
    expect(section.get_by_role("button", name="Add guard")).to_be_visible()


def test_an_action_definition_offers_no_guard(page: Page, base_url: str, api: httpx.Client) -> None:
    definition = api.post("/api/actions", json={"name": "Check"}).json()
    _open(page, base_url, f"/actions/{definition['slug']}")
    page.click("[data-add-menu]")
    page.fill(".ge-add__search", "guard")
    expect(page.locator("[data-placeholder=guard]")).to_have_count(0)


def test_adding_an_action_through_the_stage_menu_still_works(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    add_action(page)
    expect(page.locator(".ge-node--action")).to_have_count(1)


# ── what guards do in a run (a server with a short minimum interval) ──


@pytest.fixture(scope="module")
def guard_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    yield from _serve(
        Path(tmp_path_factory.mktemp("guards")),
        guard_min_interval_seconds="0.5",
        heartbeat_min_spacing_seconds="0.5",
    )


@pytest.fixture
def guard_api(guard_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=guard_url, timeout=30) as client:
        for task in client.get("/api/tasks").json():
            client.post(f"/api/tasks/{task['id']}/run/stop")
            client.delete(f"/api/tasks/{task['id']}")
        for path in ("/api/pipelines", "/api/actions"):
            for graph in client.get(path).json():
                client.delete(f"{path}/{graph['id']}")
        yield client


def _run(client: httpx.Client, pipeline: dict[str, Any], title: str) -> dict[str, Any]:
    task: dict[str, Any] = client.post(
        "/api/tasks", json={"title": title, "status": "backlog"}
    ).json()
    client.post(
        f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]}
    ).raise_for_status()
    return task


def _status(client: httpx.Client, task: dict[str, Any], status: str) -> dict[str, Any]:
    def run() -> dict[str, Any]:
        return next(r for r in client.get("/api/runs").json() if r["task_id"] == task["id"])

    Board._eventually(lambda: run()["status"], status, 30)
    return run()


def _guard_rows(page: Page, guard_url: str, client: httpx.Client, title: str) -> Any:
    board = Board(page, guard_url, client)
    dialog = board.open().open_card(title).open_history()
    return dialog.history.locator('.history-event[data-kind="guard"]')


def test_a_round_guard_fires_at_round_5_and_8_and_pauses_the_run_and_the_history_says_why(
    page: Page, guard_url: str, guard_api: httpx.Client
) -> None:
    pipeline = build_pipeline(guard_api, stages=1, name="Loop")
    stage, work = pipeline["stages"][0]
    check = node(guard_api, pipeline, "action", stage_id=stage["id"], x=240, y=48, name="Check")
    connect(guard_api, pipeline, work, "pass", check, "in")
    connect(
        guard_api, pipeline, check, "pass", work, "in"
    )  # a loop back to the stage's entry action
    judge = code_definition(
        guard_api,
        "Judge",
        'import json, sys\nsys.exit(0 if json.load(open("context.json"))["vars"]["guard_firing"] < 2 else 1)',
    )
    guard_api.post(
        "/api/guards",
        json={
            "pipeline_id": pipeline["id"],
            "name": "Health guard",
            "scope_type": "stage",
            "scope_id": stage["id"],
            "trigger": {"type": "event", "events": ["enter"]},
            "when": {
                "type": "group",
                "mode": "all",
                "items": [{"type": "condition", "field": "runs", "op": "at_least", "value": 1}],
            },
            "consequence": "run_action",
            "fallback": "pause",
            "definition_id": judge["id"],
            "escalation": [
                {"from_firing": 1, "every_runs": 5},
                {"from_firing": 2, "every_runs": 3},
            ],
        },
    ).raise_for_status()
    task = _run(guard_api, pipeline, "Looping")
    run = _status(guard_api, task, "stopped")
    assert run["note"].startswith("Paused by guard Health guard fired at Stage 1: round 8")

    rows = _guard_rows(page, guard_url, guard_api, "Looping")
    expect(rows).to_have_count(2)
    expect(rows.nth(0)).to_contain_text("Health guard")
    expect(rows.nth(0)).to_contain_text("fired at Stage 1: paused the run (round 8")
    expect(rows.nth(1)).to_contain_text("fired at Stage 1: the run went on (round 5")
    expect(rows.nth(0).locator(".history-marker")).to_have_attribute("data-tone", "accent")
    assert rows.nth(0).get_attribute("data-group") == "runs"


def test_a_stall_guard_stops_a_sleeping_code_node_and_aborts_the_run(
    page: Page, guard_url: str, guard_api: httpx.Client
) -> None:
    pipeline = build_pipeline(guard_api, stages=1, name="Stall")
    _stage, action = pipeline["stages"][0]
    link(
        guard_api,
        pipeline,
        action,
        code_definition(guard_api, "Sleeper", "import time\ntime.sleep(60)"),
    )
    guard_api.post(
        "/api/guards",
        json={
            "pipeline_id": pipeline["id"],
            "name": "Stall guard",
            "scope_type": "action",
            "scope_id": action["id"],
            "trigger": {"type": "interval", "every_seconds": 1, "for_seconds": 1},
            "when": {
                "type": "group",
                "mode": "all",
                "items": [{"type": "condition", "field": "idle", "op": "at_least", "value": 2}],
            },
            "consequence": "abort",
        },
    ).raise_for_status()
    task = _run(guard_api, pipeline, "Stalling")
    run = _status(guard_api, task, "failed")
    assert run["note"].startswith("Aborted by guard Stall guard fired at ")
    rows = _guard_rows(page, guard_url, guard_api, "Stalling")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("aborted the run")
    expect(rows.first).to_contain_text("without progress")
    expect(rows.first.locator(".history-marker")).to_have_attribute("data-tone", "bad")
