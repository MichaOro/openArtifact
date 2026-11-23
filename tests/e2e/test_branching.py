"""The If and Switch nodes and the suggestions for ${...} references, in the action editor and the flow page."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.conftest import SECURED_TOKEN
from tests.e2e.helpers import drag as _drag
from tests.e2e.helpers import eventually, execution_of, flow_url, menu_kinds, pick_node, run_started
from tests.helpers import build_definition, build_pipeline, connect, graph_url, kind_of, link, node

_PASSED = re.compile(r"\bef-state-pass\b")
SETTER = "import json\nprint(json.dumps({'ok': True, 'vars': {'priority': 'high'}}))"


def _open_action(
    page: Page, base_url: str, api: httpx.Client, name: str = "Triage"
) -> dict[str, Any]:
    definition: dict[str, Any] = api.post("/api/actions", json={"name": name}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    return definition


def _add(page: Page, kind: str) -> Locator:
    page.click("[data-add-menu]")
    pick_node(page, kind)
    added = page.locator(f".ge-node--{kind}")
    expect(added).to_have_count(1)
    added.dblclick(position={"x": 30, "y": 5})  # the settings open in an overlay
    return added


def _select(page: Page, kind: str) -> Locator:
    """Open the settings of the (only) node of this kind: a double click, after closing any other dialog."""
    if page.locator("#node-modal").is_visible():
        page.keyboard.press("Escape")
        expect(page.locator("#node-modal")).not_to_be_visible()
    page.locator(f".ge-node--{kind}").dblclick(position={"x": 30, "y": 5})
    return page.locator(".ge-inspector")


def _edges(api: httpx.Client, definition: dict[str, Any]) -> list[tuple[str, str]]:
    edges = api.get(graph_url(definition)).json()["edges"]
    return sorted((e["source_port"], e["target_port"]) for e in edges)


def test_the_menu_offers_if_and_switch_after_http(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _open_action(page, base_url, api)
    page.click("[data-add-menu]")
    assert menu_kinds(page) == {
        "AI": ["Agent"],
        "Agent tools": ["MCP Client Tool", "HTTP Request Tool", "Code Tool", "Postgres Tool"],
        "Apps and data": ["GitHub", "Postgres"],
        "Core": ["Code", "HTTP request"],
        "Data": ["Edit Fields", "Artifact"],
        "Flow": ["If", "Switch", "Timer"],
    }


def test_an_if_node_is_configured_and_its_outputs_connect(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open_action(page, base_url, api)
    branch = _add(page, "if")
    expect(branch.locator(".ge-node__kind")).to_have_text("no condition yet")
    inspector = _select(page, "if")
    inspector.get_by_label("Value").first.fill("${var.priority}")
    inspector.get_by_label("Value").first.press("Enter")
    inspector.get_by_label("Compare with").first.fill("high")
    inspector.get_by_label("Compare with").first.press("Enter")
    inspector.get_by_label("Operator").first.select_option("not equals")
    expect(branch.locator(".ge-node__kind")).to_have_text("${var.priority} not equals high")
    # a second row is folded until it is opened
    expect(inspector.locator("details.ge-group")).to_have_count(5)
    expect(inspector.locator("details.ge-group[open]")).to_have_count(1)
    inspector.locator("summary", has_text="Condition 2").click()
    inspector.get_by_label("Value").nth(1).fill("${var.score}")
    inspector.get_by_label("Value").nth(1).press("Enter")
    expect(branch.locator(".ge-node__kind")).to_contain_text("+1 more")
    refused = inspector.get_by_label("Compare with").first
    refused.fill("${secret:API_KEY}")
    refused.press("Enter")
    expect(inspector.get_by_role("alert")).to_contain_text("secret")
    refused.fill("high")
    refused.press("Enter")
    page.keyboard.press("Escape")

    page.locator(".ge-node--output .ge-node__name").dblclick()
    page.locator(".ge-switch").click()  # On Fail of the output
    page.keyboard.press("Escape")
    page.click("[data-zoom-fit]")
    output = page.locator(".ge-node--output")
    for port, label in (("yes", "Yes"), ("no", "No"), ("else", "Else")):
        expect(branch.locator(f".ge-port--{port}")).to_have_attribute("data-label", label)
    _drag(page, branch.locator(".ge-port--yes"), output.locator(".ge-port--pass"))
    _drag(page, branch.locator(".ge-port--else"), output.locator(".ge-port--fail"))
    eventually(
        lambda: _edges(api, definition), [("else", "fail"), ("out", "pass"), ("yes", "pass")]
    )
    expect(page.locator(".ge-edge--yes")).to_have_count(1)
    expect(page.locator(".ge-edge--else")).to_have_count(1)
    expect(page.locator(".ge-edge--else .ge-edge__line")).to_have_css(
        "stroke-dasharray", "6px, 4px"
    )


def _case(inspector: Locator, number: int) -> Locator:
    """The value field of a Switch case; its group is opened first (unused cases are folded away)."""
    group = inspector.locator(f'details[data-group="Case {number}"]')
    if group.get_attribute("open") is None:
        group.locator("summary").click()
    return group.get_by_label("Compare with")


def test_a_switch_shows_its_cases_as_port_labels_and_hides_the_unused(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open_action(page, base_url, api)
    switch = _add(page, "switch")
    expect(switch.locator(".ge-port:not([hidden])[data-direction=output]")).to_have_count(1)  # Else
    expect(switch.locator(".ge-node__kind")).to_have_text("no value yet · 0 cases")
    inspector = _select(page, "switch")
    inspector.get_by_label("Value").fill("${var.tier}")
    inspector.get_by_label("Value").press("Enter")
    for number, text in ((1, "silver"), (2, "gold")):
        field = _case(inspector, number)
        field.fill(text)
        field.press("Enter")
    expect(switch.locator(".ge-node__kind")).to_have_text("${var.tier} · 2 cases")
    expect(switch.locator(".ge-port:not([hidden])[data-direction=output]")).to_have_count(3)
    expect(switch.locator(".ge-port--case_1")).to_have_attribute("data-label", "silver")
    expect(switch.locator(".ge-port--case_2")).to_have_attribute("data-label", "gold")
    expect(switch.locator(".ge-port--case_3")).to_be_hidden()
    expect(switch.locator(".ge-port--else")).to_have_attribute("data-label", "Else")
    page.keyboard.press("Escape")
    page.click("[data-zoom-fit]")
    _drag(page, switch.locator(".ge-port--case_2"), page.locator(".ge-node--output .ge-port--pass"))
    eventually(lambda: _edges(api, definition), [("case_2", "pass"), ("out", "pass")])
    inspector = _select(page, "switch")
    field = _case(inspector, 2)
    field.fill("")
    field.press("Enter")  # an emptied case loses its output and its connection
    eventually(lambda: _edges(api, definition), [("out", "pass")])
    expect(switch.locator(".ge-port--case_2")).to_be_hidden()


def test_the_flow_page_shows_the_branch_that_was_taken(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = build_pipeline(api, stages=1, name="Triage flow")
    definition = build_definition(api, "Triage", output=None, fail_enabled=True)
    trigger, output = kind_of(api, definition, "trigger"), kind_of(api, definition, "output")
    setter = node(
        api, definition, "code", name="Classify", config={"language": "python", "code": SETTER}
    )
    decide = node(
        api,
        definition,
        "if",
        name="Decide",
        config={"left_1": "${var.priority}", "operator_1": "equals", "right_1": "high"},
    )
    urgent = node(api, definition, "code", name="Escalate", config={"code": "echo escalated"})
    connect(api, definition, trigger, "out", setter, "in")
    connect(api, definition, setter, "pass", decide, "in")
    connect(api, definition, decide, "yes", urgent, "in")
    connect(api, definition, decide, "no", output, "pass")
    connect(api, definition, decide, "else", output, "fail")
    connect(api, definition, urgent, "pass", output, "pass")
    link(api, pipeline, pipeline["stages"][0][1], definition)
    task: dict[str, Any] = api.post("/api/tasks", json={"title": "Item"}).json()
    run_started(api, task, pipeline)
    page.goto(flow_url(base_url, task, execution_of(api, task)))
    page.locator(".ge-node[aria-label^='Action: Triage']").dblclick()
    decide_node = page.locator(".ge-node[aria-label^='If: Decide']")
    expect(decide_node).to_have_class(_PASSED)
    expect(page.locator(".ge-node[aria-label^='Code: Escalate']")).to_have_class(_PASSED)
    expect(page.locator(".ge-edge--yes.is-walked")).to_have_count(1)
    expect(page.locator(".ge-edge--no.is-walked, .ge-edge--else.is-walked")).to_have_count(0)
    expect(decide_node.locator(".ge-port--yes")).to_have_attribute("data-label", "Yes")
    page.locator(".ef-path__item", has_text="Decide").locator(".ef-path__main").click()
    expect(page.locator("[data-panel-detail]")).to_contain_text("Port: Yes")


# ── suggestions while typing a reference ─────────────────────────────


@pytest.fixture
def secured(secured_url: str) -> Iterator[httpx.Client]:
    """Secrets need an access token and a key: the secured server, emptied of actions before each test."""
    headers = {"Authorization": f"Bearer {SECURED_TOKEN}"}
    with httpx.Client(base_url=secured_url, headers=headers) as client:
        for graph in client.get("/api/actions").json():
            client.delete(f"/api/actions/{graph['id']}")
        client.put("/api/secrets/E2E_TOKEN", json={"value": "not shown"}).raise_for_status()
        yield client


def _editor(page: Page, secured_url: str, api: httpx.Client) -> None:
    """Sign in and open the 'Suggest' action (a Code node that sets 'priority', an HTTP node, an If node)."""
    definition = _suggest_definition(api)
    page.goto(f"{secured_url}/actions/{definition['slug']}")
    page.fill("#token", SECURED_TOKEN)
    page.click("button[type=submit]")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.click("[data-zoom-fit]")


def _suggest_definition(api: httpx.Client) -> dict[str, Any]:
    definition: dict[str, Any] = api.post("/api/actions", json={"name": "Suggest"}).json()
    config = {"language": "sh", "code": "true", "sets_variables": "priority\nscore"}
    node(api, definition, "code", name="Fetch user", x=0, y=200, config=config)
    node(api, definition, "http", name="Call", x=0, y=420)
    node(api, definition, "if", name="Decide", x=0, y=620)
    return definition


def _options(page: Page) -> Locator:
    return page.get_by_role("listbox", name="References").get_by_role("option")


def test_typing_a_reference_suggests_and_the_keyboard_accepts(
    page: Page, secured_url: str, secured: httpx.Client
) -> None:
    _editor(page, secured_url, secured)
    page.locator(".ge-node[aria-label^='HTTP request:']").dblclick(position={"x": 30, "y": 5})
    url = page.locator(".ge-inspector").get_by_label("URL")
    url.click()
    url.press_sequentially("https://example.org/${")
    listbox = page.get_by_role("listbox", name="References")
    expect(listbox).to_be_visible()
    expect(url).to_have_attribute("aria-expanded", "true")
    # the first step: the groups and the nodes by name, not everything at once
    expect(_options(page).first).to_contain_text(
        "var."
    )  # (and card. where the artifact has fields)
    expect(listbox.get_by_role("option", name="var.")).to_have_count(1)
    page.wait_for_timeout(500)  # the secret names arrive a moment after the field got focus
    url.press("Backspace")
    url.press_sequentially("{")  # asks again
    expect(listbox.get_by_role("option", name="secret:")).to_have_count(1)  # allowed in a URL
    expect(listbox.get_by_role("option", name="(Fetch user).")).to_have_count(1)
    expect(listbox.get_by_role("option", name="(Decide).")).to_have_count(1)
    expect(listbox.get_by_role("option", name="exit_code")).to_have_count(0)
    # choosing a node shows what is behind it
    url.press_sequentially("(Decide).")
    expect(_options(page)).to_have_count(4 + 1)  # the If node's own result: 5 fields
    url.fill("https://example.org/${(Fetch")
    expect(_options(page)).to_have_count(1)
    url.press("Enter")
    expect(url).to_have_value("https://example.org/${(Fetch user).")
    expect(_options(page).first).to_contain_text("(Fetch user).output")
    url.press("ArrowDown")
    expect(url).to_have_attribute("aria-activedescendant", re.compile(r"^ge-suggest-\d+-1$"))
    url.press("Enter")
    expect(url).to_have_value("https://example.org/${(Fetch user).exit_code}")
    expect(listbox).to_be_hidden()
    # typing filters, Escape closes and keeps what was typed
    url.press_sequentially("?q=${var.pr")
    expect(_options(page)).to_have_count(1)
    url.press("Escape")
    expect(listbox).to_be_hidden()
    expect(url).to_have_value("https://example.org/${(Fetch user).exit_code}?q=${var.pr")
    url.press("Control+ ")  # Ctrl+Space inside an open ${ asks again
    expect(_options(page)).to_have_count(1)
    _options(page).first.click()
    expect(url).to_have_value("https://example.org/${(Fetch user).exit_code}?q=${var.priority}")


def test_conditions_never_suggest_secrets_and_the_code_text_never_suggests(
    page: Page, secured_url: str, secured: httpx.Client
) -> None:
    _editor(page, secured_url, secured)
    page.locator(".ge-node[aria-label^='If:']").dblclick(position={"x": 30, "y": 5})
    left = page.locator(".ge-inspector").get_by_label("Value").first
    left.click()
    left.press_sequentially("${")
    expect(_options(page).first).to_be_visible()
    expect(page.get_by_role("option", name="secret:")).to_have_count(0)
    left.press("Escape")  # closes the list
    page.keyboard.press("Escape")  # closes the dialog
    page.locator(".ge-node[aria-label^='Code:']").dblclick(position={"x": 30, "y": 5})
    code = page.locator(".ge-inspector").get_by_label("Code", exact=True)
    code.click()
    code.press_sequentially("echo ${")
    expect(page.get_by_role("listbox", name="References")).to_have_count(0)


def test_the_suggestions_fit_a_phone(page: Page, secured_url: str, secured: httpx.Client) -> None:
    page.set_viewport_size({"width": 390, "height": 800})
    _editor(page, secured_url, secured)
    page.locator(".ge-node[aria-label^='HTTP request:']").dblclick(position={"x": 30, "y": 5})
    body = page.locator(".ge-inspector").get_by_label("Body")
    body.scroll_into_view_if_needed()
    body.click()
    body.press_sequentially('{"a": "${')
    listbox = page.get_by_role("listbox", name="References")
    expect(listbox).to_be_visible()
    box = listbox.bounding_box()
    assert box is not None
    assert box["x"] >= 0 and box["x"] + box["width"] <= 390 and box["y"] + box["height"] <= 800
    assert page.evaluate("document.documentElement.scrollWidth") <= 390  # no horizontal scroll
    assert (
        3 <= listbox.get_by_role("option").count() <= 5
    )  # var., two nodes, perhaps secret: and card.
