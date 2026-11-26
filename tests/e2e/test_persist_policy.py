"""When the node dialog saves (ADR-059 addendum, ui-catalog "Persist on the user's act"): text on leaving the field or Enter,
a choice when it changes, never on a keystroke, never a draw under a focused field, and nothing typed is lost when the dialog
closes. Real keystrokes at human speed, the PATCH requests watched."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from playwright.sync_api import ElementHandle, Locator, Page, expect

from tests.agent_support import HEADERS, TOKEN, FakeLlm, fake_llm
from tests.e2e.conftest import _serve
from tests.e2e.helpers import add_setting, eventually
from tests.e2e.test_card_source import _agent, _open_agent_node, _provider
from tests.helpers import graph_url, node


@pytest.fixture(scope="module")
def card_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    yield from _serve(
        tmp_path_factory.mktemp("persist"),
        api_token=TOKEN,
        secret_key="k" * 40,
        llm_allow_private_networks="true",
    )


@pytest.fixture(scope="module")
def llm() -> Iterator[FakeLlm]:
    with fake_llm() as server:
        yield server


@pytest.fixture
def api(card_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=card_url, headers=HEADERS, timeout=30) as client:
        for path in ("/api/pipelines", "/api/actions", "/api/agents", "/api/providers"):
            for item in client.get(path).json():
                if path == "/api/providers":
                    client.patch(f"{path}/{item['id']}", json={"is_default": False})
                assert client.delete(f"{path}/{item['id']}").status_code == 204, path
        yield client


@pytest.fixture
def signed_in(page: Page, card_url: str) -> Page:
    page.goto(f"{card_url}/login")
    page.fill("#token", TOKEN)
    page.click("button[type=submit]")
    expect(page.locator(".lane")).to_have_count(3)
    return page


HUMAN = 35  # milliseconds between two keystrokes


def _watch(page: Page) -> list[str]:
    """The PATCH requests of the page that save a setting (not a move of a node), as their JSON bodies."""
    seen: list[str] = []

    def record(request: Any) -> None:
        body = request.post_data or ""
        if request.method == "PATCH" and "/nodes/" in request.url and '"x"' not in body:
            seen.append(body)

    page.on("request", record)
    return seen


def _stored(api: httpx.Client, action: dict[str, Any], kind: str) -> dict[str, Any]:
    nodes = api.get(graph_url(action)).json()["nodes"]
    return next(n for n in nodes if n["kind"] == kind)["config"]  # type: ignore[no-any-return]


def _leave(page: Page) -> None:
    """Leave the field the way a person does: click on an empty place of the dialog."""
    page.locator("#node-modal .modal__panel").click(position={"x": 4, "y": 4})


def _attached_and_focused(handle: ElementHandle) -> bool:
    return bool(handle.evaluate("el => el.isConnected && document.activeElement === el"))


def _code_node(
    page: Page, card_url: str, api: httpx.Client, code: str = "print(1)"
) -> tuple[dict[str, Any], Locator]:
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    node(api, action, "code", name="Run", config={"language": "python", "code": code})
    page.goto(f"{card_url}/actions/{action['slug']}")
    page.locator(".ge-node--code").dblclick(position={"x": 30, "y": 5})
    area = page.locator('.ge-inspector [data-focus-key="setting-code"]')
    expect(area).to_be_visible()
    return action, area


def _type_slowly_then_leave(page: Page, area: Locator, seen: list[str]) -> ElementHandle:
    handle = area.element_handle()
    assert handle is not None
    area.click()
    page.keyboard.press("Control+End")
    before = len(seen)
    page.keyboard.type(" # typed", delay=HUMAN)
    page.wait_for_timeout(1200)  # longer than the old autosave delay: still nothing may be sent
    assert len(seen) == before, "nothing is saved while typing"
    assert _attached_and_focused(handle), "the field under the caret is never replaced"
    return handle


def test_a_code_field_saves_once_when_it_is_left_and_never_while_typing(
    signed_in: Page, card_url: str, api: httpx.Client
) -> None:
    page = signed_in
    action, area = _code_node(page, card_url, api)
    seen = _watch(page)
    _type_slowly_then_leave(page, area, seen)
    expect(area.locator("xpath=ancestor::*[contains(@class,'ge-setting')][1]")).to_contain_text(
        "Not saved"
    )
    _leave(page)  # the field is left
    eventually(lambda: _stored(api, action, "code")["code"], "print(1) # typed", page=page)
    assert len(seen) == 1, seen


def test_the_caret_and_the_text_order_survive_typing_in_the_middle_of_a_text(
    signed_in: Page, card_url: str, api: httpx.Client
) -> None:
    page = signed_in
    action, area = _code_node(page, card_url, api, code="hello world")
    handle = area.element_handle()
    assert handle is not None
    area.click()
    page.keyboard.press("Control+Home")
    for _ in range(5):
        page.keyboard.press("ArrowRight")
    seen = _watch(page)
    page.keyboard.type("XY", delay=HUMAN)
    page.wait_for_timeout(1200)
    page.keyboard.press("ArrowRight")
    page.keyboard.type("Z", delay=HUMAN)
    assert area.input_value() == "helloXY Zworld"
    assert handle.evaluate("el => [el.selectionStart, el.selectionEnd]") == [9, 9]
    assert _attached_and_focused(handle) and not seen
    _leave(page)
    eventually(lambda: _stored(api, action, "code")["code"], "helloXY Zworld", page=page)


def test_a_graph_changed_event_while_a_field_is_focused_does_not_steal_the_caret(
    signed_in: Page, card_url: str, api: httpx.Client
) -> None:
    page = signed_in
    page.add_init_script(
        "window.__sources = []; const Real = window.EventSource;"
        "window.EventSource = class extends Real { constructor(...a) { super(...a); window.__sources.push(this); } };"
    )
    action, area = _code_node(page, card_url, api)
    handle = area.element_handle()
    assert handle is not None
    area.click()
    page.keyboard.press("Control+End")
    page.keyboard.type(" a", delay=HUMAN)
    page.evaluate(
        "id => window.__sources.forEach(s => s.dispatchEvent(new MessageEvent('graph.changed', {data: JSON.stringify({graph_ids: [id]})})))",
        action["id"],
    )
    page.wait_for_timeout(800)
    assert _attached_and_focused(handle), "the draw waits until the field is left"
    page.keyboard.type("b", delay=HUMAN)
    assert area.input_value() == "print(1) ab"
    _leave(page)
    eventually(lambda: _stored(api, action, "code")["code"], "print(1) ab", page=page)
    expect(page.locator('.ge-inspector [data-focus-key="setting-code"]')).to_have_value(
        "print(1) ab"
    )


def test_closing_the_dialog_with_unsaved_text_saves_it_first(
    signed_in: Page, card_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    agent = _agent(api, [{"name": "t"}], "T=${input.t}")
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    page = signed_in
    inspector = _open_agent_node(page, card_url, action, agent)
    add_setting(page, "User prompt")
    prompt = inspector.get_by_label("User prompt", exact=True)
    prompt.click()
    page.keyboard.press("Control+End")
    seen = _watch(page)
    page.keyboard.type(" and more", delay=HUMAN)
    page.wait_for_timeout(1000)
    assert not seen, "no save while typing"
    page.keyboard.press("Escape")  # closes the dialog: a blur may not come
    expect(page.locator("#node-modal")).to_be_hidden()
    eventually(
        lambda: str(_stored(api, action, "agent").get("user_prompt", "")).endswith(" and more"),
        True,
        page=page,
    )
    assert len(seen) == 1
    inspector = _open_agent_again(page)
    expect(inspector.get_by_label("User prompt", exact=True)).to_have_value("T=${input.t} and more")


def _open_agent_again(page: Page) -> Locator:
    page.locator(".ge-node--agent").first.dblclick(position={"x": 30, "y": 5})
    inspector = page.locator(".ge-inspector")
    expect(page.locator("#node-modal [data-node-version]")).to_have_text(re.compile(r"v\d+"))
    return inspector


def test_the_user_prompt_override_of_an_agent_node_keeps_focus_and_caret_while_typing(
    signed_in: Page, card_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    agent = _agent(api, [{"name": "t"}], "T=${input.t}")
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    page = signed_in
    inspector = _open_agent_node(page, card_url, action, agent)
    add_setting(page, "User prompt")
    prompt = inspector.get_by_label("User prompt", exact=True)
    handle = prompt.element_handle()
    assert handle is not None
    prompt.click()
    page.keyboard.press("Control+Home")
    seen = _watch(page)
    page.keyboard.type("Hi ", delay=HUMAN)
    page.wait_for_timeout(1200)
    page.keyboard.type("there ", delay=HUMAN)
    assert prompt.input_value() == "Hi there T=${input.t}"
    assert _attached_and_focused(handle) and not seen
    _leave(page)
    eventually(
        lambda: _stored(api, action, "agent").get("user_prompt"), "Hi there T=${input.t}", page=page
    )
    assert len(seen) == 1


def test_enter_saves_a_one_line_field_and_nothing_is_saved_before(
    signed_in: Page, card_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    agent = _agent(api, [{"name": "t", "required": True}], "T=${input.t}")
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    page = signed_in
    inspector = _open_agent_node(page, card_url, action, agent)
    field = inspector.get_by_label("Value for ${input.t}")
    seen = _watch(page)
    field.click()
    page.keyboard.type("${card.title}", delay=HUMAN)
    page.wait_for_timeout(1000)
    assert not seen
    page.keyboard.press("Enter")
    eventually(lambda: _stored(api, action, "agent").get("inputs"), "t = ${card.title}", page=page)
    assert len(seen) == 1
    expect(
        inspector.get_by_label("Value for ${input.t}")
    ).to_be_focused()  # the caret stays where it was


def test_a_select_and_a_switch_save_once_at_the_moment_they_change(
    signed_in: Page, card_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    agent = _agent(api, [{"name": "t"}], "T=${input.t}")
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    page = signed_in
    seen = _watch(page)
    inspector = _open_agent_node(page, card_url, action, agent)  # chooses the agent in the select
    assert len(seen) == 1 and json.loads(seen[0])["config"]["agent_id"] == agent["id"]
    page.keyboard.press("Escape")
    output = page.locator(".ge-node--output")
    output.dblclick(position={"x": 30, "y": 5})
    toggle = page.locator('#node-modal [role="switch"]').first
    state = toggle.get_attribute("aria-checked")
    before = len(seen)
    toggle.click()
    eventually(
        lambda: toggle.get_attribute("aria-checked"),
        "false" if state == "true" else "true",
        page=page,
    )
    page.wait_for_timeout(500)
    assert len(seen) == before + 1, "one save for one change"
    del inspector
