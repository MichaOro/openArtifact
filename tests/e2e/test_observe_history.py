"""The history of an observed pipeline (ADR-088, card #151): the flag *Observed* instead of *Dry run*, the *Observed* kind of the executions page, and the
quiet line of a step an observed run could not see. The rules (what an observed run does) are tested in tests/test_observe_mode.py."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import eventually
from tests.helpers import build_pipeline, connect, graph_url, kind_of, node, post


def _comment_then_read(api: httpx.Client) -> dict[str, Any]:
    """An action: Artifact 'Comment' (Add comment, a write), then Edit Fields 'Say' that reads the comment's result (what a skipped write cannot give)."""
    action = post(api, "/api/actions", name="Comment then read")
    trigger, output = kind_of(api, action, "trigger"), kind_of(api, action, "output")
    for edge in api.get(graph_url(action)).json()["edges"]:
        api.delete(f"{graph_url(action)}/edges/{edge['id']}")
    comment = node(
        api, action, "artifact", name="Comment", config={"operation": "Add comment", "text": "hi"}
    )
    say = node(api, action, "set", name="Say", config={"fields": "seen = ${(Comment).output}"})
    connect(api, action, trigger, "out", comment, "in")
    connect(api, action, comment, "pass", say, "in")
    connect(api, action, say, "pass", output, "pass")
    return action


def _observed_and_manual(
    api: httpx.Client,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """A published pipeline in the observe mode with one observed run (card "Watched") and one dry run by hand (card "Manual")."""
    pipeline = build_pipeline(api, stages=1, name="Trial pipeline")
    shell = pipeline["stages"][0][1]
    action = _comment_then_read(api)
    api.patch(
        f"{graph_url(pipeline)}/nodes/{shell['id']}", json={"definition_id": action["id"]}
    ).raise_for_status()
    api.put(
        f"/api/pipelines/{pipeline['id']}/observe",
        json={"enabled": True, "publish": True},
    ).raise_for_status()
    watched = post(api, "/api/tasks", title="Watched", status="backlog")
    api.post(
        f"/api/tasks/{watched['id']}/run", json={"pipeline_id": pipeline["id"]}
    ).raise_for_status()
    eventually(lambda: _status_of(api, "Watched"), "done", timeout=15)
    manual = post(api, "/api/tasks", title="Manual", status="backlog")
    api.post(
        f"/api/tasks/{manual['id']}/run",
        json={"pipeline_id": pipeline["id"], "dry_run": True, "version": "draft"},
    ).raise_for_status()
    eventually(
        lambda: _status_of(api, "Manual"), "failed", timeout=15
    )  # a manual dry run keeps failing at the node that needs a skipped write
    return pipeline, watched, manual


def _status_of(api: httpx.Client, title: str) -> str | None:
    for item in api.get("/api/executions").json()["items"]:
        if item["task"]["title"] == title:
            return str(item["status"])
    return None


def _row(page: Page, title: str) -> Any:
    return page.locator(".ex-row", has=page.locator("[data-artifact]", has_text=title))


def test_an_observed_run_shows_the_flag_observed_and_a_manual_dry_run_keeps_its_own(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _observed_and_manual(api)
    page.goto(f"{base_url}/executions")
    watched, manual = _row(page, "Watched"), _row(page, "Manual")
    expect(watched.locator(".history-flag")).to_have_text("Observed")
    expect(watched.locator(".history-flag")).to_have_attribute("data-kind", "observed")
    expect(manual.locator(".history-flag")).to_have_text("Dry run")
    expect(manual.locator(".history-flag")).to_have_attribute("data-kind", "dry")
    assert "Observed up to 'Say'" in watched.inner_text(), (
        "the run's note says where the observation ended"
    )


def test_the_kind_filter_has_observed_apart_from_the_dry_runs_started_by_hand(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _observed_and_manual(api)
    page.goto(f"{base_url}/executions")
    kind = page.get_by_role("group", name="Kind")
    expect(kind.get_by_role("radio")).to_have_count(4)
    expect(kind.locator("label")).to_have_text(["Any", "Real runs", "Dry runs", "Observed"])
    kind.locator(".ex-toggle", has_text="Observed").click()
    expect(page).to_have_url(f"{base_url}/executions?observed=only")
    expect(_row(page, "Watched")).to_be_visible()
    expect(_row(page, "Manual")).to_have_count(0)
    kind.locator(".ex-toggle", has_text="Dry runs").click()
    expect(page).to_have_url(f"{base_url}/executions?dry_run=only")
    expect(_row(page, "Manual")).to_be_visible()
    expect(_row(page, "Watched")).to_have_count(0)
    kind.locator(".ex-toggle", has_text="Real runs").click()
    expect(page.locator(".ex-row")).to_have_count(0)
    page.goto(f"{base_url}/executions?observed=only")  # a link keeps the kind
    expect(kind.get_by_role("radio", name="Observed")).to_be_checked()
    expect(_row(page, "Watched")).to_be_visible()


def test_the_execution_of_an_observed_run_says_observed_and_its_step_says_not_observable_quietly(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _, watched, _ = _observed_and_manual(api)
    run = next(r for r in api.get("/api/runs").json() if r["task_id"] == watched["id"])
    page.goto(f"{base_url}/artifacts/{watched['number']}/executions/{run['execution_id']}")
    flag = page.locator("[data-head-dry]")
    expect(flag).to_have_text("Observed")
    expect(flag).to_have_attribute("data-kind", "observed")
    page.locator(
        ".ge-node", has_text="Comment then read"
    ).first.click()  # the action: the path of its nodes
    page.locator(".ef-path__item", has=page.locator(".ef-path__label", has_text="Say")).locator(
        ".ef-path__main"
    ).click()
    quiet = page.locator("[data-panel-detail] [data-step-reason][data-not-observable]")
    expect(quiet).to_be_visible()
    expect(quiet).to_contain_text("Not observable from here")
    expect(quiet).not_to_contain_text("Reason:")  # a passed step: no reason of a failure
