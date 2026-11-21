"""The workflow list and the canvas editor."""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect


def _graph(api: httpx.Client, workflow: dict[str, Any]) -> dict[str, Any]:
    return api.get(f"/api/workflows/{workflow['id']}").json()  # type: ignore[no-any-return]


def _clear(api: httpx.Client) -> None:
    for workflow in api.get("/api/workflows").json():
        api.delete(f"/api/workflows/{workflow['id']}")


def _open(page: Page, base_url: str, workflow: dict[str, Any]) -> None:
    page.goto(f"{base_url}/workflows/{workflow['id']}")
    expect(page.locator(".wf-node").first).to_be_visible()


def _centre(locator: Locator) -> tuple[float, float]:
    box = locator.bounding_box()
    assert box is not None
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _drag(page: Page, source: Locator, target: Locator) -> None:
    sx, sy = _centre(source)
    tx, ty = _centre(target)
    page.mouse.move(sx, sy)
    page.mouse.down()
    page.mouse.move(tx, ty, steps=10)
    page.mouse.up()


def _edges(api: httpx.Client, workflow: dict[str, Any]) -> list[tuple[str, str]]:
    return sorted((e["source_port"], e["target_port"]) for e in _graph(api, workflow)["edges"])


# ── list ──────────────────────────────────────────────────────────────


