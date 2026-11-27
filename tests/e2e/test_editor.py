"""The pipeline list and the canvas editor."""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Locator, Page, Route, expect

from tests.e2e.helpers import (
    add_action,
    centre,
    drag,
    eventually,
    failure_setting,
    menu_kinds,
    pick_node,
)
from tests.helpers import graph_url


def _graph(api: httpx.Client, pipeline: dict[str, Any]) -> dict[str, Any]:
    return api.get(graph_url(pipeline)).json()  # type: ignore[no-any-return]


def _open(page: Page, base_url: str, pipeline: dict[str, Any]) -> None:
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    expect(page.locator(".ge-node").first).to_be_visible()


def _expect_edges(
    page: Page, api: httpx.Client, pipeline: dict[str, Any], expected: list[tuple[str, str]]
) -> None:
    """The server's edges become `expected` (changes are saved asynchronously, so this polls)."""
    eventually(lambda: _edges(api, pipeline), expected)


def _add_stage(page: Page) -> None:
    page.click("[data-add-menu]")
    pick_node(page, "stage")


def _edges(api: httpx.Client, pipeline: dict[str, Any]) -> list[tuple[str, str]]:
    return sorted((e["source_port"], e["target_port"]) for e in _graph(api, pipeline)["edges"])


# ── list ──────────────────────────────────────────────────────────────


