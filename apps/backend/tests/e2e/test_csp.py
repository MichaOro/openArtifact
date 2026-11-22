"""The strict content security policy: no page needs, or breaks on, a blocked script or style."""

from __future__ import annotations

import httpx
import pytest
from playwright.sync_api import ConsoleMessage, Page, expect

from tests.e2e.conftest import SECURED_TOKEN
from tests.e2e.helpers import echo_pipeline, execution_of, flow_url, run_started


def _watch(page: Page) -> list[str]:
    """Everything the browser reports that is a policy violation, an error or a script error."""
    problems: list[str] = []

    def console(message: ConsoleMessage) -> None:
        if message.type in ("error", "warning") or "Content Security Policy" in message.text:
            problems.append(message.text)

    page.on("console", console)
    page.on("pageerror", lambda e: problems.append(str(e)))
    return problems


def test_the_policy_is_strict_on_every_page(base_url: str, api: httpx.Client) -> None:
    for path in (
        "/",
        "/pipelines",
        "/actions",
        "/executions",
        "/login",
        "/artifacts/1/executions/x",
    ):
        csp = httpx.get(f"{base_url}{path}", follow_redirects=True).headers[
            "content-security-policy"
        ]
        assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp.split("style-src")[0]


@pytest.mark.parametrize("path", ["/", "/pipelines", "/actions", "/executions", "/login"])
def test_pages_run_without_a_policy_violation(page: Page, base_url: str, path: str) -> None:
    problems = _watch(page)
    page.goto(f"{base_url}{path}")
    page.wait_for_load_state("networkidle")
    assert problems == []


def test_the_board_with_artifacts_and_its_dialog_run_without_a_violation(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    api.post("/api/tasks", json={"title": "Seen"}).raise_for_status()
    problems = _watch(page)
    page.goto(base_url)
    expect(page.locator(".task-card")).to_have_count(1)
    page.locator(".task-card__title").click()
    expect(page.locator("#create-task-modal")).to_be_visible()
    page.wait_for_load_state("networkidle")
    assert problems == []


def test_the_editor_runs_without_a_violation(page: Page, base_url: str, api: httpx.Client) -> None:
    pipeline = api.post("/api/pipelines", json={"name": "Strict"}).json()
    problems = _watch(page)
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    expect(page.locator(".ge-node").first).to_be_visible()
    page.wait_for_load_state("networkidle")
    assert problems == []


def test_the_execution_flow_runs_without_a_violation(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    task = api.post("/api/tasks", json={"title": "Seen"}).json()
    run_started(api, task, echo_pipeline(api))
    problems = _watch(page)
    page.goto(flow_url(base_url, task, execution_of(api, task)))
    expect(page.locator(".ge-node").first).to_be_visible()
    page.locator(".ge-node--action").click()
    page.wait_for_load_state("networkidle")
    assert problems == []


def test_the_executions_page_with_rows_runs_without_a_violation(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    task = api.post("/api/tasks", json={"title": "Seen"}).json()
    run_started(api, task, echo_pipeline(api))
    problems = _watch(page)
    page.goto(f"{base_url}/executions?status=done&range=24h")
    expect(page.locator(".ex-row")).to_have_count(1)
    page.locator("[data-delete]").hover()
    page.wait_for_load_state("networkidle")
    assert problems == []


def test_the_sign_in_page_of_a_secured_server_runs_without_a_violation(
    page: Page, secured_url: str
) -> None:
    problems = _watch(page)
    page.goto(secured_url)
    page.fill("#token", SECURED_TOKEN)
    page.click("button[type=submit]")
    expect(page.locator(".lane")).to_have_count(3)
    page.wait_for_load_state("networkidle")
    assert problems == []


def test_an_inline_script_is_really_blocked(page: Page, base_url: str) -> None:
    """The policy is enforced by the browser, not only announced: an injected inline script does not run."""
    problems = _watch(page)
    page.goto(f"{base_url}/login")
    page.evaluate(
        "() => { const s = document.createElement('script'); s.textContent = 'window.__ran = 1';"
        " document.head.append(s); }"
    )
    assert page.evaluate("window.__ran === undefined")
    assert any("Content Security Policy" in p for p in problems)


def test_renaming_a_lane_runs_without_a_violation(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    problems = _watch(page)
    page.goto(base_url)
    page.locator('[data-lane][data-status="done"] [data-rename-lane]').click()
    field = page.locator("#rename-lane-modal-field-title")
    field.fill("Shipped")
    field.press("Enter")
    expect(page.locator('[data-lane][data-status="done"] .lane__title')).to_have_text(
        "Shipped", use_inner_text=False
    )
    page.wait_for_load_state("networkidle")
    assert problems == []
