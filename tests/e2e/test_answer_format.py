"""The answer format in the browser (ADR-085): set in the agent editor and kept with the draft, overridden on a node, offered as data in the
reference list, said in the step."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import eventually
from tests.e2e.test_agents import _agent, _provider, agents_url, api, llm, signed_in
from tests.helpers import graph_url, node

__all__ = ["agents_url", "api", "llm", "signed_in"]  # the fixtures of the agent tests, used by name

FORMAT = [
    {"name": "passed", "type": "boolean", "required": True, "description": "Did it pass?"},
    {"name": "verdict", "type": "choice", "required": False, "choices": ["ship", "fix"]},
]


def _options(page: Page) -> Any:
    return page.get_by_role("listbox", name="References").get_by_role("option")


def test_the_answer_format_is_set_in_the_agent_editor_and_kept_with_the_draft(
    signed_in: Page, agents_url: str, api: httpx.Client
) -> None:
    agent = api.post(
        "/api/agents", json={"name": "Reviewer", "draft": {"user_prompt": "Review it."}}
    ).json()
    page = signed_in
    page.goto(f"{agents_url}/agents/{agent['id']}")
    editor = page.locator("[data-agent-editor]")
    format_ = editor.locator("[data-answer-format]")
    expect(editor.get_by_text("Answer format", exact=True).first).to_be_visible()
    rows = format_.locator(".sf__row")
    expect(rows).to_have_count(0)
    expect(editor.locator("[data-save]")).to_be_disabled()  # nothing changed yet
    format_.locator(".sf__add").click()
    format_.locator(".sf__add").click()
    expect(rows).to_have_count(2)
    expect(editor.locator("[data-save]")).to_be_enabled()  # a field is a change of the draft
    first = rows.nth(0)
    first.locator(".sf__name").fill("passed")
    first.locator(".sf__name").press("Enter")
    first.locator(".sf__type").select_option(label="True or false")
    first.locator(".sf__check").check()
    first.locator(".sf__description").fill("Did it pass?")
    first.locator(".sf__description").press("Enter")
    editor.locator("[data-save]").click()
    expect(editor.locator("[data-draft-state]")).to_contain_text("The draft is saved")
    stored = api.get(f"/api/agents/{agent['id']}").json()["draft"]["answer_format"]
    assert [(f["name"], f["type"], f["required"]) for f in stored] == [
        ("passed", "boolean", True),
        ("field_2", "text", False),
    ]
    page.reload()
    rows = page.locator("[data-answer-format] .sf__row")
    expect(rows).to_have_count(2)
    expect(rows.nth(0).locator(".sf__name")).to_have_value("passed")
    # a name the agent's own data already uses is refused with the reason, nothing is lost
    rows.nth(1).locator(".sf__name").fill("usage")
    rows.nth(1).locator(".sf__name").press("Enter")
    page.locator("[data-save]").click()
    expect(page.locator("[data-save-error]")).to_contain_text("used by the agent's own data")


def test_a_node_offers_the_fields_of_the_format_as_data_and_may_set_its_own(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: Any
) -> None:
    _provider(api, llm)
    agent = _agent(api, answer_format=FORMAT)
    definition: dict[str, Any] = api.post("/api/actions", json={"name": "Review flow"}).json()
    review = node(
        api, definition, "agent", name="Review", config={"agent_id": agent["id"]}, x=0, y=100
    )
    node(api, definition, "http", name="Call", x=0, y=420)
    page = signed_in
    page.goto(f"{agents_url}/actions/{definition['slug']}")
    page.locator(".ge-node[aria-label^='HTTP request:']").dblclick(position={"x": 30, "y": 5})
    url = page.locator(".ge-inspector").get_by_label("URL")
    url.click()
    url.press_sequentially("https://example.org/${(Review).")
    listbox = page.get_by_role("listbox", name="References")
    expect(listbox).to_be_visible()
    # the agent's published format: its fields are the data of the node
    expect(listbox.get_by_role("option", name="data.passed")).to_have_count(1)
    expect(listbox.get_by_role("option", name="data.verdict")).to_have_count(1)
    # a node that sets its own format (an empty one switches the agent's off): the list follows the node
    api.patch(
        f"{graph_url(definition)}/nodes/{review['id']}",
        json={"config": {"answer_format": [{"name": "ok", "type": "boolean", "required": True}]}},
    ).raise_for_status()
    page.reload()
    page.locator(".ge-node[aria-label^='HTTP request:']").dblclick(position={"x": 30, "y": 5})
    url = page.locator(".ge-inspector").get_by_label("URL")
    url.click()
    url.press_sequentially("https://example.org/${(Review).")
    listbox = page.get_by_role("listbox", name="References")
    expect(listbox.get_by_role("option", name="data.ok")).to_have_count(1)
    expect(listbox.get_by_role("option", name="data.passed")).to_have_count(0)
    eventually(
        lambda: [
            f["name"]
            for n in api.get(graph_url(definition)).json()["nodes"]
            if n["name"] == "Review"
            for f in n["config"]["answer_format"]
        ],
        ["ok"],
    )


def test_a_node_adds_an_answer_format_of_its_own_in_its_window(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: Any
) -> None:
    _provider(api, llm)
    agent = _agent(api, answer_format=FORMAT)
    definition: dict[str, Any] = api.post("/api/actions", json={"name": "Own format"}).json()
    node(api, definition, "agent", name="Review", config={"agent_id": agent["id"]})
    page = signed_in
    page.goto(f"{agents_url}/actions/{definition['slug']}")
    page.locator(".ge-node--agent").dblclick(position={"x": 30, "y": 5})
    modal = page.locator("#node-modal")
    expect(modal).to_be_visible()
    # the agent's format is told as what the node inherits, the node sets nothing yet
    modal.get_by_role("button", name="Add setting").first.click()
    # the menu tells what the agent has: the names of its fields
    item = page.get_by_role("menuitem", name="Answer format")
    expect(item.first).to_contain_text("passed, verdict")
    item.first.click()
    rows = modal.locator(".sf__row")
    expect(rows).to_have_count(2)  # it starts from the agent's fields
    rows.nth(0).locator(".sf__name").fill("approved")
    rows.nth(0).locator(".sf__name").press("Enter")
    eventually(
        lambda: [
            f["name"]
            for n in api.get(graph_url(definition)).json()["nodes"]
            if n["name"] == "Review"
            for f in (n["config"].get("answer_format") or [])
        ],
        ["approved", "verdict"],
    )
