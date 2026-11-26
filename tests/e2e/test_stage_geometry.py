"""Straight lines in the pipeline editor: the attachment points of a stage follow the stage's height (the top one is level
with an action at the very top, the bottom one with an action at the very bottom), a dragged node settles level with a
connected port or a point of its stage (Alt switches that off), and a stage has grips to make it larger or smaller
(never smaller than its actions need)."""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import (
    add_action,
    centre,
    eventually,
    execution_of,
    flow_url,
    run_started,
    two_stage_pipeline,
)
from tests.helpers import build_definition, connect, graph_url, make_task, node, post

STAGE_SIZE = {"width": 500, "height": 360}
# the least a stage measures: its actions plus the band between its outer and inner border (STAGE_MARGIN = 56) on the right
# and below (the right edge of an action at 100 + 190, the lower one ends at 44 + 170 + 68)
BAND = 56
DETOUR = 28  # how far a loop back keeps below the lowest action
ACTION_WIDTH, ACTION_HEIGHT, HEADER = 190, 68, 44
MIN_WIDTH, MIN_HEIGHT = 100 + ACTION_WIDTH + BAND, HEADER + 170 + ACTION_HEIGHT + BAND
# An action's ports sit inside its 1px border, a stage's inside the stage's: the drawn lines use the model and are exact,
# the dots measured in the page differ by that border.
BORDER = 1.5


def _pipeline(client: httpx.Client, upper_y: int = 12) -> dict[str, Any]:
    """Trigger -> a stage with two actions (one above the other, the first feeding the second)."""
    pipeline: dict[str, Any] = client.post("/api/pipelines", json={"name": "Straight"}).json()
    stage = node(client, pipeline, "stage", name="Gap", x=200, y=40)
    client.patch(f"{graph_url(pipeline)}/nodes/{stage['id']}", json=STAGE_SIZE).raise_for_status()
    upper = node(
        client, pipeline, "action", stage_id=stage["id"], x=100, y=upper_y
    )  # 12 is the highest row
    lower = node(client, pipeline, "action", stage_id=stage["id"], x=100, y=170)
    connect(client, pipeline, stage, "start", upper, "in")
    connect(client, pipeline, upper, "pass", lower, "in")
    pipeline["stage"], pipeline["upper"], pipeline["lower"] = stage, upper, lower
    return pipeline


def _open(page: Page, base_url: str, pipeline: dict[str, Any]) -> None:
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    expect(page.locator(".ge-node--action")).to_have_count(2)
    page.click("[data-zoom-fit]")


def _action(page: Page, node_id: str) -> Locator:
    return page.locator(f'.ge-node--action[data-node-id="{node_id}"]')


def _stage_port(page: Page, slot: int, side: str = "start") -> Locator:
    return page.locator(f".ge-node--stage > .ge-port--{side}[data-slot='{slot}']")


def _y(locator: Locator) -> float:
    return centre(locator)[1]


def _stored(api: httpx.Client, pipeline: dict[str, Any], node_id: str) -> dict[str, Any]:
    nodes = api.get(graph_url(pipeline)).json()["nodes"]
    return next(n for n in nodes if n["id"] == node_id)


def _grip(page: Page, side: str) -> Locator:
    return page.locator(f".ge-node--stage .ge-resize--{side}")


def _drag_by(page: Page, grip: Locator, dx: float, dy: float) -> None:
    x, y = centre(grip)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=12)
    page.mouse.up()


# ── the attachment points of a stage ────────────────────────────────


