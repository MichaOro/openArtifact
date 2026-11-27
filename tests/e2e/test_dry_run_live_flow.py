"""The flow page of a RUNNING dry run shows what works, as a normal run does (ADR-089).

An action's dry run runs the action by itself: its flow is replayed from the action's own steps, with no pipeline around it. While a node works
there is no step of it yet, so the replay has to say that the run is in the node the last finished step leads to. The pipeline path did; the
stand-alone path did not, so the working node stayed faded, no bubbles ran along the edge and the path list ended at the Trigger.

What keeps a dry run running is a read: an HTTP GET to a local server that answers when the test lets it (see test_dry_run_stop.py)."""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e import test_dry_run_stop as _stop
from tests.e2e.helpers import eventually, flow_url, start, wait_executions
from tests.helpers import post

# the fixtures of the module whose slow server this test uses (a module attribute is what pytest finds)
_reading_pipeline = _stop._reading_pipeline
_slow_state = _stop._slow_state
local_url = _stop.local_url
api = _stop.api
slow_server = _stop.slow_server


def _signs(page: Page) -> dict[str, int]:
    """What the flow page shows while something works: the working node, the bubbles on an edge that was walked, the working step in the path."""
    return {
        "working node": page.locator(".ef-badge[data-state=running]").count(),
        "bubbles": page.locator(".ge-edge.is-walked .ef-bubbles").count(),
        "working step": page.locator(".ef-path__item[data-state=running]").count(),
    }


def _action(api: httpx.Client) -> dict[str, Any]:
    return next(a for a in api.get("/api/actions").json() if a["name"] == "Read")


def test_a_node_that_works_in_a_dry_run_is_drawn_as_working_with_bubbles_and_in_the_path(
    page: Page, local_url: str, api: httpx.Client, slow_server: dict[str, Any]
) -> None:
    _reading_pipeline(api, slow_server["url"])
    action = _action(api)
    started = api.post(f"/api/graphs/{action['id']}/dry-run", json={})
    assert started.status_code == 201, started.text
    task_id = started.json()["task_id"]
    eventually(
        lambda: api.get(f"/api/tasks/{task_id}/executions").json()["items"][0]["status"], "running"
    )
    execution = api.get(f"/api/tasks/{task_id}/executions").json()["items"][0]
    number = api.get(f"/api/tasks/{task_id}").json()["number"]
    page.goto(f"{local_url}/artifacts/{number}/executions/{execution['id']}")
    expect(page.locator("[data-head-chip]")).to_have_text("Running")
    # the HTTP node works: its badge, the bubbles on the edge that leads to it, the step in the path
    expect(page.locator(".ef-badge[data-state=running]").first).to_be_visible()
    expect(page.locator(".ge-edge.is-walked .ef-bubbles").first).to_be_attached()
    expect(page.locator(".ef-path__item[data-state=running]")).to_have_count(1)
    flow = api.get(f"/api/tasks/{task_id}/executions/{execution['id']}/flow").json()
    (visit,) = flow["visits"]
    assert visit["outcome"] == "running"
    http = next(n for n in flow["graphs"][action["id"]]["nodes"] if n["kind"] == "http")
    assert visit["nodes"][-1] == http["id"], "the visit ends in the node that works"
    # the answer comes: nothing works any more and nothing moves, with no reload
    slow_server["release"].set()
    expect(page.locator("[data-head-chip]")).to_have_text("Done")
    assert _signs(page) == {"working node": 0, "bubbles": 0, "working step": 0}


def test_a_dry_run_and_a_normal_run_show_the_same_signs_of_work(
    page: Page, local_url: str, api: httpx.Client, slow_server: dict[str, Any]
) -> None:
    """Parity: whatever a normal run shows for a node that works, the dry run of the same action shows too (a regression in either is caught)."""
    pipeline = _reading_pipeline(api, slow_server["url"])
    action = _action(api)
    # the normal run, through the pipeline, entered at its action
    task = post(api, "/api/tasks", title="Real card", status="backlog")
    start(api, task, pipeline)
    wait_executions(api, task, ["running"])
    real = api.get(f"/api/tasks/{task['id']}/executions").json()["items"][0]
    page.goto(flow_url(local_url, task, real))
    page.locator('.ge-node[aria-label^="Action: Read"]').click()
    expect(page.locator(".ef-badge[data-state=running]").first).to_be_visible()
    expect(page.locator(".ge-edge.is-walked .ef-bubbles").first).to_be_attached()
    real_signs = _signs(page)
    # the dry run of the action by itself
    started = api.post(f"/api/graphs/{action['id']}/dry-run", json={}).json()
    task_id = started["task_id"]
    eventually(
        lambda: api.get(f"/api/tasks/{task_id}/executions").json()["items"][0]["status"], "running"
    )
    dry = api.get(f"/api/tasks/{task_id}/executions").json()["items"][0]
    number = api.get(f"/api/tasks/{task_id}").json()["number"]
    page.goto(f"{local_url}/artifacts/{number}/executions/{dry['id']}")
    expect(page.locator(".ef-badge[data-state=running]").first).to_be_visible()
    expect(page.locator(".ge-edge.is-walked .ef-bubbles").first).to_be_attached()
    dry_signs = _signs(page)
    assert all(real_signs.values()), real_signs
    assert {key for key, count in dry_signs.items() if count} == {
        key for key, count in real_signs.items() if count
    }
    assert re.fullmatch(r"[0-9a-f-]{36}", dry["id"])
    slow_server["release"].set()


def test_a_pipeline_dry_run_shows_the_working_node_of_its_action_too(
    page: Page, local_url: str, api: httpx.Client, slow_server: dict[str, Any]
) -> None:
    pipeline = _reading_pipeline(api, slow_server["url"])
    started = api.post(f"/api/graphs/{pipeline['id']}/dry-run", json={})
    assert started.status_code == 201, started.text
    task_id = started.json()["task_id"]
    eventually(
        lambda: api.get(f"/api/tasks/{task_id}/executions").json()["items"][0]["status"], "running"
    )
    execution = api.get(f"/api/tasks/{task_id}/executions").json()["items"][0]
    number = api.get(f"/api/tasks/{task_id}").json()["number"]
    page.goto(f"{local_url}/artifacts/{number}/executions/{execution['id']}")
    page.locator('.ge-node[aria-label^="Action: Read"]').click()
    expect(page.locator(".ef-badge[data-state=running]").first).to_be_visible()
    expect(page.locator(".ge-edge.is-walked .ef-bubbles").first).to_be_attached()
    assert all(_signs(page).values()), _signs(page)
    slow_server["release"].set()
