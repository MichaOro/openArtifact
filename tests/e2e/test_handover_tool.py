"""The Hand Over Tool in the browser (ADR-080): its fields are a list that is added to, edited, ordered and kept; a step says what an agent
handed over. The model is the local stand-in."""

from __future__ import annotations

import json
from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.agent_support import FakeLlm, completion
from tests.e2e.helpers import eventually, execution_of, flow_url
from tests.e2e.test_agents import _agent, _provider, agents_url, api, llm, signed_in
from tests.helpers import build_pipeline, connect, graph_url, kind_of, node

__all__ = ["agents_url", "api", "llm", "signed_in"]  # the fixtures of the agent tests, used by name


def _fields(api: httpx.Client, definition: dict[str, Any]) -> Any:
    found = next(
        n for n in api.get(graph_url(definition)).json()["nodes"] if n["kind"] == "handover_tool"
    )
    return found["config"].get("fields")


def test_the_fields_are_a_list_that_is_added_to_edited_ordered_and_kept(
    signed_in: Page, agents_url: str, api: httpx.Client
) -> None:
    page = signed_in
    definition: dict[str, Any] = api.post("/api/actions", json={"name": "Hand over check"}).json()
    page.goto(f"{agents_url}/actions/{definition['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.click("[data-add-menu]")
    page.fill(".ge-add__search", "Hand")
    page.click("[data-add=handover_tool]")
    page.locator(".ge-node--handover_tool").dblclick(position={"x": 30, "y": 5})
    modal = page.locator("#node-modal")
    expect(modal).to_be_visible()
    rows = modal.locator(".sf__row")
    expect(rows).to_have_count(0)

    # a field is added with a name nobody has, as an optional text; the list is stored at once
    modal.locator(".sf__add").click()
    modal.locator(".sf__add").click()
    expect(rows).to_have_count(2)
    # this narrow window keeps its compact layout (the one row per field with heads belongs to the Trigger, Output and Complete windows,
    # ADR-083) and the text for a model: it is where a model fills the field
    expect(modal.locator(".sf--wide")).to_have_count(0)
    expect(modal.locator(".sf__head")).to_have_count(0)
    expect(rows.nth(0).locator(".sf__description")).to_have_attribute(
        "placeholder", "What the model puts here"
    )
    expect(rows.nth(0).locator(".sf__name")).to_have_value("field")
    expect(rows.nth(1).locator(".sf__name")).to_have_value("field_2")
    eventually(
        lambda: [(f["name"], f["type"], f["required"]) for f in _fields(api, definition)],
        [("field", "text", False), ("field_2", "text", False)],
    )

    # nothing of a row lies over the bin, however narrow the window (ADR-074)
    for width in (1280, 520):
        page.set_viewport_size({"width": width, "height": 900})
        for index in range(2):
            boxes = [
                rows.nth(index).locator(f".sf__{part}").bounding_box()
                for part in ("grip", "name", "type", "required", "bin")
            ]
            for i, one in enumerate(boxes):
                for other in boxes[i + 1 :]:
                    assert one and other
                    apart = (
                        one["x"] + one["width"] <= other["x"] + 1
                        or other["x"] + other["width"] <= one["x"] + 1
                        or one["y"] + one["height"] <= other["y"] + 1
                        or other["y"] + other["height"] <= one["y"] + 1
                    )
                    assert apart, f"two controls of row {index + 1} overlap at {width} px"
    page.set_viewport_size({"width": 1280, "height": 900})

    # a name and a description are saved when the field is confirmed; the type and "required" at once
    first = rows.nth(0)
    first.locator(".sf__name").fill("passed")
    first.locator(".sf__name").press("Enter")
    first.locator(".sf__type").select_option(label="True or false")
    first.locator(".sf__check").check()
    first.locator(".sf__description").fill("Whether it holds")
    first.locator(".sf__description").press("Enter")
    eventually(
        lambda: _fields(api, definition)[0],
        {"name": "passed", "type": "boolean", "required": True, "description": "Whether it holds"},
    )

    # a choice shows its values; they are read as typed, separated by commas
    second = rows.nth(1)
    second.locator(".sf__name").fill("verdict")
    second.locator(".sf__name").press("Enter")
    expect(second.locator(".sf__choices")).to_have_count(0)  # only a choice has values
    second.locator(".sf__type").select_option(label="Choice")
    values = second.locator(".sf__choices")
    expect(values).to_be_visible()
    values.fill("approve, reject")
    values.press("Enter")
    eventually(
        lambda: _fields(api, definition)[1],
        {
            "name": "verdict",
            "type": "choice",
            "required": False,
            "description": "",
            "choices": ["approve", "reject"],
        },
    )

    # the order is the order the model sees: the handle moves a row with the arrow keys and the focus follows it
    second.locator(".sf__grip").focus()
    page.keyboard.press("ArrowUp")
    expect(rows.nth(0).locator(".sf__name")).to_have_value("verdict")
    expect(rows.nth(0).locator(".sf__grip")).to_be_focused()
    eventually(lambda: [f["name"] for f in _fields(api, definition)], ["verdict", "passed"])

    # a name that is not allowed says why and is not sent
    rows.nth(1).locator(".sf__name").fill("Bad name")
    rows.nth(1).locator(".sf__name").press("Enter")
    expect(modal.get_by_role("alert").first).to_contain_text(
        "Field 2: the name is lowercase letters, digits and _"
    )
    assert [f["name"] for f in _fields(api, definition)] == ["verdict", "passed"]

    # a field is taken away with its bin
    rows.nth(1).locator(".sf__name").fill("passed")
    rows.nth(1).locator(".sf__name").press("Enter")
    rows.nth(0).locator(".sf__bin").click()
    expect(rows).to_have_count(1)
    eventually(lambda: [f["name"] for f in _fields(api, definition)], ["passed"])


def test_a_step_says_what_the_agent_handed_over_and_shows_the_document(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    agent = _agent(api)
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    trigger, output = kind_of(api, action, "trigger"), kind_of(api, action, "output")
    for edge in api.get(graph_url(action)).json()["edges"]:
        api.delete(f"{graph_url(action)}/edges/{edge['id']}")
    ask = node(
        api, action, "agent", name="Ask", config={"agent_id": agent["id"], "inputs": "ticket = T-7"}
    )
    tool = node(
        api,
        action,
        "handover_tool",
        name="Review",
        config={
            "tool_name": "report",
            "fields": [
                {"name": "passed", "type": "boolean", "required": True},
                {"name": "reasons", "type": "list"},
            ],
        },
        x=100,
        y=320,
    )
    connect(api, action, trigger, "out", ask, "in")
    connect(api, action, tool, "tool", ask, "tools")
    connect(api, action, ask, "pass", output, "pass")
    pipeline = build_pipeline(api, stages=1)
    api.patch(
        f"{graph_url(pipeline)}/nodes/{pipeline['stages'][0][1]['id']}",
        json={"definition_id": action["id"]},
    )
    call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {
                    "name": "report",
                    "arguments": json.dumps({"passed": True, "reasons": ["clear", "tested"]}),
                },
            }
        ],
    }
    llm.script = [
        (
            200,
            {"id": "x", "choices": [{"index": 0, "message": call, "finish_reason": "tool_calls"}]},
        ),
        (200, completion("Handed over.")),
    ]
    task: dict[str, Any] = api.post(
        "/api/tasks", json={"title": "Item", "status": "backlog"}
    ).json()
    api.post(
        f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]}
    ).raise_for_status()
    eventually(lambda: execution_of(api, task)["status"], "done", timeout=30)

    page = signed_in
    page.goto(flow_url(agents_url, task, execution_of(api, task)))
    page.locator(".ge-node--action").first.click()
    page.locator(".ef-path__item").filter(has_text="Ask").locator(".ef-path__main").click()
    detail = page.locator("[data-panel-detail]")
    expect(detail).to_contain_text("Handed over: Review")  # the step names the documents
    detail.locator("[data-step-data] summary").click()
    shown = detail.locator("[data-step-data] pre")
    expect(shown).to_contain_text('"handovers"')
    expect(shown).to_contain_text('"passed": true')
    expect(shown).to_contain_text('"clear"')
