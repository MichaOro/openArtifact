"""Retry on fail in a run (ADR-073): the steps of a node that was tried again, and a Stop while it waits for the next try."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import (
    arrange,
    code_definition,
    eventually,
    execution_of,
    flow_url,
    run_started,
    start,
    wait_executions,
)
from tests.helpers import build_pipeline, connect, graph_url, kind_of, link


def _retrying_pipeline(api: httpx.Client, retry: dict[str, Any]) -> dict[str, Any]:
    """One action whose Code node always fails and is tried again as `retry` says; On Error leads to the end of the stage."""
    pipeline = build_pipeline(api, stages=1, name="Retrying flow", stage_name="Check")
    stage, action = pipeline["stages"][0]
    definition = code_definition(api, "Flaky", "import sys\nprint('nope')\nsys.exit(1)")
    node = kind_of(api, definition, "code")
    api.patch(
        f"{graph_url(definition)}/nodes/{node['id']}", json={"config": {"retry": retry}}
    ).raise_for_status()
    link(api, pipeline, action, definition)
    connect(api, pipeline, action, "error", stage, "end")
    arrange(api, pipeline)
    return pipeline


def test_a_node_that_was_tried_again_says_so_and_lists_its_tries(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _retrying_pipeline(api, {"enabled": True, "max_tries": 2, "wait_ms": 0})
    task: dict[str, Any] = api.post("/api/tasks", json={"title": "Item"}).json()
    run_started(api, task, pipeline)
    page.goto(flow_url(base_url, task, execution_of(api, task)))
    page.locator('.ge-node[aria-label^="Action: Check"], .ge-node--action').first.click()
    page.locator(".ef-path__item").filter(has_text="flaky").locator(".ef-path__main").click()
    detail = page.locator("[data-panel-detail]")
    expect(detail).to_contain_text("2 tries")  # the fact line of the step
    block = detail.locator("[data-step-tries]")
    expect(block.locator("summary")).to_have_text("Tried 2 times")
    block.locator("summary").click()
    items = block.locator("li")
    expect(items).to_have_count(2)
    expect(items.nth(0)).to_contain_text("Try 1 of 2 failed after")
    expect(items.nth(0)).to_contain_text("Exit code 1")
    expect(items.nth(1)).to_have_text("Try 2 of 2 failed: Exit code 1")


def test_stopping_the_run_from_the_list_ends_a_wait_between_tries_at_once(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _retrying_pipeline(api, {"enabled": True, "max_tries": 3, "wait_ms": 120000})
    task: dict[str, Any] = api.post("/api/tasks", json={"title": "Item"}).json()
    start(api, task, pipeline)
    wait_executions(api, task, ["running"])
    page.goto(f"{base_url}/executions")
    row = page.locator("tr", has=page.locator("[data-stop]")).first
    expect(row.locator(".history-chip")).to_have_text(
        "Running"
    )  # it waits two minutes for the second try
    row.locator("[data-stop]").click()
    page.locator("#confirm-modal").get_by_role("button", name="Stop execution").click()
    expect(row.locator(".history-chip")).to_have_text("Stopped", timeout=5000)  # not after the wait
    eventually(
        lambda: [
            e["status"] for e in api.get(f"/api/tasks/{task['id']}/executions").json()["items"]
        ],
        ["stopped"],
    )
