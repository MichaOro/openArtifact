"""A line dragged from a port and released on the empty canvas opens the "+" menu at the pointer (static/js/editor/connect-menu.js).

The menu is the editor's own add menu in its anchored mode, filtered to what can connect to the dragged port. Choosing a kind
makes the node where the line ended and connects it, in the normal direction whichever end was dragged; the connection that
left the dragged output is replaced and the notice names it; Escape or a click elsewhere cancels with nothing changed.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import centre, drag, eventually
from tests.helpers import connect, graph_url, node

MENU = ".ge-add__menu.is-anchored"


def _open_action(page: Page, base_url: str, api: httpx.Client) -> dict[str, Any]:
    definition: dict[str, Any] = api.post("/api/actions", json={"name": "Wires"}).json()
    return definition


def _show(page: Page, base_url: str, graph: dict[str, Any], kind: str = "actions") -> None:
    page.set_viewport_size(
        {"width": 1400, "height": 1100}
    )  # room for the menu below the release point
    page.goto(f"{base_url}/{kind}/{graph['slug']}")
    expect(page.locator(".ge-node").first).to_be_visible()


def _release(page: Page, port: Locator, dx: float, dy: float) -> tuple[float, float]:
    """Press the port, drag by (dx, dy) and let go; returns where the pointer was released."""
    x, y = centre(port)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=10)
    page.mouse.up()
    return x + dx, y + dy


def _edges(api: httpx.Client, graph: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    return sorted(
        (e["source_id"], e["source_port"], e["target_id"], e["target_port"])
        for e in api.get(graph_url(graph)).json()["edges"]
    )


def _nodes(api: httpx.Client, graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["id"]: n for n in api.get(graph_url(graph)).json()["nodes"]}


def _offered(page: Page, query: str) -> list[str]:
    """The kinds the open menu lists for a search."""
    page.fill(f"{MENU} .ge-add__search", query)
    return sorted(
        el.get_attribute("data-add") or "" for el in page.locator(f"{MENU} [data-add]").all()
    )


def _code(
    api: httpx.Client, graph: dict[str, Any], x: float = 120, y: float = 40, **extra: Any
) -> dict[str, Any]:
    return node(api, graph, "code", x=x, y=y, **extra)


def test_a_line_released_on_the_canvas_opens_the_add_menu_at_the_pointer(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    graph = _open_action(page, base_url, api)
    code = _code(api, graph)
    _show(page, base_url, graph)
    sx, sy = _release(page, page.locator(f'[data-node-id="{code["id"]}"] .ge-port--pass'), 60, 220)
    menu = page.locator(MENU)
    expect(menu).to_be_visible()
    box = menu.bounding_box()
    assert box is not None
    assert abs(box["x"] - sx) < 12 and abs(box["y"] - sy) < 12, "the menu opens at the pointer"
    expect(menu.locator(".ge-add__from")).to_contain_text("Connects from:")
    expect(menu.locator(".ge-add__from")).to_contain_text("On Pass")
    expect(menu.locator(".ge-add__search")).to_be_focused()


def test_choosing_a_kind_makes_it_where_the_line_ended_and_connects_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    graph = _open_action(page, base_url, api)
    code = _code(api, graph)
    _show(page, base_url, graph)
    before = set(_nodes(api, graph))
    _release(page, page.locator(f'[data-node-id="{code["id"]}"] .ge-port--pass'), 90, 220)
    page.fill(f"{MENU} .ge-add__search", "http")
    page.click(f"{MENU} [data-add=http]")
    eventually(lambda: len(_nodes(api, graph)) - len(before), 1)
    created = next(n for i, n in _nodes(api, graph).items() if i not in before)
    assert created["kind"] == "http"
    eventually(lambda: (code["id"], "pass", created["id"], "in") in _edges(api, graph), True)
    expect(page.locator(MENU)).to_be_hidden()
    expect(page.locator(f'.ge-node[data-node-id="{created["id"]}"]')).to_have_class(
        re.compile("is-selected")
    )
    expect(
        page.locator("#node-modal")
    ).to_be_hidden()  # the new node is only selected: its settings are the user's next step


def test_the_new_connection_is_straight_when_the_release_is_close_to_the_level_of_the_port(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    graph = _open_action(page, base_url, api)
    code = _code(api, graph)
    _show(page, base_url, graph)
    before = set(_nodes(api, graph))
    _release(page, page.locator(f'[data-node-id="{code["id"]}"] .ge-port--pass'), 330, 7)
    page.fill(f"{MENU} .ge-add__search", "set")
    page.click(f"{MENU} [data-add=set]")
    eventually(lambda: len(_nodes(api, graph)) - len(before), 1)
    created = next(i for i in _nodes(api, graph) if i not in before)
    out = page.locator(f'[data-node-id="{code["id"]}"] .ge-port--pass').bounding_box()
    entry = page.locator(f'[data-node-id="{created}"] .ge-port--in').bounding_box()
    assert out is not None and entry is not None
    assert abs((out["y"] + out["height"] / 2) - (entry["y"] + entry["height"] / 2)) < 1, (
        "the line is horizontal"
    )


def test_from_an_input_the_new_nodes_output_feeds_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    graph = _open_action(page, base_url, api)
    code = _code(api, graph, x=520, y=40)
    _show(page, base_url, graph)
    before = set(_nodes(api, graph))
    _release(page, page.locator(f'[data-node-id="{code["id"]}"] .ge-port--in'), -60, 230)
    expect(page.locator(MENU).locator(".ge-add__from")).to_contain_text("In")
    page.fill(f"{MENU} .ge-add__search", "timer")
    page.click(f"{MENU} [data-add=timer]")
    eventually(lambda: len(_nodes(api, graph)) - len(before), 1)
    created = next(i for i in _nodes(api, graph) if i not in before)
    eventually(
        lambda: (created, "out", code["id"], "in") in _edges(api, graph), True
    )  # stored from the output to the input


def test_from_an_agents_tools_port_only_tools_are_offered_and_one_hangs_below_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    graph = _open_action(page, base_url, api)
    agent = node(api, graph, "agent", x=120, y=40)
    _show(page, base_url, graph)
    before = set(_nodes(api, graph))
    _release(page, page.locator(f'[data-node-id="{agent["id"]}"] .ge-port--tools'), 40, 70)
    assert _offered(page, "tool") == ["code_tool", "http_tool", "mcp_tool", "postgres_tool"]
    assert _offered(page, "code") == ["code_tool"], "the Code node cannot be a tool"
    _offered(page, "http_tool")
    page.click(f"{MENU} [data-add=http_tool]")
    eventually(lambda: len(_nodes(api, graph)) - len(before), 1)
    tool = next(i for i in _nodes(api, graph) if i not in before)
    eventually(lambda: (tool, "tool", agent["id"], "tools") in _edges(api, graph), True)
    assert _nodes(api, graph)[tool]["y"] > agent["y"], "a tool hangs below its agent"


def test_the_connection_that_left_the_dragged_output_is_replaced_and_the_notice_names_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    graph = _open_action(page, base_url, api)
    code = _code(api, graph, x=100, y=40)
    gate = node(api, graph, "http", name="Goal Gate", x=560, y=40)
    connect(api, graph, code, "pass", gate, "in")
    _show(page, base_url, graph)
    before = set(_nodes(api, graph))
    _release(page, page.locator(f'[data-node-id="{code["id"]}"] .ge-port--pass'), 60, 230)
    page.fill(f"{MENU} .ge-add__search", "set")
    page.click(f"{MENU} [data-add=set]")
    eventually(lambda: len(_nodes(api, graph)) - len(before), 1)
    created = next(i for i in _nodes(api, graph) if i not in before)
    eventually(
        lambda: [e for e in _edges(api, graph) if e[0] == code["id"] and e[1] == "pass"],
        [(code["id"], "pass", created, "in")],
    )
    assert gate["id"] in _nodes(api, graph), "the node that was let go stays"
    expect(page.locator("[data-alert]")).to_contain_text("Disconnected from 'Goal Gate'")


def test_escape_and_a_click_elsewhere_cancel_everything(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    graph = _open_action(page, base_url, api)
    code = _code(api, graph, x=100, y=40)
    gate = node(api, graph, "http", name="Goal Gate", x=560, y=40)
    connect(api, graph, code, "pass", gate, "in")
    _show(page, base_url, graph)
    before = (_nodes(api, graph).keys(), _edges(api, graph))
    pass_port = page.locator(f'[data-node-id="{code["id"]}"] .ge-port--pass')
    _release(page, pass_port, 60, 230)
    expect(page.locator(MENU)).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator(MENU)).to_be_hidden()
    _release(page, pass_port, 60, 230)
    expect(page.locator(MENU)).to_be_visible()
    page.mouse.click(900, 600)
    expect(page.locator(MENU)).to_be_hidden()
    assert (_nodes(api, graph).keys(), _edges(api, graph)) == before, (
        "no node, no new connection, nothing let go"
    )
    expect(page.locator(".ge-node")).to_have_count(len(before[0]))


def test_the_plus_menu_still_works_and_is_not_filtered_after_a_cancelled_line(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    graph = _open_action(page, base_url, api)
    agent = node(api, graph, "agent", x=120, y=40)
    _show(page, base_url, graph)
    _release(page, page.locator(f'[data-node-id="{agent["id"]}"] .ge-port--tools'), 40, 70)
    page.keyboard.press("Escape")
    page.click("[data-add-menu]")
    expect(page.locator(".ge-add__menu")).not_to_have_class(re.compile("is-anchored"))
    expect(page.locator(".ge-add__from")).to_be_hidden()
    page.fill(".ge-add__search", "code")
    assert sorted(
        el.get_attribute("data-add") or "" for el in page.locator(".ge-add__menu [data-add]").all()
    ) == ["code", "code_tool"]
    page.click(".ge-add__menu [data-add=code]")
    eventually(lambda: sum(1 for n in _nodes(api, graph).values() if n["kind"] == "code"), 1)


def test_the_menu_is_used_with_the_keyboard(page: Page, base_url: str, api: httpx.Client) -> None:
    graph = _open_action(page, base_url, api)
    code = _code(api, graph)
    _show(page, base_url, graph)
    before = set(_nodes(api, graph))
    _release(page, page.locator(f'[data-node-id="{code["id"]}"] .ge-port--pass'), 90, 230)
    page.keyboard.type("http")
    page.keyboard.press("Enter")
    eventually(lambda: len(_nodes(api, graph)) - len(before), 1)
    created = next(i for i in _nodes(api, graph) if i not in before)
    eventually(lambda: (code["id"], "pass", created, "in") in _edges(api, graph), True)


def test_releasing_a_line_on_a_node_that_does_not_fit_does_nothing(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    graph = _open_action(page, base_url, api)
    code = _code(api, graph, x=100, y=40)
    other = _code(api, graph, x=520, y=40)
    _show(page, base_url, graph)
    fixed_edges = _edges(
        api, graph
    )  # a new action definition brings its own trigger-to-output connection
    x, y = centre(page.locator(f'[data-node-id="{other["id"]}"] .ge-node__text'))
    start_x, start_y = centre(page.locator(f'[data-node-id="{code["id"]}"] .ge-port--pass'))
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(x, y, steps=10)
    page.mouse.up()
    expect(page.locator(MENU)).to_be_hidden()
    assert _edges(api, graph) == fixed_edges, "no connection was made"


def test_a_line_released_inside_a_stage_offers_only_an_action_and_makes_it_there(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline: dict[str, Any] = api.post("/api/pipelines", json={"name": "Inside"}).json()
    stage = node(api, pipeline, "stage", name="Gap", x=200, y=40)
    api.patch(
        f"{graph_url(pipeline)}/nodes/{stage['id']}", json={"width": 560, "height": 380}
    ).raise_for_status()
    first = node(api, pipeline, "action", stage_id=stage["id"], x=60, y=14)
    _show(page, base_url, pipeline, "pipelines")
    before = set(_nodes(api, pipeline))
    _release(page, page.locator(f'[data-node-id="{first["id"]}"] .ge-port--pass'), 40, 150)
    assert _offered(page, "action") == ["action"]
    page.click(f"{MENU} [data-add=action]")
    eventually(lambda: len(_nodes(api, pipeline)) - len(before), 1)
    created = next(n for i, n in _nodes(api, pipeline).items() if i not in before)
    assert created["kind"] == "action" and created["stage_id"] == stage["id"]
    eventually(lambda: (first["id"], "pass", created["id"], "in") in _edges(api, pipeline), True)


def test_the_menu_header_and_an_empty_result_speak_german(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.context.add_cookies([{"name": "oa_lang", "value": "de", "url": base_url}])
    graph = _open_action(page, base_url, api)
    code = _code(api, graph)
    _show(page, base_url, graph)
    _release(page, page.locator(f'[data-node-id="{code["id"]}"] .ge-port--pass'), 60, 220)
    expect(page.locator(f"{MENU} .ge-add__from")).to_contain_text("Verbindet von:")


def test_dragging_a_connection_to_a_port_that_fits_still_connects_without_a_menu(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    graph = _open_action(page, base_url, api)
    code = _code(api, graph, x=100, y=40)
    other = _code(api, graph, x=560, y=40)
    _show(page, base_url, graph)
    fixed_edges = _edges(api, graph)
    drag(
        page,
        page.locator(f'[data-node-id="{code["id"]}"] .ge-port--pass'),
        page.locator(f'[data-node-id="{other["id"]}"] .ge-port--in'),
    )
    eventually(
        lambda: [e for e in _edges(api, graph) if e not in fixed_edges],
        [(code["id"], "pass", other["id"], "in")],
    )
    expect(page.locator(MENU)).to_be_hidden()