def test_create_rename_and_delete_a_workflow_from_the_list(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _clear(api)
    page.goto(f"{base_url}/workflows")
    expect(page.locator("[data-wf-empty]")).to_be_visible()
    page.click("[data-new-workflow]")
    page.fill("#workflow-name", "Agentic Coding")
    page.click("#name-modal [data-submit]")
    expect(page).to_have_url(re.compile(r"/workflows/[0-9a-f-]{36}$"))
    expect(page.locator(".wf-node--trigger")).to_have_count(
        1
    )  # every workflow starts with a trigger

    page.goto(f"{base_url}/workflows")
    page.locator("[data-rename]").click()
    page.fill("#workflow-name", "Renamed")
    page.click("#name-modal [data-submit]")
    expect(page.locator(".wf-item__name")).to_have_text("Renamed")

    page.locator("[data-delete]").click()
    page.click("#confirm-modal [data-confirm]")
    expect(page.locator(".wf-item")).to_have_count(0)
    assert api.get("/api/workflows").json() == []


def test_workflow_name_is_required(page: Page, base_url: str, api: httpx.Client) -> None:
    _clear(api)
    page.goto(f"{base_url}/workflows")
    page.click("[data-new-workflow]")
    page.click("#name-modal [data-submit]")
    expect(page.locator("#workflow-name-error")).to_be_visible()
    assert api.get("/api/workflows").json() == []


# ── editor ────────────────────────────────────────────────────────────


def test_add_stage_and_actions_and_they_persist(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _clear(api)
    workflow = api.post("/api/workflows", json={"name": "Flow"}).json()
    _open(page, base_url, workflow)
    page.click("[data-add=stage]")
    expect(page.locator(".wf-node--stage")).to_have_count(1)
    page.locator("[data-add-action]").click()
    page.locator("[data-add-action]").click()
    expect(page.locator(".wf-node--action")).to_have_count(2)
    kinds = sorted(n["kind"] for n in _graph(api, workflow)["nodes"])
    assert kinds == ["action", "action", "stage", "trigger"]
    page.reload()
    expect(page.locator(".wf-node--action")).to_have_count(2)
    expect(page.locator(".wf-node--action").first).to_be_visible()


def _flow(page: Page, base_url: str, api: httpx.Client) -> dict[str, Any]:
    """A workflow with a trigger, one stage and two actions in it, opened in the editor."""
    _clear(api)
    workflow = api.post("/api/workflows", json={"name": "Flow"}).json()
    _open(page, base_url, workflow)
    page.click("[data-add=stage]")
    page.locator("[data-add-action]").click()
    page.locator("[data-add-action]").click()
    expect(page.locator(".wf-node--action")).to_have_count(2)
    page.click("[data-zoom-fit]")  # everything on screen, so ports can be reached with the mouse
    return workflow  # type: ignore[no-any-return]


def test_connect_by_dragging_between_ports(page: Page, base_url: str, api: httpx.Client) -> None:
    workflow = _flow(page, base_url, api)
    _drag(
        page,
        page.locator(".wf-node--trigger .wf-port--out"),
        page.locator(".wf-node--stage > .wf-port--in"),
    )
    _drag(
        page,
        page.locator(".wf-node--stage > .wf-port--entry"),
        page.locator(".wf-node--action").first.locator(".wf-port--in"),
    )
    _drag(
        page,
        page.locator(".wf-node--action").first.locator(".wf-port--pass"),
        page.locator(".wf-node--action").nth(1).locator(".wf-port--in"),
    )
    _drag(
        page,
        page.locator(".wf-node--action").nth(1).locator(".wf-port--error"),
        page.locator(".wf-node--stage > .wf-port--exit"),
    )
    expect(page.locator(".wf-edge")).to_have_count(4)
    assert _edges(api, workflow) == [
        ("entry", "in"),
        ("error", "exit"),
        ("out", "in"),
        ("pass", "in"),
    ]


def test_only_valid_targets_light_up_and_invalid_drops_do_nothing(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    workflow = _flow(page, base_url, api)
    page.click("[data-add=stage]")
    expect(page.locator(".wf-node--stage")).to_have_count(2)
    page.click("[data-zoom-fit]")
    first = page.locator(".wf-node--action").first.locator(".wf-port--pass")
    x, y = _centre(first)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 40, y + 40, steps=4)
    valid = page.locator(".wf-port.is-valid")
    # an action may reach actions of its own stage and the end of its own stage, nothing else
    expect(valid).to_have_count(3)
    stage_in = page.locator(".wf-node--stage").nth(1).locator("> .wf-port--in")
    tx, ty = _centre(stage_in)
    page.mouse.move(tx, ty, steps=6)
    page.mouse.up()
    assert _edges(api, workflow) == []
    expect(page.locator(".wf-port.is-valid")).to_have_count(0)


def test_connect_through_the_inspector_with_the_keyboard(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    workflow = _flow(page, base_url, api)
    first = page.locator(".wf-node--action").first
    first.focus()
    page.keyboard.press("Enter")  # selects and moves focus to the inspector
    pass_select = page.locator(".wf-inspector select").first
    pass_select.select_option(label=_second_action_name(page))
    expect(page.locator(".wf-edge")).to_have_count(1)
    assert _edges(api, workflow) == [("pass", "in")]
    pass_select.select_option(label="Not connected")
    expect(page.locator(".wf-edge")).to_have_count(0)
    assert _edges(api, workflow) == []


def _second_action_name(page: Page) -> str:
    return page.locator(".wf-node--action .wf-node__name").nth(1).inner_text()


def test_an_output_has_one_edge_and_reconnecting_replaces_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    workflow = _flow(page, base_url, api)
    first = page.locator(".wf-node--action").first
    _drag(
        page,
        first.locator(".wf-port--pass"),
        page.locator(".wf-node--action").nth(1).locator(".wf-port--in"),
    )
    _drag(page, first.locator(".wf-port--pass"), page.locator(".wf-node--stage > .wf-port--exit"))
    expect(page.locator(".wf-edge")).to_have_count(1)
    assert _edges(api, workflow) == [("pass", "exit")]


def test_error_may_loop_back_to_its_own_input(page: Page, base_url: str, api: httpx.Client) -> None:
    workflow = _flow(page, base_url, api)
    first = page.locator(".wf-node--action").first
    _drag(page, first.locator(".wf-port--error"), first.locator(".wf-port--in"))
    expect(page.locator(".wf-edge")).to_have_count(1)
    assert _edges(api, workflow) == [("error", "in")]


def test_select_and_delete_an_edge(page: Page, base_url: str, api: httpx.Client) -> None:
    workflow = _flow(page, base_url, api)
    _drag(
        page,
        page.locator(".wf-node--trigger .wf-port--out"),
        page.locator(".wf-node--stage > .wf-port--in"),
    )
    page.locator(".wf-edge__hit").first.click(force=True)
    expect(page.locator(".wf-inspector h2")).to_have_text("Connection")
    page.keyboard.press("Delete")
    expect(page.locator(".wf-edge")).to_have_count(0)
    assert _edges(api, workflow) == []


def test_move_rename_and_delete_a_node(page: Page, base_url: str, api: httpx.Client) -> None:
    workflow = _flow(page, base_url, api)
    action = page.locator(".wf-node--action").first
    before = next(n for n in _graph(api, workflow)["nodes"] if n["kind"] == "action")
    x, y = _centre(action.locator(".wf-node__name"))
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 60, y + 30, steps=6)
    page.mouse.up()
    expect(page.locator(".wf-inspector h2")).to_have_text("Action")
    moved = next(n for n in _graph(api, workflow)["nodes"] if n["id"] == before["id"])
    assert (moved["x"], moved["y"]) != (before["x"], before["y"])

    name = page.locator(".wf-inspector input").first
    name.fill("Gap analysis")
    name.press("Enter")
    expect(action.locator(".wf-node__name")).to_have_text("Gap analysis")

    page.locator(".wf-inspector .wf-delete").click()
    page.click("#confirm-modal [data-confirm]")
    expect(page.locator(".wf-node--action")).to_have_count(1)


def test_deleting_a_stage_asks_and_takes_its_actions_along(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    workflow = _flow(page, base_url, api)
    page.locator(".wf-stage__header").click(position={"x": 80, "y": 20})
    page.locator(".wf-inspector .wf-delete").click()
    expect(page.locator("#confirm-modal [data-confirm-message]")).to_contain_text("2 actions")
    page.click("#confirm-modal [data-confirm]")
    expect(page.locator(".wf-node--stage")).to_have_count(0)
    assert [n["kind"] for n in _graph(api, workflow)["nodes"]] == ["trigger"]


def test_zoom_controls_and_fit(page: Page, base_url: str, api: httpx.Client) -> None:
    _clear(api)
    workflow = api.post("/api/workflows", json={"name": "Flow"}).json()
    _open(page, base_url, workflow)
    label = page.locator("[data-zoom-label]")
    before = label.inner_text()
    page.click("[data-zoom-in]")
    assert label.inner_text() != before
    page.click("[data-zoom-out]")
    page.click("[data-zoom-out]")
    assert int(label.inner_text().rstrip("%")) < int(before.rstrip("%"))
    page.click("[data-zoom-fit]")
    expect(page.locator(".wf-node--trigger")).to_be_visible()


def test_editor_for_an_unknown_workflow_says_so(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/workflows/does-not-exist")
    expect(page.locator("[data-editor-error]")).to_contain_text("does not exist")
