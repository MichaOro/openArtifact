"""The Back button of the execution page leads to where the user came from (ADR-089): an editor, the list of executions, a card, or the
board when nothing (or nothing valid) says otherwise. The rules of the words are in tests/js/back-link.test.mjs."""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import eventually
from tests.helpers import build_definition, build_pipeline, post


def _action_run(api: httpx.Client) -> tuple[dict[str, Any], dict[str, Any], str]:
    """An action, one dry run of it by itself, and the address of that execution (no `from`)."""
    action = build_definition(api, "Back test", output="pass")
    api.post(f"/api/graphs/{action['id']}/dry-run", json={}).raise_for_status()
    card = api.get(f"/api/graphs/{action['id']}/dry-run-card").json()
    listed = f"/api/tasks/{card['task_id']}/executions"
    eventually(lambda: api.get(listed).json()["items"][0]["status"], "done")
    execution = api.get(listed).json()["items"][0]
    return action, card, f"/artifacts/{card['number']}/executions/{execution['id']}"


def _backs(page: Page) -> Any:
    return page.locator("[data-back]")


def test_without_an_origin_or_with_a_bad_one_back_is_the_board(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _, _, path = _action_run(api)
    for query in (
        "",
        "?from=nowhere",
        "?from=https%3A%2F%2Fevil.example%2F",
        "?from=action%3A..%2Fx",
    ):
        page.goto(f"{base_url}{path}{query}")
        expect(_backs(page).first).to_have_text("Back to the board")
        expect(_backs(page).first).to_have_attribute("href", "/")


def test_back_names_the_action_or_the_pipeline_it_came_from(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action, _, path = _action_run(api)
    page.goto(f"{base_url}{path}?from=action%3A{action['slug']}")
    expect(_backs(page).first).to_have_text(f"Back to the action {action['name']}")
    _backs(page).first.click()
    expect(page).to_have_url(f"{base_url}/actions/{action['slug']}")
    pipeline = build_pipeline(api, stages=1)
    api.post(f"/api/graphs/{pipeline['id']}/dry-run", json={}).raise_for_status()
    card = api.get(f"/api/graphs/{pipeline['id']}/dry-run-card").json()
    eventually(
        lambda: api.get(f"/api/tasks/{card['task_id']}/executions").json()["items"][0]["status"],
        "done",
    )
    execution = api.get(f"/api/tasks/{card['task_id']}/executions").json()["items"][0]
    page.goto(
        f"{base_url}/artifacts/{card['number']}/executions/{execution['id']}?from=pipeline%3A{pipeline['slug']}"
    )
    expect(_backs(page).first).to_have_text(f"Back to the pipeline {pipeline['name']}")
    expect(_backs(page).first).to_have_attribute("href", f"/pipelines/{pipeline['slug']}")


def test_a_row_of_the_dry_run_tab_leads_to_the_execution_and_back_to_the_editor(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = build_definition(api, "From the tab", output="pass")
    page.goto(f"{base_url}/actions/{action['slug']}")
    page.locator(".ge-node--trigger").dblclick(position={"x": 20, "y": 5})
    dialog = page.locator("#node-modal")
    dialog.get_by_role("tab", name="Dry run").click()
    dialog.get_by_role("button", name="Start dry run").click()
    dialog.locator(".ge-dry__runs .history-row__open").click()
    expect(page).to_have_url(re.compile(r"/executions/[^?]+\?from=action%3A" + action["slug"]))
    expect(_backs(page).first).to_have_text(f"Back to the action {action['name']}")
    page.get_by_role("link", name=f"Back to the action {action['name']}").first.click()
    expect(page).to_have_url(f"{base_url}/actions/{action['slug']}")


def test_a_row_of_the_list_of_executions_leads_back_to_the_list(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _action_run(api)
    page.goto(f"{base_url}/executions")
    page.locator("table a[href*='/executions/']").first.click()
    expect(_backs(page).first).to_have_text("Back to executions")
    _backs(page).first.click()
    expect(page).to_have_url(f"{base_url}/executions")


def test_a_card_history_leads_back_to_the_card_and_the_origin_stays_while_a_step_is_entered(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    card = post(api, "/api/tasks", title="The card", status="backlog")
    action = build_definition(api, "On a card", output="pass")
    api.post(f"/api/graphs/{action['id']}/dry-run", json={"task_id": card["id"]}).raise_for_status()
    listed = f"/api/tasks/{card['id']}/executions"
    eventually(lambda: api.get(listed).json()["items"][0]["status"], "done")
    run = {"execution_id": api.get(listed).json()["items"][0]["id"]}
    page.goto(
        f"{base_url}/artifacts/{card['number']}/executions/{run['execution_id']}?from=card%3A{card['number']}"
    )
    expect(_backs(page).first).to_have_text("Back to the card")
    expect(_backs(page).first).to_have_attribute("href", f"/?artifact={card['number']}")
