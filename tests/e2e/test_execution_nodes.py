"""The Code and HTTP request nodes in the action editor: add, configure, connect, delete."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import drag as _drag
from tests.e2e.helpers import eventually
from tests.helpers import graph_url


def _open_action(page: Page, base_url: str, api: httpx.Client) -> dict[str, Any]:
    definition: dict[str, Any] = api.post("/api/actions", json={"name": "Check"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    return definition


def _add(page: Page, kind: str) -> Locator:
    page.click("[data-add-menu]")
    page.click(f"[data-add={kind}]")
    node = page.locator(f".ge-node--{kind}")
    expect(node).to_have_count(1)
    return node


def _stored(api: httpx.Client, definition: dict[str, Any], kind: str) -> dict[str, Any]:
    nodes = api.get(graph_url(definition)).json()["nodes"]
    return next(n for n in nodes if n["kind"] == kind)


def _config(api: httpx.Client, definition: dict[str, Any], kind: str, **expected: Any) -> None:
    """The stored config of the node becomes (at least) `expected`; saving is asynchronous."""

    def stored() -> dict[str, Any]:
        config: dict[str, Any] = _stored(api, definition, kind)["config"]
        return {k: config.get(k) for k in expected}

    eventually(stored, expected)


def _edges(api: httpx.Client, definition: dict[str, Any]) -> list[tuple[str, str]]:
    edges = api.get(graph_url(definition)).json()["edges"]
    return sorted((e["source_port"], e["target_port"]) for e in edges)


def _expect_edges(api: httpx.Client, definition: dict[str, Any], expected: list[Any]) -> None:
    eventually(lambda: _edges(api, definition), expected)


def _select(page: Page, kind: str) -> Locator:
    # the top edge of the card: the line from trigger to output runs across its middle and takes the clicks
    page.locator(f".ge-node--{kind}").click(position={"x": 30, "y": 5})
    return page.locator(".ge-inspector")


def test_a_code_node_is_added_configured_and_persists(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open_action(page, base_url, api)
    node = _add(page, "code")
    expect(node.locator(".ge-node__kind")).to_have_text("sh · no code yet")
    inspector = page.locator(".ge-inspector")
    code = inspector.get_by_label("Code", exact=True)
    code.fill("echo hello\necho second")
    expect(inspector.get_by_text("Saved")).to_be_visible()
    expect(node.locator(".ge-node__kind")).to_have_text("sh · echo hello")
    inspector.get_by_label("Language").select_option("python")
    inspector.get_by_label("Timeout (seconds)").fill("45")
    inspector.get_by_label("Timeout (seconds)").press("Enter")
    expect(node.locator(".ge-node__kind")).to_have_text("python · echo hello")
    _config(api, definition, "code", language="python", timeout_seconds=45)

    page.reload()
    inspector = _select(page, "code")
    expect(inspector.get_by_label("Code", exact=True)).to_have_value("echo hello\necho second")
    expect(inspector.get_by_label("Language")).to_have_value("python")
    expect(inspector.get_by_label("Timeout (seconds)")).to_have_value("45")
    expect(inspector.get_by_text("2 lines · 22 / 20000")).to_be_visible()


def test_a_refused_value_shows_the_server_message_and_keeps_the_text(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open_action(page, base_url, api)
    _add(page, "code")
    inspector = page.locator(".ge-inspector")
    timeout = inspector.get_by_label("Timeout (seconds)")
    timeout.fill("0")
    timeout.press("Enter")
    expect(inspector.get_by_role("alert")).to_have_text("'timeout_seconds' must be 1 to 600")
    expect(timeout).to_have_value("0")
    expect(timeout).to_have_attribute("aria-invalid", "true")
    timeout.fill("20")
    timeout.press("Enter")
    expect(inspector.get_by_role("alert")).to_have_count(0)  # hidden again

    long = "x" * 20001
    code = inspector.get_by_label("Code", exact=True)
    code.fill(long)
    expect(inspector.get_by_role("alert")).to_have_text("'code' is too long")
    expect(inspector.get_by_text("(too long)")).to_be_visible()
    assert len(code.input_value()) == 20001  # nothing was lost
    assert _stored(api, definition, "code")["config"]["code"] == ""
    code.fill("echo ok")
    expect(inspector.get_by_text("Saved")).to_be_visible()


def test_the_code_field_indents_with_tab_and_escape_then_tab_leaves_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _open_action(page, base_url, api)
    _add(page, "code")
    inspector = page.locator(".ge-inspector")
    code = inspector.get_by_label("Code", exact=True)
    expect(inspector.get_by_text("Press Escape, then Tab to leave the field.")).to_be_visible()
    code.click()
    page.keyboard.type("if x:")
    page.keyboard.press("Tab")
    assert code.input_value() == "if x:  "
    expect(code).to_be_focused()
    page.keyboard.press("Escape")
    page.keyboard.press("Tab")
    expect(code).not_to_be_focused()
    expect(
        inspector.get_by_label("Secrets")
    ).to_be_focused()  # the field after Code (migration 0022)
    page.keyboard.press("Tab")
    expect(inspector.get_by_label("Sets variables")).to_be_focused()  # declared variables (ADR-034)
    page.keyboard.press("Tab")
    expect(inspector.get_by_label("Timeout (seconds)")).to_be_focused()


def test_the_focus_stays_in_the_field_while_typing_and_saving(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open_action(page, base_url, api)
    _add(page, "code")
    inspector = page.locator(".ge-inspector")
    code = inspector.get_by_label("Code", exact=True)
    code.click()
    page.keyboard.type("echo one")
    expect(inspector.get_by_text("Saved")).to_be_visible()
    expect(code).to_be_focused()
    page.keyboard.type(" two")
    expect(code).to_be_focused()
    expect(code).to_have_value("echo one two")
    _config(api, definition, "code", code="echo one two")
    expect(code).to_be_focused()


def test_an_http_node_is_configured_and_persists(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open_action(page, base_url, api)
    _add(page, "http")
    inspector = page.locator(".ge-inspector")
    inspector.get_by_label("Method").select_option("POST")
    url = inspector.get_by_label("URL")
    expect(url).to_have_attribute("placeholder", "https://example.org/hook")
    url.fill("https://example.org/hook")
    url.press("Enter")
    inspector.get_by_label("Headers").fill("X-Run: 1\nAccept: text/plain")
    inspector.get_by_label("Body").fill('{"a": 1}')
    inspector.get_by_label("Timeout (seconds)").fill("10")
    inspector.get_by_label("Timeout (seconds)").press("Enter")
    status = inspector.get_by_label("Success status")
    status.fill("200, 404")
    status.press("Enter")
    _config(
        api,
        definition,
        "http",
        method="POST",
        url="https://example.org/hook",
        headers="X-Run: 1\nAccept: text/plain",
        body='{"a": 1}',
        timeout_seconds=10,
        success_status="200, 404",
    )
    page.reload()
    inspector = _select(page, "http")
    expect(inspector.get_by_label("Method")).to_have_value("POST")
    expect(inspector.get_by_label("URL")).to_have_value("https://example.org/hook")
    expect(inspector.get_by_label("Headers")).to_have_value("X-Run: 1\nAccept: text/plain")
    expect(inspector.get_by_label("Body")).to_have_value('{"a": 1}')
    expect(inspector.get_by_label("Success status")).to_have_value("200, 404")
    expect(inspector.get_by_label("Timeout (seconds)")).to_have_value("10")


def test_the_http_summary_never_shows_the_query_string(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _open_action(page, base_url, api)
    node = _add(page, "http")
    inspector = page.locator(".ge-inspector")
    expect(node.locator(".ge-node__kind")).to_have_text("GET no URL yet")
    url = inspector.get_by_label("URL")
    url.fill("https://user:pw@example.org/hook?token=secret#frag")
    url.press("Enter")
    expect(node.locator(".ge-node__kind")).to_have_text("GET example.org/hook")
    expect(node).not_to_contain_text("secret")
    expect(node).not_to_contain_text("pw")
    status = inspector.get_by_label("Success status")
    status.fill("abc")
    status.press("Enter")
    expect(inspector.get_by_role("alert")).to_contain_text("status codes")
    expect(status).to_have_value("abc")


def test_pass_and_fail_connect_to_the_output_and_the_next_node(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open_action(page, base_url, api)
    code = _add(page, "code")
    _add(page, "http")
    page.locator(".ge-node--output .ge-node__name").click()
    page.locator(".ge-switch").click()
    expect(page.locator(".ge-node--output .ge-port--fail")).to_be_visible()
    page.click("[data-zoom-fit]")
    output = page.locator(".ge-node--output")
    expect(code.locator(".ge-port--pass")).to_be_visible()
    expect(code.locator(".ge-port--pass")).to_have_attribute("data-label", "On Pass")
    expect(code.locator(".ge-port--fail")).to_have_attribute("data-label", "On Fail")
    _drag(page, code.locator(".ge-port--pass"), output.locator(".ge-port--pass"))
    _expect_edges(api, definition, [("out", "pass"), ("pass", "pass")])
    _drag(page, code.locator(".ge-port--fail"), output.locator(".ge-port--fail"))
    _expect_edges(api, definition, [("fail", "fail"), ("out", "pass"), ("pass", "pass")])
    expect(page.locator(".ge-edge--fail")).to_have_count(1)

    http = page.locator(".ge-node--http")
    _drag(page, page.locator(".ge-node--trigger .ge-port--out"), code.locator(".ge-port--in"))
    _drag(page, code.locator(".ge-port--pass"), http.locator(".ge-port--in"))
    _expect_edges(api, definition, [("fail", "fail"), ("out", "in"), ("pass", "in")])


def test_a_code_node_is_deleted_with_its_connections(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open_action(page, base_url, api)
    code = _add(page, "code")
    page.click("[data-zoom-fit]")
    _drag(
        page,
        code.locator(".ge-port--pass"),
        page.locator(".ge-node--output .ge-port--pass"),
    )
    _expect_edges(api, definition, [("out", "pass"), ("pass", "pass")])
    _select(page, "code").locator(".ge-delete").click()
    page.click("#confirm-modal [data-confirm]")
    expect(page.locator(".ge-node--code")).to_have_count(0)
    _expect_edges(api, definition, [("out", "pass")])