def test_create_rename_and_delete_a_pipeline_from_the_list(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.goto(f"{base_url}/pipelines")
    expect(page.locator(".mg__empty")).to_be_visible()
    page.click("[data-new-graph]")
    page.locator("#graph-modal").get_by_label("Name").fill("Agentic Coding")
    page.click("#graph-modal [data-submit]")
    expect(page).to_have_url(f"{base_url}/pipelines/agentic-coding")  # the name, not an id
    expect(page.locator(".ge-node--trigger")).to_have_count(1)
    expect(page.locator(".ge-node--complete")).to_have_count(1)
    expect(page.locator(".ge-edge")).to_have_count(1)  # connected by default

    page.goto(f"{base_url}/pipelines")
    page.locator(".mg-card").click()  # a click selects: the panel's Properties change the name
    page.locator("[data-properties]").click()
    page.locator("#graph-modal").get_by_label("Name").fill("Renamed")
    page.click("#graph-modal [data-submit]")
    expect(page.locator(".mg-card__name")).to_have_text("Renamed")

    page.locator(".mg-card [data-delete]").click()
    page.click("#confirm-modal [data-confirm]")
    expect(page.locator(".mg-card")).to_have_count(0)
    assert api.get("/api/pipelines").json() == []


def test_pipeline_name_is_required(page: Page, base_url: str, api: httpx.Client) -> None:
    page.goto(f"{base_url}/pipelines")
    page.click("[data-new-graph]")
    page.click("#graph-modal [data-submit]")
    expect(page.locator("#graph-modal [data-error-for='name']")).to_be_visible()
    assert api.get("/api/pipelines").json() == []


# ── editor ────────────────────────────────────────────────────────────


def test_add_stage_and_actions_and_they_persist(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = api.post("/api/pipelines", json={"name": "Flow"}).json()
    _open(page, base_url, pipeline)
    _add_stage(page)
    expect(page.locator(".ge-node--stage")).to_have_count(1)
    add_action(page)
    add_action(page)
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
    # The stage's connection points follow its actions, so the line from the trigger is short when the stage sits right
    # beside it: the hover bar covers all of such a line. Put the stage further away, as the owner's pipelines have it.
    eventually(
        lambda: any(n["kind"] == "stage" for n in _graph(api, pipeline)["nodes"]), True
    )  # saved asynchronously
    stage = next(n for n in _graph(api, pipeline)["nodes"] if n["kind"] == "stage")
    api.patch(
        f"{graph_url(pipeline)}/nodes/{stage['id']}", json={"x": stage["x"] + 260}
    ).raise_for_status()
    _open(page, base_url, pipeline)
    add_action(page)
    add_action(page)
    expect(page.locator(".ge-node--action")).to_have_count(2)
    page.click("[data-zoom-fit]")  # everything on screen, so ports can be reached with the mouse
    return pipeline  # type: ignore[no-any-return]


def _error_outputs_on(
    page: Page, base_url: str, api: httpx.Client, pipeline: dict[str, Any]
) -> None:
    """Switch the error output of the actions on (it is there only with "If the action fails: Error output", ADR-061)."""
    for node in _graph(api, pipeline)["nodes"]:
        if node["kind"] == "action":
            api.patch(
                f"{graph_url(pipeline)}/nodes/{node['id']}",
                json={"config": {"on_failure": "error_output"}},
            ).raise_for_status()
    _open(page, base_url, pipeline)
    expect(page.locator(".ge-node--action")).to_have_count(2)
    page.click("[data-zoom-fit]")


def test_connect_by_dragging_between_ports(page: Page, base_url: str, api: httpx.Client) -> None:
    pipeline = _flow(page, base_url, api)
    _error_outputs_on(page, base_url, api, pipeline)
    drag(
        page,
        page.locator(".ge-node--trigger .ge-port--out"),
        page.locator(".ge-node--stage > .ge-port--start[data-slot='0']"),
    )
    drag(
        page,
        page.locator(".ge-node--stage > .ge-port--start[data-slot='0']"),
        page.locator(".ge-node--action").first.locator(".ge-port--in"),
    )
    drag(
        page,
        page.locator(".ge-node--action").first.locator(".ge-port--pass"),
        page.locator(".ge-node--action").nth(1).locator(".ge-port--in"),
    )
    drag(
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
    x, y = centre(first)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 40, y + 40, steps=4)
    valid = page.locator(".ge-port.is-valid")
    # an action may reach actions of its own stage and the end of its own stage (3 points), nothing else
    expect(valid).to_have_count(5)
    stage_in = page.locator(".ge-node--stage").nth(1).locator("> .ge-port--start[data-slot='0']")
    tx, ty = centre(stage_in)
    page.mouse.move(tx, ty, steps=6)
    page.mouse.up()
    _expect_edges(page, api, pipeline, [])
    expect(page.locator(".ge-port.is-valid")).to_have_count(0)


def test_an_output_has_one_edge_and_reconnecting_replaces_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    first = page.locator(".ge-node--action").first
    drag(
        page,
        first.locator(".ge-port--pass"),
        page.locator(".ge-node--action").nth(1).locator(".ge-port--in"),
    )
    drag(
        page,
        first.locator(".ge-port--pass"),
        page.locator(".ge-node--stage > .ge-port--end[data-slot='0']"),
    )
    expect(page.locator(".ge-edge")).to_have_count(1)
    _expect_edges(page, api, pipeline, [("pass", "end")])


def test_error_may_loop_back_to_its_own_input(page: Page, base_url: str, api: httpx.Client) -> None:
    pipeline = _flow(page, base_url, api)
    _error_outputs_on(page, base_url, api, pipeline)
    first = page.locator(".ge-node--action").first
    drag(page, first.locator(".ge-port--error"), first.locator(".ge-port--in"))
    expect(page.locator(".ge-edge")).to_have_count(1)
    _expect_edges(page, api, pipeline, [("error", "in")])


def _edge_point(page: Page, fraction: float = 0.3) -> tuple[float, float]:
    """A point on the line of the first connection, not in its middle where the bar sits.

    The line is measured once it has stopped moving (two animation frames give the same point): right after a
    connection is made the canvas may still be settling the nodes, and a point taken from a moving line misses it."""
    page.locator(".ge-edge .ge-edge__line").first.wait_for(state="attached")
    point = page.evaluate_handle(
        """(fraction) => new Promise((resolve) => {
          const measure = () => {
            const path = document.querySelector(".ge-edge .ge-edge__line");
            const at = path.getPointAtLength(path.getTotalLength() * fraction);
            const m = path.getScreenCTM();
            return [at.x * m.a + at.y * m.c + m.e, at.x * m.b + at.y * m.d + m.f];
          };
          let last = measure(), still = 0;
          const frame = () => {
            const now = measure();
            still = Math.hypot(now[0] - last[0], now[1] - last[1]) < 0.5 ? still + 1 : 0;
            last = now;
            if (still >= 3) resolve(now);
            else requestAnimationFrame(frame);
          };
          requestAnimationFrame(frame);
        })""",
        fraction,
    )
    x, y = point.json_value()
    return x, y


def _on_edge(page: Page, fraction: float = 0.3) -> None:
    page.mouse.move(*_edge_point(page, fraction))


def _select_edge(page: Page) -> None:
    """Click the first connection (beside the middle, where the bar shows on hover)."""
    page.mouse.click(*_edge_point(page))


def test_select_and_delete_an_edge(page: Page, base_url: str, api: httpx.Client) -> None:
    pipeline = _flow(page, base_url, api)
    drag(
        page,
        page.locator(".ge-node--trigger .ge-port--out"),
        page.locator(".ge-node--stage > .ge-port--start[data-slot='0']"),
    )
    _select_edge(page)
    expect(page.locator(".ge-edge.is-selected")).to_have_count(1)
    page.keyboard.press("Delete")
    expect(page.locator(".ge-edge")).to_have_count(0)
    _expect_edges(page, api, pipeline, [])


def _connect_trigger_to_stage(page: Page) -> None:
    drag(
        page,
        page.locator(".ge-node--trigger .ge-port--out"),
        page.locator(".ge-node--stage > .ge-port--start[data-slot='0']"),
    )
    expect(page.locator(".ge-edge")).to_have_count(1)


def test_delete_on_a_focused_node_does_not_also_delete_the_selected_edge(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    _connect_trigger_to_stage(page)
    _select_edge(page)
    expect(page.locator(".ge-edge.is-selected")).to_have_count(1)
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
    eventually(lambda: _graph(api, pipeline)["graph"]["name"], "Flow two")


def test_move_rename_and_delete_a_node(page: Page, base_url: str, api: httpx.Client) -> None:
    pipeline = _flow(page, base_url, api)
    action = page.locator(".ge-node--action").first
    before = next(n for n in _graph(api, pipeline)["nodes"] if n["kind"] == "action")
    x, y = centre(action.locator(".ge-node__name"))
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 60, y + 30, steps=6)
    page.mouse.up()
    expect(action).to_have_class(re.compile(r"is-selected"))
    expect(page.locator("#node-modal")).not_to_be_visible()  # a drag opens nothing

    def moved() -> bool:  # saved asynchronously
        node = next(n for n in _graph(api, pipeline)["nodes"] if n["id"] == before["id"])
        return (node["x"], node["y"]) != (before["x"], before["y"])

    eventually(moved, True)

    action.locator(".ge-node__name").dblclick()
    expect(page.locator(".ge-inspector input")).to_have_count(
        0
    )  # a shell is named by its definition
    page.keyboard.press("Escape")
    trigger = page.locator(".ge-node--trigger")
    trigger.locator(".ge-node__name").dblclick()
    page.locator(".ge-inspector h2").click()  # the name is edited in place
    name = page.locator(".ge-inspector input").first
    name.fill("Manual start")
    name.press("Enter")
    expect(trigger.locator(".ge-node__name")).to_have_text("Manual start")
    page.keyboard.press("Escape")
    action.locator(".ge-node__name").dblclick()

    page.locator(".ge-inspector .ge-delete").click()
    page.click("#confirm-modal [data-confirm]")
    expect(page.locator(".ge-node--action")).to_have_count(1)


def test_deleting_a_stage_asks_and_takes_its_actions_along(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    page.locator(".ge-stage__header").dblclick(position={"x": 80, "y": 20})
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
    drag(page, page.locator(".ge-node--trigger .ge-port--out"), ports.nth(1))
    page.mouse.move(0, 0)
    expect(ports.nth(1)).to_have_css("opacity", "1")
    expect(ports.nth(0)).to_have_css("opacity", "0")
    eventually(lambda: bool(_graph(api, pipeline)["edges"]), True)
    edge = _graph(api, pipeline)["edges"][0]
    assert (edge["target_slot"], edge["source_slot"]) == (1, 0)


# ── the toolbar of a connection (hover: a bin and a pencil) ──────────


def test_hovering_a_connection_shows_a_bin_and_a_pencil_and_leaving_hides_them(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _flow(page, base_url, api)
    _connect_trigger_to_stage(page)
    bar = page.locator(".ge-edge-bar")
    expect(bar).to_be_hidden()  # nothing hovered, nothing selected
    _on_edge(page)
    expect(bar).to_be_visible()
    expect(bar.get_by_role("button", name="Delete connection")).to_be_visible()
    expect(bar.get_by_role("button", name="Change line style")).to_be_visible()
    page.mouse.move(5, 5)
    expect(bar).to_be_hidden()


def test_the_bin_of_the_bar_deletes_the_connection(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    _connect_trigger_to_stage(page)
    _on_edge(page)
    page.get_by_role("button", name="Delete connection").click()
    expect(page.locator(".ge-edge")).to_have_count(0)
    expect(page.locator(".ge-edge-bar")).to_be_hidden()
    _expect_edges(page, api, pipeline, [])


def test_the_pencil_of_the_bar_sets_the_line_style_in_one_click_more(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    _connect_trigger_to_stage(page)
    line = page.locator(".ge-edge__line").first
    assert " C " in (line.get_attribute("d") or "")
    _on_edge(page)
    page.get_by_role("button", name="Change line style").click()
    assert (
        page.locator(".ge-edge-bar__style[data-style=curved]").get_attribute("aria-pressed")
        == "true"
    )
    page.locator(".ge-edge-bar__style[data-style=straight]").click()
    path = line.get_attribute("d") or ""
    assert " C " not in path and " Q " not in path  # straight now
    eventually(lambda: _graph(api, pipeline)["edges"][0]["style"], "straight")
    _on_edge(page)
    page.get_by_role("button", name="Change line style").click()
    page.locator(".ge-edge-bar__style[data-style=elbow]").click()
    eventually(lambda: _graph(api, pipeline)["edges"][0]["style"], "elbow")
    page.reload()
    expect(page.locator(".ge-edge")).to_have_count(1)
    assert " C " not in (page.locator(".ge-edge__line").first.get_attribute("d") or "")


def test_the_styles_open_as_a_submenu_centred_below_the_bar_and_the_bar_keeps_its_size(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _flow(page, base_url, api)
    _connect_trigger_to_stage(page)
    _on_edge(page)
    bar = page.locator(".ge-edge-bar")
    expect(bar).to_be_visible()
    closed = bar.bounding_box()
    page.get_by_role("button", name="Change line style").click()
    submenu = page.locator(".ge-edge-bar__submenu")
    expect(submenu).to_be_visible()
    opened, menu = bar.bounding_box(), page.locator(".ge-edge-bar__choices").bounding_box()
    assert closed and opened and menu
    assert (
        opened["width"] == closed["width"] and opened["height"] == closed["height"]
    )  # pencil and bin stay
    assert menu["y"] >= opened["y"] + opened["height"]  # below the bar, not beside the buttons
    assert (
        abs((menu["x"] + menu["width"] / 2) - (opened["x"] + opened["width"] / 2)) <= 2
    )  # centred
    # the pointer may travel from the bar to the submenu without it closing
    page.mouse.move(menu["x"] + menu["width"] / 2, menu["y"] + menu["height"] / 2, steps=5)
    page.wait_for_timeout(400)
    expect(submenu).to_be_visible()


def test_a_selected_connection_keeps_its_bar_so_keyboard_and_touch_can_reach_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _flow(page, base_url, api)
    _connect_trigger_to_stage(page)
    _select_edge(page)  # selects the connection
    page.mouse.move(5, 5)
    expect(page.locator(".ge-edge-bar")).to_be_visible()
    page.keyboard.press("Delete")  # the bar leaves with the connection
    expect(page.locator(".ge-edge-bar")).to_be_hidden()


# ── action definitions ────────────────────────────────────────────────


def test_create_an_action_definition_from_the_navigation(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.goto(f"{base_url}/pipelines")
    page.click(".nav-link[href='/actions']")
    expect(page).to_have_url(re.compile(r"/actions$"))
    expect(page.locator(".mg__empty")).to_be_visible()
    page.click("[data-new-graph]")
    page.locator("#graph-modal").get_by_label("Name").fill(
        "Gap analysis"
    )  # a window of the form manifest (ADR-065, ADR-067)
    page.click("#graph-modal [data-submit]")
    expect(page).to_have_url(f"{base_url}/actions/gap-analysis")
    expect(page.locator(".ge-node--trigger")).to_have_count(1)
    expect(page.locator(".ge-node--output")).to_have_count(1)
    page.click("[data-add-menu]")
    assert menu_kinds(page) == {
        "AI": ["Agent"],
        "Agent tools": [
            "MCP Client Tool",
            "GitHub MCP",
            "HTTP Request Tool",
            "Execute Command Tool",
            "Postgres Tool",
            "OpenArtifact MCP Tool",  # ADR-079
            "Hand Over Tool",  # ADR-080
        ],
        "Apps and data": ["GitHub", "Postgres"],
        "Core": ["Execute Command", "HTTP request"],
        "Data": ["Edit Fields", "Artifact", "Build Context"],  # Build Context: ADR-078
        "Flow": ["If", "Switch", "Timer"],
    }


def test_on_pass_is_always_there_and_on_fail_is_switched_on_and_off(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = api.post("/api/actions", json={"name": "Check"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    output = page.locator(".ge-node--output")
    expect(output.locator(".ge-port--pass")).to_be_visible()  # a connector of its own
    expect(output.locator(".ge-port--fail")).to_be_hidden()
    output.locator(".ge-node__name").dblclick()
    page.locator(".ge-switch").click()
    page.keyboard.press("Escape")
    expect(output.locator(".ge-port--fail")).to_be_visible()
    eventually(
        lambda: next(n for n in _graph(api, definition)["nodes"] if n["kind"] == "output")[
            "fail_enabled"
        ],
        True,
    )
    page.reload()
    expect(page.locator(".ge-node--output .ge-port--fail")).to_be_visible()
    page.locator(".ge-node--output .ge-node__name").dblclick()
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
    page.locator(".ge-node--output .ge-node__name").dblclick()
    page.locator(".ge-switch").click()
    page.keyboard.press("Escape")
    drag(
        page,
        page.locator(".ge-node--trigger .ge-port--out"),
        page.locator(".ge-node--output .ge-port--fail"),
    )
    _expect_edges(page, api, definition, [("out", "fail")])
    page.locator(".ge-node--output .ge-node__name").dblclick()
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
    assert menu_kinds(page) == {"Structure": ["Stage", "Pipeline"]}
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    for kind in ("trigger", "complete"):
        page.locator(f".ge-node--{kind} .ge-node__name").dblclick()
        expect(page.locator(".ge-inspector .ge-delete")).to_have_count(0)
        page.keyboard.press("Escape")
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

    def room() -> bool:
        nodes = {n["kind"]: n for n in _graph(api, pipeline)["nodes"]}
        return bool(nodes["complete"]["x"] >= nodes["stage"]["x"] + nodes["stage"]["width"])

    eventually(room, True)


# ── linking an action shell to an action definition ───────────────────


def _definition(api: httpx.Client, name: str, fail: bool = False) -> dict[str, Any]:
    definition = api.post("/api/actions", json={"name": name}).json()
    if fail:
        output = next(n for n in _graph(api, definition)["nodes"] if n["kind"] == "output")
        api.patch(f"{graph_url(definition)}/nodes/{output['id']}", json={"fail_enabled": True})
    return definition  # type: ignore[no-any-return]


def _give_the_actions_a_definition(api: httpx.Client, pipeline: dict[str, Any]) -> None:
    definition = _definition(api, "Gap analysis")
    for node in _graph(api, pipeline)["nodes"]:
        if node["kind"] == "action":  # both shells use it, so the first one in the page does too
            api.patch(
                f"{graph_url(pipeline)}/nodes/{node['id']}",
                json={"definition_id": definition["id"]},
            )


def test_a_double_click_on_an_action_without_a_definition_opens_its_settings(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _flow(page, base_url, api)
    page.locator(".ge-node--action").first.locator(".ge-node__name").dblclick()
    expect(
        page.locator("#node-modal")
    ).to_be_visible()  # nothing to open yet: choose or create one here
    expect(page).to_have_url(f"{base_url}/pipelines/flow")
    expect(page.locator(".ge-actionbar a")).to_have_attribute("aria-disabled", "true")


def test_a_double_click_on_an_action_opens_the_action_itself(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    _give_the_actions_a_definition(api, pipeline)
    page.reload()
    page.locator(".ge-node--action").first.locator(".ge-node__name").dblclick()
    expect(page).to_have_url(re.compile(r"/actions/gap-analysis\?from=flow&"))
    expect(page.locator("[data-back]")).to_have_text("Back to Flow")


def test_the_menu_edit_and_enter_open_the_action_like_a_double_click(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    _give_the_actions_a_definition(api, pipeline)
    page.reload()
    action = page.locator(".ge-node--action").first
    action.click(button="right", position={"x": 30, "y": 5})
    page.get_by_role("menuitem", name="Edit").click()
    expect(page).to_have_url(re.compile(r"/actions/gap-analysis\?from=flow&"))
    page.go_back()
    action = page.locator(".ge-node--action").first
    action.focus()
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"/actions/gap-analysis\?from=flow&"))


def test_the_settings_of_an_action_stay_one_menu_entry_away(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    """The double click no longer opens them: the menu's Settings does (which definition, New, Edit, Delete)."""
    pipeline = _flow(page, base_url, api)
    _give_the_actions_a_definition(api, pipeline)
    page.reload()
    action = page.locator(".ge-node--action").first
    action.click(button="right", position={"x": 30, "y": 5})
    page.get_by_role("menuitem", name="Settings").click()
    expect(page.locator("#node-modal")).to_be_visible()
    expect(page).to_have_url(f"{base_url}/pipelines/flow")
    expect(page.locator(".ge-actionbar a", has_text="Edit")).to_have_attribute(
        "href", re.compile(r"/actions/gap-analysis")
    )


def test_a_double_click_on_a_kind_that_does_not_link_still_opens_its_settings(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    _give_the_actions_a_definition(api, pipeline)
    page.reload()
    page.locator(".ge-node--trigger .ge-node__name").dblclick()
    expect(page.locator("#node-modal")).to_be_visible()
    expect(page).to_have_url(f"{base_url}/pipelines/flow")


def test_the_style_choices_of_a_connection_are_pictograms_named_by_their_tooltip(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _flow(page, base_url, api)
    _connect_trigger_to_stage(page)
    _on_edge(page)
    page.get_by_role("button", name="Change line style").click()
    for value, name in (("curved", "Curved"), ("straight", "Straight"), ("elbow", "Elbow")):
        choice = page.locator(f".ge-edge-bar__style[data-style={value}]")
        expect(choice).to_have_attribute("title", name)  # the tooltip names it
        expect(choice).to_have_attribute("aria-label", name)
        expect(choice.locator("svg")).to_have_count(1)  # a pictogram
        expect(choice).to_have_text("")  # no words on the button


def test_a_new_action_is_defined_in_actions_and_selected_again_on_return(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)
    shell = page.locator(".ge-node--action").first
    shell.locator(".ge-node__name").dblclick()
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


def _linked_name(api: httpx.Client, pipeline: dict[str, Any]) -> str | None:
    action = next(n for n in _graph(api, pipeline)["nodes"] if n["kind"] == "action")
    name: str | None = action["definition_name"]
    return name


def test_link_an_existing_action_switch_and_unlink(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _definition(api, "With fail", fail=True)
    _definition(api, "Without fail")
    pipeline = _flow(page, base_url, api)
    node = page.locator(".ge-node--action").first
    node.locator(".ge-node__name").dblclick()
    select = page.locator(
        ".ge-inspector select[data-focus-key='link']"
    )  # the choice of the definition, not the setting
    expect(select.locator("option")).to_have_count(3)  # not defined + two definitions

    def choose(label: str) -> None:
        """Select an entry and wait until screen and server both show it."""
        select.select_option(label=label)
        eventually(lambda: _linked_name(api, pipeline), None if label == "Not defined" else label)

    choose("With fail")
    expect(node.locator(".ge-node__name")).to_have_text("With fail")
    # the error output comes from the action's own setting, not from its definition (ADR-061)
    expect(node.locator(".ge-port--error")).to_be_hidden()
    assert abs(_pass_offset(node)) < 2
    failure_setting(page, "If the action fails").select_option(label="Error output")
    expect(node.locator(".ge-port--error")).to_be_visible()
    assert _pass_offset(node) < -5  # Pass above the middle, Error below it
    choose("Without fail")
    expect(node.locator(".ge-node__name")).to_have_text("Without fail")
    expect(
        node.locator(".ge-port--error")
    ).to_be_visible()  # another definition does not take it away
    assert _pass_offset(node) < -5
    choose("With fail")  # and back again
    expect(node.locator(".ge-port--error")).to_be_visible()
    choose("Without fail")
    choose("Not defined")
    expect(node.locator(".ge-node__kind")).to_have_text("Empty action")


def test_two_quick_link_changes_end_with_server_and_screen_in_agreement(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _definition(api, "With fail", fail=True)
    pipeline = _flow(page, base_url, api)
    node = page.locator(".ge-node--action").first
    node.locator(".ge-node__name").dblclick()
    select = page.locator(
        ".ge-inspector select[data-focus-key='link']"
    )  # the choice of the definition, not the setting
    expect(select.locator("option")).to_have_count(2)
    armed = [False]

    def slow_first_answer(route: Route) -> None:
        """The answer to the first change arrives late, as on a slow connection."""
        response = route.fetch()
        if armed[0]:
            armed[0] = False
            page.wait_for_timeout(300)  # lets the second request overtake it, if it may
        route.fulfill(response=response)

    page.route(
        lambda url: "/nodes/" in url,
        lambda r: slow_first_answer(r) if r.request.method == "PATCH" else r.continue_(),
    )
    for _ in range(5):
        armed[0] = True
        # both changes happen in one browser task, before any answer can arrive
        select.evaluate(
            """(el) => {
                for (const label of ["With fail", "Not defined"]) {
                    el.value = [...el.options].find((o) => o.textContent === label).value;
                    el.dispatchEvent(new Event("change", { bubbles: true }));
                }
            }"""
        )
        # the screen is checked first: waiting on it also lets the delayed answer through
        expect(node.locator(".ge-node__kind")).to_have_text("Empty action")
        eventually(lambda: _linked_name(api, pipeline), None, page=page)
        select.select_option(label="With fail")
        expect(node.locator(".ge-node__name")).to_have_text("With fail")
        eventually(lambda: _linked_name(api, pipeline), "With fail", page=page)
        select.select_option(label="Not defined")
        expect(node.locator(".ge-node__kind")).to_have_text("Empty action")
        eventually(lambda: _linked_name(api, pipeline), None, page=page)
    page.unroute_all(behavior="ignoreErrors")  # no handler may still run when the page closes


def test_a_timer_goes_between_trigger_and_output_and_waits_for_its_seconds(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = api.post("/api/actions", json={"name": "Wait"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    page.click("[data-add-menu]")
    pick_node(page, "timer")
    timer = page.locator(".ge-node--timer")
    expect(timer).to_have_count(1)
    expect(timer.locator(".ge-node__kind")).to_have_text("5 s")
    timer.dblclick(position={"x": 30, "y": 5})
    page.fill(".ge-inspector input[type=number]", "12")
    page.keyboard.press("Enter")
    expect(timer.locator(".ge-node__kind")).to_have_text("12 s")
    page.keyboard.press("Escape")
    page.click("[data-zoom-fit]")
    drag(page, page.locator(".ge-node--trigger .ge-port--out"), timer.locator(".ge-port--in"))
    drag(page, timer.locator(".ge-port--out"), page.locator(".ge-node--output .ge-port--pass"))
    _expect_edges(page, api, definition, [("out", "in"), ("out", "pass")])
    saved = next(n for n in _graph(api, definition)["nodes"] if n["kind"] == "timer")
    assert saved["seconds"] == 12


def test_the_new_action_dialog_validates_and_shows_server_errors(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    """The shared form dialog: required field, form error from the server, busy state, success."""
    _flow(page, base_url, api)
    page.locator(".ge-node--action").first.locator(".ge-node__name").dblclick()
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


def test_a_stage_is_duplicated_with_its_actions_and_pasted_into_another_pipeline(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _flow(page, base_url, api)  # one stage, two actions
    stage = page.locator(".ge-node--stage")
    stage.locator(".ge-stage__header").click(position={"x": 80, "y": 20})
    page.keyboard.press("Control+d")
    expect(page.locator(".ge-node--stage")).to_have_count(2)
    expect(page.locator(".ge-node--action")).to_have_count(4)  # the actions went along
    eventually(lambda: sorted(n["kind"] for n in _graph(api, pipeline)["nodes"]).count("action"), 4)
    names = [n["name"] for n in _graph(api, pipeline)["nodes"] if n["kind"] == "stage"]
    assert len(set(names)) == 2 and any(name.endswith(" copy") for name in names), names

    page.keyboard.press("Control+c")  # a duplicate does not use the clipboard; a copy does
    other = api.post("/api/pipelines", json={"name": "Other"}).json()
    _open(page, base_url, other)  # another pipeline: the clipboard is shared
    page.keyboard.press("Control+v")
    expect(page.locator(".ge-node--stage")).to_have_count(1)
    expect(page.locator(".ge-node--action")).to_have_count(2)
