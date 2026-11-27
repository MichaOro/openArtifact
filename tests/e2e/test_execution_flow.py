"""The read-only flow page of an execution: the walk drawn on the frozen snapshot, drilling into an
action, passes, the URL, the keyboard, live updates and the layout on a phone."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import (
    Board,
    echo_pipeline,
    execution_of,
    failing_pipeline,
    flow_url,
    nested_pipeline,
    retry_pipeline,
    run_started,
    slow_flow,
    start,
    two_stage_pipeline,
    wait_executions,
)


def _open(
    page: Page,
    base_url: str,
    api: httpx.Client,
    pipeline: dict[str, Any],
    query: str = "",
    **at: Any,
) -> dict[str, Any]:
    """Run the artifact in the pipeline, wait for the end and open the flow page of the execution."""
    task: dict[str, Any] = api.post("/api/tasks", json={"title": "Item"}).json()
    run_started(api, task, pipeline, **at)
    page.goto(f"{flow_url(base_url, task, execution_of(api, task))}{query}")
    expect(page.locator(".ge-node").first).to_be_visible()
    return task


def _node(page: Page, label: str) -> Locator:
    """A node of the canvas by the start of its aria label, e.g. "Action: Compile"."""
    return page.locator(f'.ge-node[aria-label^="{label}"]')


def _crumbs(page: Page) -> Locator:
    return page.locator("[data-crumbs] li")


def _state(name: str) -> re.Pattern[str]:
    return re.compile(rf"\bef-state-{name}\b")


def _item(page: Page, text: str) -> Locator:
    """An entry of the path list by its label."""
    return page.locator(".ef-path__item").filter(has=page.locator(".ef-path__label", has_text=text))


# ── the root flow ─────────────────────────────────────────────────────


def test_the_root_flow_shows_the_walked_stages_edges_and_passes(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    task = _open(page, base_url, api, two_stage_pipeline(api))
    expect(page.locator("[data-head-title]")).to_have_text(
        f"Execution #1 of #{task['number']} Item"
    )
    expect(page.locator("[data-head-chip]")).to_have_text("Done")
    expect(page.locator("[data-head-facts]")).to_contain_text("User")
    expect(page).to_have_title(re.compile(r"Execution #1"))
    expect(_crumbs(page)).to_have_text(["Release flow"])
    expect(page.locator(".ge-node")).to_have_count(6)  # trigger, 2 stages, 2 actions, complete
    expect(page.locator(".ge-node.ef-state-pass")).to_have_count(6)
    expect(page.locator(".ge-node.is-dim")).to_have_count(0)
    expect(page.locator(".ge-edge.is-walked")).to_have_count(7)
    expect(page.locator(".ge-edge.is-idle")).to_have_count(0)
    expect(page.locator(".ef-badge[data-state=pass]")).to_have_count(6)
    expect(page.locator(".ef-edge__order")).to_have_count(7)
    expect(page.locator(".ef-bubbles")).to_have_count(0)  # the run is over: no motion
    expect(page.locator(".ef-path__item")).to_have_count(6)
    expect(_node(page, "Stage: Build")).to_have_attribute("aria-label", "Stage: Build, passed")
    expect(_item(page, "Compile").locator("button", has_text="Open")).to_be_visible()


def test_a_run_started_at_a_later_stage_dims_what_did_not_run(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = two_stage_pipeline(api)
    _open(page, base_url, api, pipeline, stage_id=pipeline["stages"][1][0]["id"])
    build, ship = _node(page, "Stage: Build"), _node(page, "Stage: Ship")
    expect(build).to_have_class(re.compile(r"\bis-dim\b"))
    expect(build).to_have_attribute("aria-label", "Stage: Build, skipped")
    expect(build).to_have_css("opacity", re.compile(r"^0\.[0-6]"))
    expect(ship).not_to_have_class(re.compile(r"\bis-dim\b"))
    expect(ship).to_have_class(_state("pass"))
    expect(_node(page, "Action: Compile")).to_have_attribute(
        "aria-label", "Action: Compile, skipped"
    )
    expect(_item(page, "Build")).to_have_count(0)  # the path lists what was walked only
    expect(_item(page, "Ship")).to_have_count(1)
    assert page.locator(".ge-edge.is-idle").count() >= 3


def test_a_failing_action_shows_the_failure_and_the_error_edge(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _open(page, base_url, api, failing_pipeline(api))
    expect(page.locator("[data-head-chip]")).to_have_text("Done")
    verify = _node(page, "Action: Verify")
    expect(verify).to_have_class(_state("fail"))
    expect(verify.locator(".ef-badge")).to_have_attribute("data-state", "fail")
    expect(page.locator(".ge-edge--error.is-walked")).to_have_count(1)
    expect(page.locator(".ge-edge.is-walked")).to_have_count(
        4
    )  # trigger, stage, error edge, end of stage
    expect(_item(page, "Verify")).to_have_attribute("data-state", "fail")
    expect(_item(page, "Verify")).to_contain_text("Failed")
    verify.click()  # into the definition: the Code node failed with exit code 1
    expect(_node(page, "Execute Command: verify")).to_have_attribute(
        "aria-label", "Execute Command: verify, failed, exit code 1"
    )
    expect(page.locator("[data-panel-chips]")).to_have_text("Fail")


# ── drilling in ──────────────────────────────────────────────────────


def test_a_nested_pipeline_opens_with_a_breadcrumb_and_back_goes_up(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    outer, _inner = nested_pipeline(api)
    _open(page, base_url, api, outer)
    _node(page, "Pipeline: Inner flow").click()
    expect(_crumbs(page)).to_have_text(["Outer flow", "Inner flow"])
    expect(page.locator("[data-panel-title]")).to_have_text("Inner flow")
    expect(page.locator("[data-live]")).to_contain_text("Showing Pipeline Inner flow, level 2")
    _node(page, "Action: Inner work").click()
    expect(_crumbs(page)).to_have_text(
        ["Outer flow", "Inner flow", "Inner stage \u203a Inner work"]
    )
    expect(page.locator("[data-live]")).to_contain_text("Showing Action Inner work, level 3")
    page.locator("[data-up]").click()
    expect(_crumbs(page)).to_have_text(["Outer flow", "Inner flow"])
    expect(_node(page, "Action: Inner work")).to_have_class(re.compile(r"\bis-selected\b"))
    page.locator("[data-crumbs] a", has_text="Outer flow").click()
    expect(_crumbs(page)).to_have_text(["Outer flow"])
    expect(page.locator("[data-up]")).to_be_hidden()


def test_an_action_lists_its_steps_and_loads_the_output_when_it_is_opened(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    requested: list[str] = []
    page.on("request", lambda r: requested.append(r.url) if "/steps/" in r.url else None)
    _open(page, base_url, api, two_stage_pipeline(api))
    _node(page, "Action: Compile").click()
    expect(_crumbs(page)).to_have_text(["Release flow", "Build \u203a Compile"])
    expect(page.locator(".ef-path__label")).to_have_text(["Trigger", "compile", "Output"])
    expect(page.locator(".ef-path__item[data-state=pass]")).to_have_count(3)
    assert page.locator(".ge-edge.is-walked").count() == 2
    _item(page, "compile").locator(".ef-path__main").click()
    expect(page.locator("[data-panel-detail]")).to_contain_text("Exit code: 0")
    block = page.locator("[data-panel-detail] [data-step-output]")
    expect(block).to_be_visible()
    assert requested == []  # the output stays on the server until it is asked for
    block.locator("summary").click()
    expect(block.locator("pre")).to_have_text("Compile done\n")
    assert len(requested) == 1
    block.locator("summary").click()
    block.locator("summary").click()
    expect(block.locator("pre")).to_have_text("Compile done\n")
    assert len(requested) == 1  # loaded once


def test_an_action_that_ran_twice_has_passes_to_switch_between(
    page: Page, base_url: str, api: httpx.Client, tmp_path: Path
) -> None:
    _open(page, base_url, api, retry_pipeline(api, str(tmp_path / "marker")))
    expect(_node(page, "Action: Flaky").locator(".ef-badge")).to_contain_text("\u00d72")
    _node(page, "Action: Flaky").click()
    expect(page.locator("[data-pass-text]")).to_have_text("Pass 1 of 2")
    expect(_crumbs(page).last).to_contain_text("(pass 1 of 2)")
    code = _node(page, "Execute Command: flaky")
    expect(code).to_have_class(_state("fail"))
    expect(page.locator("[data-panel-chips]")).to_have_text("Fail")
    expect(page.locator("[data-pass-prev]")).to_be_disabled()
    page.locator("[data-pass-next]").click()
    expect(page.locator("[data-pass-text]")).to_have_text("Pass 2 of 2")
    expect(code).to_have_class(_state("pass"))
    expect(page.locator("[data-panel-chips]")).to_have_text("Pass")
    expect(page).to_have_url(re.compile(r"\?visit=2$"))
    expect(page.locator("[data-pass-next]")).to_be_disabled()
    page.locator("[data-pass-prev]").click()
    expect(page.locator("[data-pass-text]")).to_have_text("Pass 1 of 2")
    expect(code).to_have_class(_state("fail"))


def test_the_flow_stays_as_it_ran_when_the_pipeline_is_edited_or_deleted(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = two_stage_pipeline(api)
    _open(page, base_url, api, pipeline)
    names = page.locator(".ge-node__name").all_inner_texts()
    assert "Build" in names
    stage = pipeline["stages"][0][0]
    api.patch(f"/api/pipelines/{pipeline['id']}/nodes/{stage['id']}", json={"name": "Renamed"})
    api.patch(f"/api/pipelines/{pipeline['id']}", json={"name": "Renamed pipeline"})
    api.delete(f"/api/pipelines/{pipeline['id']}/nodes/{pipeline['stages'][1][0]['id']}")
    page.reload()
    expect(page.locator(".ge-node")).to_have_count(6)
    assert page.locator(".ge-node__name").all_inner_texts() == names
    expect(_crumbs(page)).to_have_text(["Release flow"])
    api.delete(
        f"/api/pipelines/{pipeline['id']}"
    )  # the execution keeps it, even if the delete is refused
    page.reload()
    expect(page.locator(".ge-node")).to_have_count(6)
    expect(page.locator(".ge-node.ef-state-pass")).to_have_count(6)


# ── live ──────────────────────────────────────────────────────────────


def test_a_running_execution_shows_running_and_finishes_without_a_reload(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    task = api.post("/api/tasks", json={"title": "Item"}).json()
    start(api, task, slow_flow(api, seconds=3))
    wait_executions(api, task, ["running"])
    page.goto(flow_url(base_url, task, execution_of(api, task)))
    expect(page.locator("[data-head-chip]")).to_have_text("Running")
    expect(page.locator(".ef-badge[data-state=running]").first).to_be_visible()
    expect(page.locator("[data-panel-chips]")).to_have_text("Running")
    # while it runs, bubbles flow along what was walked
    expect(page.locator(".ge-edge.is-walked .ef-bubbles").first).to_be_attached()
    page.evaluate("window.__same_page = true")
    expect(page.locator("[data-head-chip]")).to_have_text("Done", timeout=15000)
    expect(page.locator(".ef-bubbles")).to_have_count(
        0
    )  # a finished run shows only where it went, not motion
    expect(page.locator(".ef-badge[data-state=running]")).to_have_count(0)
    expect(page.locator("[data-panel-chips]")).to_have_text("Pass")
    assert page.evaluate("window.__same_page === true")


def test_the_place_survives_a_live_update(page: Page, base_url: str, api: httpx.Client) -> None:
    task = api.post("/api/tasks", json={"title": "Item"}).json()
    start(api, task, slow_flow(api, seconds=3))
    wait_executions(api, task, ["running"])
    page.goto(flow_url(base_url, task, execution_of(api, task)))
    _node(page, "Action: Wait").click()
    expect(_crumbs(page)).to_have_count(2)
    expect(page.locator("[data-head-chip]")).to_have_text("Done", timeout=15000)
    expect(_crumbs(page)).to_have_count(2)  # still inside the action
    expect(page.locator(".ef-path__item[data-state=pass]")).to_have_count(3)


def test_a_deleted_execution_says_so_with_the_way_back(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    task = api.post("/api/tasks", json={"title": "Item"}).json()
    start(api, task, echo_pipeline(api))
    wait_executions(api, task, ["done"])
    execution = execution_of(api, task)
    page.goto(flow_url(base_url, task, execution))
    expect(page.locator(".ge-node").first).to_be_visible()
    api.delete(f"/api/tasks/{task['id']}/executions/{execution['id']}").raise_for_status()
    expect(page.locator("[data-gone]")).to_be_visible()
    expect(page.locator("[data-gone-text]")).to_have_text("This execution was deleted.")
    expect(page.locator("[data-gone] a")).to_have_attribute("href", "/")
    expect(page.locator("[data-body]")).to_be_hidden()


def test_an_execution_that_does_not_exist_says_so(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    task = api.post("/api/tasks", json={"title": "Item"}).json()
    page.goto(f"{base_url}/artifacts/{task['number']}/executions/nope")
    expect(page.locator("[data-gone]")).to_be_visible()
    expect(page.locator("[data-gone-text]")).to_contain_text("does not exist")
    expect(page.locator("[data-gone-title]")).to_be_focused()
    assert errors == []


# ── the URL ────────────────────────────────────────────────────────────


def test_the_place_is_in_the_url_and_reload_and_back_restore_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    outer, _inner = nested_pipeline(api)
    _open(page, base_url, api, outer)
    root = page.url
    _node(page, "Pipeline: Inner flow").click()
    expect(page).to_have_url(re.compile(r"\?visit=1$"))
    _node(page, "Action: Inner work").click()
    expect(page).to_have_url(re.compile(r"\?visit=2$"))
    page.reload()
    expect(_crumbs(page)).to_have_count(3)
    expect(_node(page, "Execute Command: inner work")).to_be_visible()
    page.go_back()
    expect(page).to_have_url(re.compile(r"\?visit=1$"))
    expect(_crumbs(page)).to_have_text(["Outer flow", "Inner flow"])
    page.go_back()
    expect(page).to_have_url(root)
    expect(_crumbs(page)).to_have_text(["Outer flow"])
    page.go_forward()
    expect(_crumbs(page)).to_have_count(2)
    page.goto(f"{root}?visit=99")  # a place that is not there: the pipeline itself
    expect(_crumbs(page)).to_have_count(1)


# ── keyboard and reading ──────────────────────────────────────────────


def test_the_list_works_with_the_keyboard(page: Page, base_url: str, api: httpx.Client) -> None:
    _open(page, base_url, api, two_stage_pipeline(api))
    first = page.locator(".ef-path__main").first
    expect(first).to_have_attribute("aria-label", "1 Trigger: Trigger, passed")
    first.focus()
    page.keyboard.press("ArrowDown")
    expect(page.locator(".ef-path__main").nth(1)).to_be_focused()
    expect(_node(page, "Stage: Build")).to_have_class(re.compile(r"\bis-selected\b"))
    page.keyboard.press("ArrowDown")
    expect(page.locator(":focus")).to_contain_text("Compile")
    expect(_node(page, "Action: Compile")).to_have_class(re.compile(r"\bis-selected\b"))
    expect(page.locator("[data-panel-detail] .ef-detail__name")).to_have_text("Compile")
    page.keyboard.press("Enter")  # opens it
    expect(_crumbs(page)).to_have_count(2)
    expect(page.locator("[data-panel-title]")).to_be_focused()
    page.keyboard.press("Escape")  # and back up, to where it came from
    expect(_crumbs(page)).to_have_count(1)
    expect(page.locator(":focus")).to_contain_text("Compile")
    page.keyboard.press("End")
    expect(page.locator(".ef-path__main").last).to_be_focused()


def test_canvas_nodes_are_focusable_and_labelled_and_enter_opens_them(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _open(page, base_url, api, two_stage_pipeline(api))
    compile_ = _node(page, "Action: Compile")
    expect(compile_).to_have_attribute("aria-label", "Action: Compile, passed, Enter opens it")
    expect(compile_).to_have_attribute("tabindex", "0")
    compile_.focus()
    page.keyboard.press("Enter")
    expect(_crumbs(page)).to_have_count(2)
    expect(_node(page, "Execute Command: compile")).to_have_attribute(
        "aria-label", "Execute Command: compile, passed, exit code 0"
    )
    page.locator("[data-viewport]").focus()
    _node(page, "Execute Command: compile").focus()
    page.keyboard.press("Escape")
    expect(_crumbs(page)).to_have_count(1)


# ── read-only ──────────────────────────────────────────────────────────


def test_the_page_changes_nothing_and_nothing_on_it_can_be_edited(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    writes: list[str] = []
    page.on(
        "request", lambda r: writes.append(f"{r.method} {r.url}") if r.method != "GET" else None
    )
    _open(page, base_url, api, two_stage_pipeline(api))
    expect(page.locator("[data-add-menu], .ge-inspector")).to_have_count(0)
    expect(page.locator(".ge-stage__add").first).to_be_hidden()
    stage = _node(page, "Stage: Ship")
    before = stage.bounding_box()
    box = _node(page, "Action: Deliver").bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + 30, box["y"] + 30)
    page.mouse.down()
    page.mouse.move(box["x"] + 200, box["y"] + 150, steps=8)
    page.mouse.up()
    port = page.locator('.ge-node[aria-label^="Action: Deliver"] .ge-port--pass')
    port_box = port.bounding_box()
    assert port_box is not None
    page.mouse.move(port_box["x"] + 6, port_box["y"] + 6)
    page.mouse.down()
    page.mouse.move(port_box["x"] + 120, port_box["y"] + 90, steps=8)
    page.mouse.up()
    page.locator("[data-viewport]").click(position={"x": 10, "y": 10})
    _node(page, "Action: Deliver").focus()
    page.keyboard.press("Delete")
    page.keyboard.press("ArrowRight")
    page.locator(".ef-path__main").first.click()
    _node(page, "Action: Deliver").click()
    page.go_back()
    page.wait_for_load_state("networkidle")
    assert stage.bounding_box() == before
    expect(page.locator(".ge-node")).to_have_count(6)
    expect(page.locator(".ge-viewport--connecting, .is-connecting")).to_have_count(0)
    assert writes == []


def test_open_flow_in_the_history_tab_goes_to_the_page(
    board: Board, api: httpx.Client, page: Page
) -> None:
    task = board.create("Item")
    start(api, task, echo_pipeline(api))
    wait_executions(api, task, ["done"])
    dialog = board.open().open_card("Item").open_history()
    dialog.row(1).locator(".history-row__open").click()
    link = dialog.detail.locator("[data-detail-flow]")
    execution = execution_of(api, task)
    expect(link).to_have_attribute(
        "href", f"/artifacts/{task['number']}/executions/{execution['id']}"
    )
    link.click()
    expect(page).to_have_url(
        re.compile(rf"/artifacts/{task['number']}/executions/{execution['id']}$")
    )
    expect(page.locator(".ge-node--stage")).to_have_count(1)
    expect(page.locator("[data-head-title]")).to_have_text(
        f"Execution #1 of #{task['number']} Item"
    )
    expect(page.locator(".sidebar a[aria-current=page]")).to_have_text("Executions")


# ── layout and policy ──────────────────────────────────────────────────


def test_on_a_phone_the_panel_is_below_the_canvas(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.set_viewport_size({"width": 390, "height": 800})
    _open(page, base_url, api, two_stage_pipeline(api))
    canvas = page.locator("[data-viewport]").bounding_box()
    panel = page.locator("[data-panel]").bounding_box()
    assert canvas is not None and panel is not None
    assert panel["y"] >= canvas["y"] + canvas["height"] - 1
    assert canvas["x"] + canvas["width"] <= 390 and panel["x"] + panel["width"] <= 390
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(page.locator(".ge-node").first).to_be_visible()
    _item(page, "Compile").locator("button", has_text="Open").click()
    expect(_crumbs(page)).to_have_count(2)


def test_a_step_that_ran_several_times_has_one_open_button_and_the_pager_leads_through_the_passes(
    page: Page, base_url: str, api: httpx.Client, tmp_path: Path
) -> None:
    """The path of the panel used to list "Open pass 1", "Open pass 2", ... for a step that ran several times (and squeezed the
    name beside them). One "Open" is enough: the opened action pages through its passes."""
    _open(page, base_url, api, retry_pipeline(api, str(tmp_path / "marker")))
    page.get_by_role("button", name=re.compile("Flaky", re.I)).first.wait_for(state="attached")
    item = (
        page.locator('.ef-path__item[data-state="pass"], .ef-path__item[data-state="fail"]')
        .filter(has=page.locator(".ef-path__open"))
        .first
    )
    opens = item.locator(".ef-path__open")
    expect(opens).to_have_count(1)
    expect(opens).to_have_text("Open")
    expect(page.get_by_text(re.compile(r"^Open pass \d+$"))).to_have_count(0)
    label = item.locator(".ef-path__label").bounding_box()
    assert label and label["height"] < 40, "the name stays readable"
    opens.click()
    expect(page.locator("[data-pass-text]")).to_have_text("Pass 1 of 2")


def _guarded(api: httpx.Client, pipeline: dict[str, Any], enabled: bool = True) -> dict[str, Any]:
    from tests.e2e.test_guards import _attach, _guard

    attachment = _attach(
        api, _guard(api, "Watcher"), pipeline, "stage", pipeline["stages"][0][0]["id"]
    )
    if not enabled:
        api.put(
            f"/api/guard-attachments/{attachment['id']}/enabled", json={"enabled": False}
        ).raise_for_status()
    return attachment


def test_the_flow_shows_the_shield_of_a_guard_on_its_stage_grey_when_the_run_is_over(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = echo_pipeline(api)
    _guarded(api, pipeline)
    _open(page, base_url, api, pipeline)
    shield = page.locator(".ge-node--stage [data-guard-shield]")
    expect(shield).to_have_count(1)
    expect(shield).to_have_attribute("data-state", "idle")  # nothing is watching any more
    expect(shield).to_have_attribute("title", re.compile(r"1 guard, 0 active\nWatcher"))
    assert shield.evaluate("el => el.tagName") == "SPAN", "read-only: an icon, not a button"


def test_a_guard_that_is_not_switched_on_leaves_no_shield(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = echo_pipeline(api)
    _guarded(api, pipeline, enabled=False)
    _open(page, base_url, api, pipeline)
    expect(page.locator("[data-guard-shield]")).to_have_count(0)


def test_the_shield_is_green_and_pulses_while_the_stage_runs_and_turns_grey_when_it_ends(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = slow_flow(api, seconds=6)
    _guarded(api, pipeline)
    task: dict[str, Any] = api.post("/api/tasks", json={"title": "Item"}).json()
    start(api, task, pipeline)
    wait_executions(api, task, ["running"])
    page.goto(flow_url(base_url, task, execution_of(api, task)))
    shield = page.locator(".ge-node--stage [data-guard-shield]")
    expect(shield).to_have_attribute("data-state", "active", timeout=10000)
    assert shield.evaluate("el => getComputedStyle(el).animationName") != "none", "it pulses"
    expect(shield).to_have_attribute("title", re.compile(r"1 guard, 1 active"))
    expect(shield).to_have_attribute("data-state", "idle", timeout=20000)  # the stage is done