def test_the_top_point_is_level_with_the_first_row_and_does_not_follow_the_actions(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _open(page, base_url, pipeline)
    upper, lower = _action(page, pipeline["upper"]["id"]), _action(page, pipeline["lower"]["id"])
    top, middle, bottom = (_y(_stage_port(page, slot)) for slot in range(3))
    assert abs(top - _y(upper.locator(".ge-port--in"))) <= BORDER, (
        "the top point is level with an action in the highest row"
    )
    assert abs(bottom - _y(lower.locator(".ge-port--in"))) > 20, (
        "the bottom point is not tied to the lowest action: this one sits higher than the bottom"
    )
    assert abs(middle - (top + bottom) / 2) < 0.6, "the middle point is halfway between them"
    # on the right the stage's points face the actions' On Pass
    assert abs(_y(_stage_port(page, 0, "end")) - _y(upper.locator(".ge-port--pass"))) <= BORDER


def test_the_top_point_is_level_with_an_action_at_the_very_top(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    """The highest an action can sit (what the drag clamp allows) is the height of the stage's top point.

    The owner had put his first action as high as it goes: its input was 36 px above the stage's top point, so no
    straight line was possible there. The middle point is halfway between the top and the bottom one.
    """
    pipeline: dict[str, Any] = api.post("/api/pipelines", json={"name": "Very top"}).json()
    stage = node(api, pipeline, "stage", name="Gap", x=200, y=40)
    api.patch(f"{graph_url(pipeline)}/nodes/{stage['id']}", json=STAGE_SIZE).raise_for_status()
    first = node(
        api, pipeline, "action", stage_id=stage["id"], x=100, y=48
    )  # lower than the highest row
    connect(api, pipeline, stage, "start", first, "in")
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    expect(page.locator(".ge-node--action")).to_have_count(1)
    page.click("[data-zoom-fit]")
    action = _action(page, first["id"])
    x, y = centre(action.locator(".ge-node__name"))
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x, y - 200, steps=12)  # far above what the stage allows
    page.mouse.up()
    top, middle, bottom = (_y(_stage_port(page, slot)) for slot in range(3))
    port = _y(action.locator(".ge-port--in"))
    assert abs(port - top) <= BORDER, (
        f"input {port:.1f} vs top point {top:.1f}: {port - top:+.1f} px"
    )
    assert abs(middle - (top + bottom) / 2) < 0.6, (top, middle, bottom)


def test_a_line_from_a_stage_point_to_an_action_is_horizontal(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _open(page, base_url, pipeline)
    d = page.locator(".ge-edge--start .ge-edge__line").get_attribute("d")
    assert d is not None
    numbers = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", d)]
    assert d.startswith("M") and "Q" not in d, f"a straight run, not a detour: {d}"
    assert abs(numbers[1] - numbers[-1]) < 0.01, f"the line starts and ends at one height: {d}"
    assert numbers[-2] > numbers[0], "and runs to the right"


def test_moving_an_action_does_not_move_the_points_of_its_stage(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _open(page, base_url, pipeline)
    lower = _action(page, pipeline["lower"]["id"])
    before = [_y(_stage_port(page, slot)) for slot in range(3)]
    x, y = centre(lower.locator(".ge-node__name"))
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x, y - 40, steps=10)
    page.mouse.up()
    after = [_y(_stage_port(page, slot)) for slot in range(3)]
    assert all(abs(a - b) < 0.6 for a, b in zip(after, before, strict=True)), (before, after)


def test_an_action_dragged_to_the_very_bottom_settles_level_with_the_bottom_point(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    """A straight line from the lowest point of the stage to an action at the very bottom must be possible."""
    pipeline = _pipeline(api)
    stage, lower = pipeline["stage"], pipeline["lower"]
    edge = post(
        api,
        f"{graph_url(pipeline)}/edges",
        source_id=stage["id"],
        source_port="start",
        source_slot=2,
        target_id=lower["id"],
        target_port="in",
    )
    _open(page, base_url, pipeline)
    action = _action(page, lower["id"])
    bottom = _y(_stage_port(page, 2))
    x, y = centre(action.locator(".ge-node__name"))
    offset = (
        bottom - 5 - _y(action.locator(".ge-port--in"))
    )  # dropped 5 px short of the bottom point
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x, y + offset, steps=12)
    assert page.locator(".ge-guide").count() == 1, "the guide shows that it settles"
    page.mouse.up()
    assert abs(_y(action.locator(".ge-port--in")) - bottom) <= BORDER, (
        "level, and the stage did not grow"
    )
    assert abs(_y(_stage_port(page, 2)) - bottom) < 0.6
    line = page.locator(f'[data-edge-id="{edge["id"]}"] .ge-edge__line').get_attribute("d")
    numbers = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", line or "")]
    assert line and "Q" not in line and abs(numbers[1] - numbers[-1]) < 0.01, f"horizontal: {line}"


def test_the_points_follow_a_resized_stage_at_once(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _open(page, base_url, pipeline)
    stage = page.locator(".ge-node--stage")
    box = stage.bounding_box()
    assert box
    from_top = [_y(_stage_port(page, slot)) - box["y"] for slot in (0, 1)]
    to_bottom = box["y"] + box["height"] - _y(_stage_port(page, 2))
    _drag_by(page, _grip(page, "s"), 0, 60)
    grown = stage.bounding_box()
    assert grown and grown["height"] > box["height"] + 30
    assert abs(_y(_stage_port(page, 0)) - grown["y"] - from_top[0]) < 0.6, "the top point stays"
    assert abs(grown["y"] + grown["height"] - _y(_stage_port(page, 2)) - to_bottom) < 0.6, (
        "the bottom point keeps its distance from the bottom edge"
    )
    assert _y(_stage_port(page, 1)) - grown["y"] > from_top[1] + 10, "the middle one moved down"
    top, middle, bottom = (_y(_stage_port(page, slot)) for slot in range(3))
    assert abs(middle - (top + bottom) / 2) < 0.6, (
        "and stays halfway between the top and the bottom one"
    )


def test_the_first_action_of_an_empty_stage_is_level_with_the_top_point(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline: dict[str, Any] = api.post("/api/pipelines", json={"name": "First row"}).json()
    node(api, pipeline, "stage", name="Empty", x=200, y=40)
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    expect(page.locator(".ge-node--stage")).to_have_count(1)
    add_action(page)
    expect(page.locator(".ge-node--action")).to_have_count(1)
    page.click("[data-zoom-fit]")
    new = page.locator(".ge-node--action .ge-port--in")
    assert abs(_y(new) - _y(_stage_port(page, 0))) <= BORDER


# ── settling level while dragging ───────────────────────────────────


def _drag_lower_near_the_upper_pass(
    page: Page, pipeline: dict[str, Any], *, alt: bool
) -> tuple[float, float]:
    """Drag the lower action so that its input ends 5 px away from the upper action's On Pass; return the two heights."""
    upper, lower = _action(page, pipeline["upper"]["id"]), _action(page, pipeline["lower"]["id"])
    target = _y(upper.locator(".ge-port--pass"))
    x, y = centre(lower.locator(".ge-node__name"))
    offset = target + 5 - _y(lower.locator(".ge-port--in"))
    if alt:
        page.keyboard.down("Alt")
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x, y + offset, steps=12)
    guides = page.locator(".ge-guide").count()
    page.mouse.up()
    if alt:
        page.keyboard.up("Alt")
    assert guides == (0 if alt else 1), "the guide shows while it settles, and not with Alt"
    return _y(lower.locator(".ge-port--in")), target


def test_a_dragged_node_settles_level_with_a_connected_port(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(
        api, upper_y=60
    )  # its On Pass lies below the highest row, so the lower input can reach it
    _open(page, base_url, pipeline)
    own, target = _drag_lower_near_the_upper_pass(page, pipeline, alt=False)
    assert abs(own - target) < 0.6, f"level after the drag: {own} against {target}"
    expect(page.locator(".ge-guide")).to_have_count(
        0
    )  # the guide is gone when the pointer is released


def test_alt_switches_the_settling_off(page: Page, base_url: str, api: httpx.Client) -> None:
    pipeline = _pipeline(
        api, upper_y=60
    )  # its On Pass lies below the highest row, so the lower input can reach it
    _open(page, base_url, pipeline)
    own, target = _drag_lower_near_the_upper_pass(page, pipeline, alt=True)
    assert 3 < abs(own - target) < 8, (
        f"left where it was dropped, 5 px away: {own} against {target}"
    )


# ── resizing a stage ────────────────────────────────────────────────


def test_the_grips_make_a_stage_larger_and_smaller_but_not_smaller_than_its_actions(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    stage_id = pipeline["stage"]["id"]
    _open(page, base_url, pipeline)
    page.locator(".ge-node--stage .ge-stage__header").click()  # select it: the grips show
    _drag_by(page, _grip(page, "se"), 120, 80)
    eventually(lambda: _stored(api, pipeline, stage_id)["width"] > STAGE_SIZE["width"], True)
    assert _stored(api, pipeline, stage_id)["height"] > STAGE_SIZE["height"]
    _drag_by(page, _grip(page, "se"), -2000, -2000)  # far beyond what is possible
    eventually(
        lambda: (
            _stored(api, pipeline, stage_id)["width"],
            _stored(api, pipeline, stage_id)["height"],
        ),
        (MIN_WIDTH, MIN_HEIGHT),
    )


def test_the_right_grip_changes_the_width_and_the_bottom_grip_the_height(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    stage_id = pipeline["stage"]["id"]
    _open(page, base_url, pipeline)
    page.locator(".ge-node--stage .ge-stage__header").click()
    _drag_by(page, _grip(page, "e"), 60, 90)  # the vertical part of the drag is ignored
    eventually(lambda: _stored(api, pipeline, stage_id)["width"] > STAGE_SIZE["width"], True)
    assert _stored(api, pipeline, stage_id)["height"] == STAGE_SIZE["height"]
    width = _stored(api, pipeline, stage_id)["width"]
    _drag_by(page, _grip(page, "s"), 70, -40)  # the horizontal part is ignored
    eventually(lambda: _stored(api, pipeline, stage_id)["height"] < STAGE_SIZE["height"], True)
    assert _stored(api, pipeline, stage_id)["width"] == width


def test_a_double_click_on_a_grip_fits_the_stage_to_its_actions(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    stage_id = pipeline["stage"]["id"]
    _open(page, base_url, pipeline)
    page.locator(".ge-node--stage .ge-stage__header").click()
    x, y = centre(_grip(page, "se"))
    page.mouse.dblclick(x, y)
    eventually(
        lambda: (
            _stored(api, pipeline, stage_id)["width"],
            _stored(api, pipeline, stage_id)["height"],
        ),
        (MIN_WIDTH, MIN_HEIGHT),
    )
    expect(page.locator(".ge-dialog, [role=dialog]:visible")).to_have_count(
        0
    )  # it did not open the settings


def test_a_resized_stage_keeps_its_size_after_a_reload(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    stage_id = pipeline["stage"]["id"]
    _open(page, base_url, pipeline)
    page.locator(".ge-node--stage .ge-stage__header").click()
    _drag_by(page, _grip(page, "se"), 100, 60)
    eventually(lambda: _stored(api, pipeline, stage_id)["width"] > STAGE_SIZE["width"], True)
    saved = _stored(api, pipeline, stage_id)
    page.reload()
    expect(page.locator(".ge-node--stage")).to_be_visible()
    style = page.locator(".ge-node--stage").evaluate("el => [el.style.width, el.style.height]")
    assert style == [f"{int(saved['width'])}px", f"{int(saved['height'])}px"]


def test_a_grip_is_reached_with_the_keyboard(page: Page, base_url: str, api: httpx.Client) -> None:
    pipeline = _pipeline(api)
    stage_id = pipeline["stage"]["id"]
    _open(page, base_url, pipeline)
    _grip(page, "e").focus()
    page.keyboard.press("ArrowRight")
    eventually(lambda: _stored(api, pipeline, stage_id)["width"], STAGE_SIZE["width"] + 10)
    page.keyboard.press("Shift+ArrowRight")
    eventually(lambda: _stored(api, pipeline, stage_id)["width"], STAGE_SIZE["width"] + 50)
    assert _stored(api, pipeline, stage_id)["x"] == 200, "the arrow keys did not move the stage"
    page.keyboard.press("Enter")  # fit to the actions
    eventually(lambda: _stored(api, pipeline, stage_id)["width"], MIN_WIDTH)


def test_the_flow_of_an_execution_has_no_grips(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = two_stage_pipeline(api)
    task = make_task(api, "Straight")
    run_started(api, task, pipeline)
    page.goto(flow_url(base_url, task, execution_of(api, task)))
    expect(page.locator(".ge-node--stage").first).to_be_visible()
    assert page.locator(".ge-resize").count() == 0


def test_the_corner_grip_shows_diagonal_strokes_and_keeps_its_hit_area(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _open(page, base_url, pipeline)
    page.locator(".ge-node--stage").click(position={"x": 200, "y": 20})  # select: the grips show
    grip = _grip(page, "se")
    expect(grip).to_have_attribute("aria-label", "Resize stage")
    glyph = grip.locator("svg.icon")
    expect(glyph).to_have_count(1)
    assert glyph.locator("path").count() == 3, "three diagonal strokes"
    box = grip.bounding_box()
    assert box and box["width"] >= 24 and box["height"] >= 24, "the hit area stays at least 24 px"
    # the dot is gone: the corner draws nothing but the glyph
    after = grip.evaluate("el => getComputedStyle(el, '::after').display")
    assert after == "none"
    # and the right and bottom grips are still the quiet bars
    assert _grip(page, "e").evaluate("el => getComputedStyle(el, '::after').display") != "none"


# ── one band between the outer and the inner border, on all four sides ───


def _drag_action_by(page: Page, action: Locator, dx: float, dy: float) -> None:
    x, y = centre(action.locator(".ge-node__name"))
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=12)
    page.mouse.up()


def test_an_action_stops_at_the_inner_border_on_the_left_and_at_the_top(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    """The inner border is the band's width from the stage's edge: the top one has always been 56 px (the header and the
    first row), now the left one is the same instead of 12 px."""
    pipeline = _pipeline(api)
    upper_id = pipeline["upper"]["id"]
    _open(page, base_url, pipeline)
    _drag_action_by(page, _action(page, upper_id), -3000, -3000)
    eventually(
        lambda: (_stored(api, pipeline, upper_id)["x"], _stored(api, pipeline, upper_id)["y"]),
        (BAND, 12),
    )


def test_the_stage_grows_with_an_action_dragged_right_and_down_and_keeps_the_band(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    lower_id, stage_id = pipeline["lower"]["id"], pipeline["stage"]["id"]
    _open(page, base_url, pipeline)
    _drag_action_by(page, _action(page, lower_id), 3000, 3000)
    eventually(lambda: _stored(api, pipeline, stage_id)["width"] > STAGE_SIZE["width"], True)
    lower, stage = _stored(api, pipeline, lower_id), _stored(api, pipeline, stage_id)
    assert stage["width"] - (lower["x"] + ACTION_WIDTH) == BAND, (
        "right: the outer border stays a band away"
    )
    assert stage["height"] - (HEADER + lower["y"] + ACTION_HEIGHT) == BAND, "below: likewise"


def test_both_grips_stop_one_band_from_the_actions(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    stage_id = pipeline["stage"]["id"]
    _open(page, base_url, pipeline)
    page.locator(".ge-node--stage .ge-stage__header").click()
    _drag_by(page, _grip(page, "e"), -3000, 0)
    _drag_by(page, _grip(page, "s"), 0, -3000)
    eventually(
        lambda: (
            _stored(api, pipeline, stage_id)["width"],
            _stored(api, pipeline, stage_id)["height"],
        ),
        (MIN_WIDTH, MIN_HEIGHT),
    )
    stage = _stored(api, pipeline, stage_id)
    right = max(
        _stored(api, pipeline, a["id"])["x"] + ACTION_WIDTH
        for a in (pipeline["upper"], pipeline["lower"])
    )
    bottom = max(
        HEADER + _stored(api, pipeline, a["id"])["y"] + ACTION_HEIGHT
        for a in (pipeline["upper"], pipeline["lower"])
    )
    assert stage["width"] - right == stage["height"] - bottom == BAND, (
        "the same band on the right and below"
    )


def test_the_inner_border_is_a_limit_and_is_not_drawn_while_an_action_or_a_grip_is_dragged(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    """The owner does not want to see the inner border: it only limits the actions."""
    pipeline = _pipeline(api)
    _open(page, base_url, pipeline)
    inner = page.locator(".ge-node--stage .ge-stage__inner, .ge-node--stage.is-guiding")
    expect(inner).to_have_count(0)
    action = _action(page, pipeline["upper"]["id"])
    x, y = centre(action.locator(".ge-node__name"))
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 20, y + 20, steps=6)
    expect(inner, "nothing of the inner border shows while an action is dragged").to_have_count(0)
    page.mouse.up()
    grip = page.locator(".ge-node--stage .ge-resize--se")
    gx, gy = centre(grip)
    page.mouse.move(gx, gy)
    page.mouse.down()
    page.mouse.move(gx + 30, gy + 30, steps=6)
    expect(inner, "nor while a grip is dragged").to_have_count(0)
    page.mouse.up()


def test_a_loop_back_inside_a_stage_runs_in_the_band_between_the_borders(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    """On Error of the lower action goes back to the first one: the line leaves to the right, runs below both and comes in
    from the left, and all of it lies between the stage's outer border and the actions."""
    pipeline: dict[str, Any] = api.post("/api/pipelines", json={"name": "Loop"}).json()
    stage = node(api, pipeline, "stage", name="Gap", x=200, y=40)
    api.patch(
        f"{graph_url(pipeline)}/nodes/{stage['id']}",
        json={"width": MIN_WIDTH, "height": MIN_HEIGHT},
    )
    upper = node(api, pipeline, "action", stage_id=stage["id"], x=100, y=12)
    definition = build_definition(
        api, "Fails", output=None, fail_enabled=True
    )  # an action with an On Error output
    lower = node(api, pipeline, "action", stage_id=stage["id"], x=100, y=170)
    api.patch(
        f"{graph_url(pipeline)}/nodes/{lower['id']}", json={"definition_id": definition["id"]}
    ).raise_for_status()
    connect(api, pipeline, stage, "start", upper, "in")
    connect(api, pipeline, upper, "pass", lower, "in")
    connect(api, pipeline, lower, "error", upper, "in")
    _open(page, base_url, pipeline)
    # the first action as far left as it goes: the line that comes in from its left has to find room in the band
    _drag_action_by(page, _action(page, upper["id"]), -3000, 0)
    eventually(lambda: _stored(api, pipeline, upper["id"])["x"], BAND)
    loop = page.locator(".ge-edge--error .ge-edge__line")
    expect(loop).to_have_count(1)
    path, frame = loop.bounding_box(), page.locator(".ge-node--stage").bounding_box()
    lowest = max(
        _action(page, a["id"]).bounding_box()["y"] + _action(page, a["id"]).bounding_box()["height"]  # type: ignore[index]
        for a in (upper, lower)
    )
    assert path and frame
    assert path["y"] + path["height"] > lowest, "it runs below the lowest action"
    assert path["y"] + path["height"] < frame["y"] + frame["height"] - 2, (
        "and stays inside the outer border"
    )
    scale = frame["height"] / MIN_HEIGHT  # the page is zoomed to fit: model units to pixels
    assert abs((path["y"] + path["height"]) - lowest - DETOUR * scale) < 4 * scale, (
        f"its lowest run is DETOUR below the lowest action: {(path['y'] + path['height']) - lowest}"
    )
    assert path["x"] > frame["x"] + 2, "also on the left"
    assert path["x"] + path["width"] < frame["x"] + frame["width"] - 2, "and on the right"


def test_a_loop_back_in_a_taller_stage_runs_right_below_the_nodes_not_at_the_stage_bottom(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline: dict[str, Any] = api.post("/api/pipelines", json={"name": "Tall loop"}).json()
    stage = node(api, pipeline, "stage", name="Gap", x=200, y=40)
    height = MIN_HEIGHT + 120
    api.patch(
        f"{graph_url(pipeline)}/nodes/{stage['id']}", json={"width": MIN_WIDTH, "height": height}
    )
    upper = node(api, pipeline, "action", stage_id=stage["id"], x=100, y=12)
    definition = build_definition(api, "Fails", output=None, fail_enabled=True)
    lower = node(api, pipeline, "action", stage_id=stage["id"], x=100, y=170)
    api.patch(
        f"{graph_url(pipeline)}/nodes/{lower['id']}", json={"definition_id": definition["id"]}
    ).raise_for_status()
    connect(api, pipeline, stage, "start", upper, "in")
    connect(api, pipeline, upper, "pass", lower, "in")
    connect(api, pipeline, lower, "error", upper, "in")
    _open(page, base_url, pipeline)
    path = page.locator(".ge-edge--error .ge-edge__line").bounding_box()
    frame = page.locator(".ge-node--stage").bounding_box()
    assert path and frame
    scale = frame["height"] / height  # the page is zoomed to fit: model units to pixels
    lowest = max(
        _action(page, a["id"]).bounding_box()["y"] + _action(page, a["id"]).bounding_box()["height"]  # type: ignore[index]
        for a in (upper, lower)
    )
    run = path["y"] + path["height"]
    assert abs(run - lowest - DETOUR * scale) < 4 * scale, (
        f"the lowest run is DETOUR below the lowest action, as before the borders: {run - lowest}"
    )
    assert frame["y"] + frame["height"] - run > BAND * scale, (
        "and it does not drop to the stage's bottom: it stays well above the inner border's bottom"
    )
