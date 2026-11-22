"""The pipeline list and the canvas editor."""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.helpers import graph_url


def _graph(api: httpx.Client, pipeline: dict[str, Any]) -> dict[str, Any]:
    return api.get(graph_url(pipeline)).json()  # type: ignore[no-any-return]


def _open(page: Page, base_url: str, pipeline: dict[str, Any]) -> None:
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    expect(page.locator(".ge-node").first).to_be_visible()


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


def _expect_edges(
    page: Page, api: httpx.Client, pipeline: dict[str, Any], expected: list[tuple[str, str]]
) -> None:
    """The server's edges become `expected` (changes are saved asynchronously, so this polls)."""
    for _ in range(100):
        if _edges(api, pipeline) == expected:
            return
        page.wait_for_timeout(50)
    assert _edges(api, pipeline) == expected, _graph(api, pipeline)["edges"]


def _add_stage(page: Page) -> None:
    page.click("[data-add-menu]")
    page.click("[data-add=stage]")


def _edges(api: httpx.Client, pipeline: dict[str, Any]) -> list[tuple[str, str]]:
    return sorted((e["source_port"], e["target_port"]) for e in _graph(api, pipeline)["edges"])


# ── list ──────────────────────────────────────────────────────────────


def test_create_rename_and_delete_a_pipeline_from_the_list(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.goto(f"{base_url}/pipelines")
    expect(page.locator("[data-ge-empty]")).to_be_visible()
    page.click("[data-new-graph]")
    page.fill("#name-modal-field-name", "Agentic Coding")
    page.click("#name-modal [data-submit]")
    expect(page).to_have_url(f"{base_url}/pipelines/agentic-coding")  # the name, not an id
    expect(page.locator(".ge-node--trigger")).to_have_count(1)
    expect(page.locator(".ge-node--complete")).to_have_count(1)
    expect(page.locator(".ge-edge")).to_have_count(1)  # connected by default

    page.goto(f"{base_url}/pipelines")
    page.locator("[data-rename]").click()
    page.fill("#name-modal-field-name", "Renamed")
    page.click("#name-modal [data-submit]")
    expect(page.locator(".ge-item__name")).to_have_text("Renamed")

    page.locator("[data-delete]").click()
    page.click("#confirm-modal [data-confirm]")
    expect(page.locator(".ge-item")).to_have_count(0)
    assert api.get("/api/pipelines").json() == []


def test_pipeline_name_is_required(page: Page, base_url: str, api: httpx.Client) -> None:
    page.goto(f"{base_url}/pipelines")
    page.click("[data-new-graph]")
    page.click("#name-modal [data-submit]")
    expect(page.locator("#name-modal-field-name-error")).to_be_visible()
    assert api.get("/api/pipelines").json() == []


# ── editor ────────────────────────────────────────────────────────────


def test_add_stage_and_actions_and_they_persist(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = api.post("/api/pipelines", json={"name": "Flow"}).json()
    _open(page, base_url, pipeline)
    _add_stage(page)
    expect(page.locator(".ge-node--stage")).to_have_count(1)
    page.locator("[data-add-action]").click()
    page.locator("[data-add-action]").click()
    expect(page.locator(".ge-node--action")).to_have_count(2)
    kinds = sorted(n["kind"] for n in _graph(api, pipeline)["nodes"])
    assert kinds == ["action", "action", "complete", "stage", "trigger"]
    page.reload()
    expect(page.locator(".ge-node--action")).to_have_count(2)
    expect(page.locator(".ge-node--action").first).to_be_visible()


def _flow(page: Page, base_url: str, api: httpx.Client) -> dict[str, Any]:
    """A pipeline with a trigger, one stage and two actions in it, opened in the editor."""
    pipeline = api.post("/api/pipelines", json={"name": "Flow"}).json()
    for edge in _graph(api, pipeline)["edges"]:  # start without the default connection
        api.delete(f"{graph_url(pipeline)}/edges/{edge['id']}")
    _open(page, base_url, pipeline)
    _add_stage(page)
    page.locator("[data-add-action]").click()
    page.locator("[data-add-action]").click()
    expect(page.locator(".ge-node--action")).to_have_count(2)
    page.click("[data-zoom-fit]")  # everything on screen, so ports can be reached with the mouse
    return pipeline  # type: ignore[no-any-return]


def test_connect_by_dragging_between_ports(page: Page, base_url: str, api: httpx.Client) -> None:
    pipeline = _flow(page, base_url, api)
    _drag(
        page,
        page.locator(".ge-node--trigger .ge-port--out"),
        page.locator(".ge-node--stage > .ge-port--start[data-slot='0']"),
    )
    _drag(
        page,
        page.locator(".ge-node--stage > .ge-port--start[data-slot='0']"),
        page.locator(".ge-node--action").first.locator(".ge-port--in"),
    )
    _drag(
        page,
        page.locator(".ge-node--action").first.locator(".ge-port--pass"),
        page.locator(".ge-node--action").nth(1).locator(".ge-port--in"),
    )
    _drag(
        page,
        page.locator(".ge-node--action").nth(1).locator(".ge-port--error"),
        page.locator(".ge-node--stage > .ge-port--end[data-slot='0']"),
    )
    expect(page.locator(".ge-edge")).to_have_count(4)
    _expect_edges(
        page,
        api,
        pipeline,
        [
            ("error", "end"),
            ("out", "start"),
            ("pass", "in"),
            ("start", "in"),
        ],
    )


def test_only_valid_targets_light_up_and_invalid_drops_do_nothing(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    _add_stage(page)
    expect(page.locator(".ge-node--stage")).to_have_count(2)
    page.click("[data-zoom-fit]")
    first = page.locator(".ge-node--action").first.locator(".ge-port--pass")
    x, y = _centre(first)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 40, y + 40, steps=4)
    valid = page.locator(".ge-port.is-valid")
    # an action may reach actions of its own stage and the end of its own stage (3 points), nothing else
    expect(valid).to_have_count(5)
    stage_in = page.locator(".ge-node--stage").nth(1).locator("> .ge-port--start[data-slot='0']")
    tx, ty = _centre(stage_in)
    page.mouse.move(tx, ty, steps=6)
    page.mouse.up()
    _expect_edges(page, api, pipeline, [])
    expect(page.locator(".ge-port.is-valid")).to_have_count(0)


def test_an_output_has_one_edge_and_reconnecting_replaces_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    first = page.locator(".ge-node--action").first
    _drag(
        page,
        first.locator(".ge-port--pass"),
        page.locator(".ge-node--action").nth(1).locator(".ge-port--in"),
    )
    _drag(
        page,
        first.locator(".ge-port--pass"),
        page.locator(".ge-node--stage > .ge-port--end[data-slot='0']"),
    )
    expect(page.locator(".ge-edge")).to_have_count(1)
    _expect_edges(page, api, pipeline, [("pass", "end")])


def test_error_may_loop_back_to_its_own_input(page: Page, base_url: str, api: httpx.Client) -> None:
    pipeline = _flow(page, base_url, api)
    first = page.locator(".ge-node--action").first
    _drag(page, first.locator(".ge-port--error"), first.locator(".ge-port--in"))
    expect(page.locator(".ge-edge")).to_have_count(1)
    _expect_edges(page, api, pipeline, [("error", "in")])


def test_select_and_delete_an_edge(page: Page, base_url: str, api: httpx.Client) -> None:
    pipeline = _flow(page, base_url, api)
    _drag(
        page,
        page.locator(".ge-node--trigger .ge-port--out"),
        page.locator(".ge-node--stage > .ge-port--start[data-slot='0']"),
    )
    page.locator(".ge-edge__hit").first.click(force=True)
    expect(page.locator(".ge-inspector h2")).to_have_text("Connection")
    page.keyboard.press("Delete")
    expect(page.locator(".ge-edge")).to_have_count(0)
    _expect_edges(page, api, pipeline, [])


def _connect_trigger_to_stage(page: Page) -> None:
    _drag(
        page,
        page.locator(".ge-node--trigger .ge-port--out"),
        page.locator(".ge-node--stage > .ge-port--start[data-slot='0']"),
    )
    expect(page.locator(".ge-edge")).to_have_count(1)


def test_the_inspector_keeps_keyboard_focus_when_it_is_redrawn(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    _connect_trigger_to_stage(page)
    page.locator(".ge-edge__hit").first.click(force=True)
    elbow = page.locator(".ge-style[data-style=elbow]")
    elbow.focus()
    page.keyboard.press("Enter")
    expect(elbow).to_have_attribute("aria-pressed", "true")
    expect(elbow).to_be_focused()
    styles = [e["style"] for e in _graph(api, pipeline)["edges"]]
    assert styles == ["elbow"]


def test_delete_on_a_focused_node_does_not_also_delete_the_selected_edge(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    _connect_trigger_to_stage(page)
    page.locator(".ge-edge__hit").first.click(force=True)
    expect(page.locator(".ge-inspector h2")).to_have_text("Connection")
    page.locator(".ge-node--stage").focus()  # Tab to a node: the selection stays on the edge
    page.keyboard.press("Delete")
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.click("#confirm-modal [data-cancel]")
    expect(page.locator(".ge-edge")).to_have_count(1)
    _expect_edges(page, api, pipeline, [("out", "start")])


def test_the_page_title_keeps_focus_after_it_is_renamed(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    title = page.locator(".app-header__title")
    title.click()
    page.keyboard.press("Control+A")
    page.keyboard.type("Flow two")
    page.keyboard.press("Enter")
    expect(title).to_have_text("Flow two")
    expect(title).to_be_focused()
    for _ in range(100):
        if _graph(api, pipeline)["graph"]["name"] == "Flow two":
            break
        page.wait_for_timeout(50)
    assert _graph(api, pipeline)["graph"]["name"] == "Flow two"


def test_move_rename_and_delete_a_node(page: Page, base_url: str, api: httpx.Client) -> None:
    pipeline = _flow(page, base_url, api)
    action = page.locator(".ge-node--action").first
    before = next(n for n in _graph(api, pipeline)["nodes"] if n["kind"] == "action")
    x, y = _centre(action.locator(".ge-node__name"))
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 60, y + 30, steps=6)
    page.mouse.up()
    expect(page.locator(".ge-inspector h2")).to_have_text("Action")
    for _ in range(100):  # saved asynchronously
        moved = next(n for n in _graph(api, pipeline)["nodes"] if n["id"] == before["id"])
        if (moved["x"], moved["y"]) != (before["x"], before["y"]):
            break
        page.wait_for_timeout(50)
    assert (moved["x"], moved["y"]) != (before["x"], before["y"])

    expect(page.locator(".ge-inspector input")).to_have_count(
        0
    )  # a shell is named by its definition
    trigger = page.locator(".ge-node--trigger")
    trigger.locator(".ge-node__name").click()
    page.locator(".ge-inspector h2").click()  # the name is edited in place
    name = page.locator(".ge-inspector input").first
    name.fill("Manual start")
    name.press("Enter")
    expect(trigger.locator(".ge-node__name")).to_have_text("Manual start")
    action.locator(".ge-node__name").click()

    page.locator(".ge-inspector .ge-delete").click()
    page.click("#confirm-modal [data-confirm]")
    expect(page.locator(".ge-node--action")).to_have_count(1)


def test_deleting_a_stage_asks_and_takes_its_actions_along(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    page.locator(".ge-stage__header").click(position={"x": 80, "y": 20})
    page.locator(".ge-inspector .ge-delete").click()
    expect(page.locator("#confirm-modal [data-confirm-message]")).to_contain_text("2 actions")
    page.click("#confirm-modal [data-confirm]")
    expect(page.locator(".ge-node--stage")).to_have_count(0)
    assert sorted(n["kind"] for n in _graph(api, pipeline)["nodes"]) == ["complete", "trigger"]


def test_zoom_controls_and_fit(page: Page, base_url: str, api: httpx.Client) -> None:
    pipeline = api.post("/api/pipelines", json={"name": "Flow"}).json()
    _open(page, base_url, pipeline)
    label = page.locator("[data-zoom-label]")
    before = label.inner_text()
    page.click("[data-zoom-in]")
    assert label.inner_text() != before
    page.click("[data-zoom-out]")
    page.click("[data-zoom-out]")
    assert int(label.inner_text().rstrip("%")) < int(before.rstrip("%"))
    page.click("[data-zoom-fit]")
    expect(page.locator(".ge-node--trigger")).to_be_visible()


def test_editor_for_an_unknown_pipeline_says_so(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/pipelines/does-not-exist")
    expect(page.locator("[data-alert]")).to_contain_text("does not exist")


def test_a_stage_offers_three_points_per_side_and_shows_the_used_one(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    ports = page.locator(".ge-node--stage > .ge-port--start")
    expect(ports).to_have_count(3)
    page.mouse.move(0, 0)
    expect(ports.nth(1)).to_have_css("opacity", "0")
    _drag(page, page.locator(".ge-node--trigger .ge-port--out"), ports.nth(1))
    page.mouse.move(0, 0)
    expect(ports.nth(1)).to_have_css("opacity", "1")
    expect(ports.nth(0)).to_have_css("opacity", "0")
    for _ in range(100):
        edges = _graph(api, pipeline)["edges"]
        if edges:
            break
        page.wait_for_timeout(50)
    assert (edges[0]["target_slot"], edges[0]["source_slot"]) == (1, 0)


def test_choose_the_line_style_of_a_connection(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    _drag(
        page,
        page.locator(".ge-node--trigger .ge-port--out"),
        page.locator(".ge-node--stage > .ge-port--start[data-slot='0']"),
    )
    page.locator(".ge-edge__hit").first.click(force=True)
    line = page.locator(".ge-edge__line").first
    curved = line.get_attribute("d")
    assert curved is not None and " C " in curved
    page.click(".ge-style[data-style=straight]")
    straight = line.get_attribute("d")
    assert straight is not None and " C " not in straight and " Q " not in straight
    page.click(".ge-style[data-style=elbow]")
    expect(page.locator(".ge-style[data-style=elbow]")).to_have_attribute("aria-pressed", "true")
    for _ in range(100):
        if _graph(api, pipeline)["edges"][0]["style"] == "elbow":
            break
        page.wait_for_timeout(50)
    assert _graph(api, pipeline)["edges"][0]["style"] == "elbow"
    page.reload()
    expect(page.locator(".ge-edge")).to_have_count(1)


# ── action definitions ────────────────────────────────────────────────


def test_create_an_action_definition_from_the_navigation(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.goto(f"{base_url}/pipelines")
    page.click(".nav-link[href='/actions']")
    expect(page).to_have_url(re.compile(r"/actions$"))
    expect(page.locator("[data-ge-empty]")).to_be_visible()
    page.click("[data-new-graph]")
    page.fill("#name-modal-field-name", "Gap analysis")
    page.click("#name-modal [data-submit]")
    expect(page).to_have_url(f"{base_url}/actions/gap-analysis")
    expect(page.locator(".ge-node--trigger")).to_have_count(1)
    expect(page.locator(".ge-node--output")).to_have_count(1)
    page.click("[data-add-menu]")
    expect(page.locator("[data-add-list] [data-add]")).to_have_text(
        ["Timer", "Code", "HTTP request"]
    )


def test_on_pass_is_always_there_and_on_fail_is_switched_on_and_off(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = api.post("/api/actions", json={"name": "Check"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    output = page.locator(".ge-node--output")
    expect(output.locator(".ge-port--pass")).to_be_visible()  # a connector of its own
    expect(output.locator(".ge-port--fail")).to_be_hidden()
    output.locator(".ge-node__name").click()
    page.locator(".ge-switch").click()
    expect(output.locator(".ge-port--fail")).to_be_visible()
    for _ in range(100):
        nodes = _graph(api, definition)["nodes"]
        if next(n for n in nodes if n["kind"] == "output")["fail_enabled"]:
            break
        page.wait_for_timeout(50)
    page.reload()
    expect(page.locator(".ge-node--output .ge-port--fail")).to_be_visible()
    page.locator(".ge-node--output .ge-node__name").click()
    page.locator(".ge-switch").click()
    expect(page.locator(".ge-node--output .ge-port--fail")).to_be_hidden()
    expect(page.locator(".ge-inspector .ge-delete")).to_have_count(0)  # output stays


def test_the_trigger_is_routed_to_on_pass_or_on_fail(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = api.post("/api/actions", json={"name": "Check"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    expect(page.locator(".ge-edge")).to_have_count(1)  # connected to On Pass by default
    _expect_edges(page, api, definition, [("out", "pass")])
    page.locator(".ge-node--output .ge-node__name").click()
    page.locator(".ge-switch").click()
    _drag(
        page,
        page.locator(".ge-node--trigger .ge-port--out"),
        page.locator(".ge-node--output .ge-port--fail"),
    )
    _expect_edges(page, api, definition, [("out", "fail")])
    page.locator(".ge-switch").click()  # switching On Fail off takes its connection along
    expect(page.locator(".ge-edge")).to_have_count(0)
    _expect_edges(page, api, definition, [])


def test_the_add_menu_offers_stages_and_trigger_and_complete_stay(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = api.post("/api/pipelines", json={"name": "Flow"}).json()
    _open(page, base_url, pipeline)
    expect(page.locator(".ge-bar [data-add]")).to_have_count(0)  # no longer in the toolbar
    menu = page.locator("[data-add-list]")
    expect(menu).to_be_hidden()
    page.click("[data-add-menu]")
    expect(menu.locator("[data-add]")).to_have_text(["Stage", "Pipeline"])
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    for kind in ("trigger", "complete"):
        page.locator(f".ge-node--{kind} .ge-node__name").click()
        expect(page.locator(".ge-inspector .ge-delete")).to_have_count(0)
        page.keyboard.press("Delete")
        expect(page.locator(f".ge-node--{kind}")).to_have_count(1)
        expect(page.locator("#confirm-modal[open]")).to_have_count(0)


def test_a_new_stage_makes_room_before_complete(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = api.post("/api/pipelines", json={"name": "Flow"}).json()
    _open(page, base_url, pipeline)
    _add_stage(page)
    expect(page.locator(".ge-node--stage")).to_have_count(1)
    for _ in range(100):
        nodes = {n["kind"]: n for n in _graph(api, pipeline)["nodes"]}
        if nodes["complete"]["x"] >= nodes["stage"]["x"] + nodes["stage"]["width"]:
            break
        page.wait_for_timeout(50)
    assert nodes["complete"]["x"] >= nodes["stage"]["x"] + nodes["stage"]["width"]


# ── linking an action shell to an action definition ───────────────────


def _definition(api: httpx.Client, name: str, fail: bool = False) -> dict[str, Any]:
    definition = api.post("/api/actions", json={"name": name}).json()
    if fail:
        output = next(n for n in _graph(api, definition)["nodes"] if n["kind"] == "output")
        api.patch(f"{graph_url(definition)}/nodes/{output['id']}", json={"fail_enabled": True})
    return definition  # type: ignore[no-any-return]


def test_a_new_action_is_defined_in_actions_and_selected_again_on_return(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    shell = page.locator(".ge-node--action").first
    shell.locator(".ge-node__name").click()
    expect(page.locator(".ge-inspector h2")).to_have_text("Action")
    expect(page.locator(".ge-inspector h3", has_text="Routing")).to_have_count(0)
    expect(page.locator(".ge-actionbar .button")).to_have_text(["New", "Edit", "Delete"])
    expect(page.locator(".ge-actionbar a")).to_have_attribute(
        "aria-disabled", "true"
    )  # nothing yet
    page.click(".ge-actionbar >> text=New")
    expect(page.locator("#new-modal")).to_be_visible()
    page.click("#new-modal [data-submit]")
    expect(page.locator("#new-modal-field-name-error")).to_be_visible()  # a name is required
    page.fill("#new-modal-field-name", "Gap analysis")
    page.click("#new-modal [data-submit]")
    expect(page).to_have_url(re.compile(r"/actions/gap-analysis\?from=flow&"))
    expect(page.locator(".app-header__title")).to_have_text("Gap analysis")
    expect(page.locator("[data-back]")).to_have_text("Back to Flow")
    definition_url = page.url

    page.goto(base_url)  # the navigation remembers the stage that was open
    expect(page.locator(".sidebar a.nav-link[href^='/pipelines/']")).to_have_count(1)
    page.goto(f"{base_url}/actions")
    page.click(".sidebar a.nav-link[href^='/pipelines/']")
    expect(page).to_have_url(re.compile(rf"/pipelines/{pipeline['slug']}"))

    page.goto(definition_url)
    page.click("[data-back]")
    selected = page.locator(".ge-node--action.is-selected")
    expect(selected.locator(".ge-node__name").first).to_have_text("Gap analysis")
    expect(page).to_have_url(
        f"{base_url}/pipelines/{pipeline['slug']}"
    )  # the hint is not left in the URL


def _pass_offset(node: Locator) -> float:
    """How far the Pass port sits above (negative) or below the middle of the node."""
    port = node.locator(".ge-port--pass").bounding_box()
    box = node.bounding_box()
    assert port is not None and box is not None
    return (port["y"] + port["height"] / 2) - (box["y"] + box["height"] / 2)


def test_link_an_existing_action_switch_and_unlink(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _definition(api, "With fail", fail=True)
    _definition(api, "Without fail")
    _flow(page, base_url, api)
    node = page.locator(".ge-node--action").first
    node.locator(".ge-node__name").click()
    select = page.locator(".ge-inspector select")
    expect(select.locator("option")).to_have_count(3)  # not defined + two definitions
    select.select_option(label="With fail")
    expect(node.locator(".ge-node__name")).to_have_text("With fail")
    expect(node.locator(".ge-port--error")).to_be_visible()
    assert _pass_offset(node) < -5  # Pass above the middle, Error below it
    select.select_option(label="Without fail")
    expect(node.locator(".ge-node__name")).to_have_text("Without fail")
    expect(node.locator(".ge-port--error")).to_be_hidden()
    expect(node.locator(".ge-port--error")).to_be_hidden()
    assert abs(_pass_offset(node)) < 2  # Pass moves to the middle
    select.select_option(label="With fail")  # and back again
    expect(node.locator(".ge-port--error")).to_be_visible()
    assert _pass_offset(node) < -5
    select.select_option(label="Without fail")
    select.select_option(label="Not defined")
    expect(node.locator(".ge-node__kind")).to_have_text("Empty action")


def test_a_timer_goes_between_trigger_and_output_and_waits_for_its_seconds(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = api.post("/api/actions", json={"name": "Wait"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    page.click("[data-add-menu]")
    page.click("[data-add=timer]")
    timer = page.locator(".ge-node--timer")
    expect(timer).to_have_count(1)
    expect(timer.locator(".ge-node__kind")).to_have_text("5 s")
    page.fill(".ge-inspector input[type=number]", "12")
    page.keyboard.press("Enter")
    expect(timer.locator(".ge-node__kind")).to_have_text("12 s")
    page.click("[data-zoom-fit]")
    _drag(page, page.locator(".ge-node--trigger .ge-port--out"), timer.locator(".ge-port--in"))
    _drag(page, timer.locator(".ge-port--out"), page.locator(".ge-node--output .ge-port--pass"))
    _expect_edges(page, api, definition, [("out", "in"), ("out", "pass")])
    saved = next(n for n in _graph(api, definition)["nodes"] if n["kind"] == "timer")
    assert saved["seconds"] == 12


def test_the_new_action_dialog_validates_and_shows_server_errors(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    """The shared form dialog: required field, form error from the server, busy state, success."""
    _flow(page, base_url, api)
    page.locator(".ge-node--action").first.locator(".ge-node__name").click()
    page.click(".ge-actionbar >> text=New")
    dialog = page.locator("#new-modal")
    expect(dialog.locator("[data-submit]")).to_have_text("Create")
    expect(dialog.locator("[data-cancel]")).to_have_text("Cancel")
    dialog.locator("[data-submit]").click()
    expect(page.locator("#new-modal-field-name-error")).to_have_text("Please enter a name.")
    expect(page.locator("#new-modal-field-name")).to_have_attribute("aria-invalid", "true")

    held: list[Any] = []  # the first create request is held until the test lets it fail

    def answer(route: Any) -> None:
        if route.request.method == "POST" and not held:
            held.append(route)
        else:
            route.continue_()

    page.route(re.compile(r"/api/actions$"), answer)
    page.fill("#new-modal-field-name", "Gap analysis")
    dialog.locator("[data-submit]").click()
    expect(dialog.locator("[data-submit]")).to_have_attribute("aria-busy", "true")
    dialog.locator("[data-submit]").click(force=True)  # no double submit
    page.keyboard.press("Escape")  # closing is blocked while busy
    expect(dialog).to_be_visible()
    assert len(held) == 1
    held[0].fulfill(status=409, json={"detail": "Name is taken"})
    expect(dialog.locator("[data-form-error]")).to_have_text("Name is taken")
    expect(dialog.locator("[data-submit]")).to_have_attribute("aria-busy", "false")
    dialog.locator("[data-submit]").click()
    expect(page).to_have_url(re.compile(r"/actions/gap-analysis"))
