"""Inputs and outputs of actions in the editor (ADR-082, ADR-083): the Trigger declares inputs, the Output declares outputs, the node
that runs the action maps the inputs, the reference list names a node by its id and shows its name, and one definition placed more than
once in a stage is numbered."""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import eventually
from tests.helpers import connect, graph_url, kind_of, node, post

DIALOG = "#node-modal"


def _config(api: httpx.Client, graph: dict[str, Any], kind: str) -> dict[str, Any]:
    nodes = api.get(graph_url(graph)).json()["nodes"]
    return next(n["config"] for n in nodes if n["kind"] == kind)


def _open_settings(page: Page, action: dict[str, Any]) -> None:
    """The settings of an action node in a pipeline: its context menu (a double click opens its definition)."""
    page.locator(f'.ge-node[data-node-id="{action["id"]}"]').click(
        button="right", position={"x": 30, "y": 5}
    )
    page.get_by_role("menuitem", name="Settings").click()


def _declared_action(api: httpx.Client, name: str = "Greet") -> dict[str, Any]:
    action = post(api, "/api/actions", name=name)
    api.patch(
        f"{graph_url(action)}/nodes/{kind_of(api, action, 'trigger')['id']}",
        json={
            "config": {
                "inputs": [
                    {"name": "who", "type": "text", "required": True, "description": "The person"},
                    {"name": "times", "type": "number", "required": False, "default": "2"},
                ]
            }
        },
    ).raise_for_status()
    return action


def test_the_trigger_has_a_window_with_the_inputs_and_a_default_is_saved_at_once(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = post(api, "/api/actions", name="Inputs")
    page.goto(f"{base_url}/actions/{action['slug']}")
    page.locator(".ge-node--trigger").dblclick(position={"x": 20, "y": 5})
    dialog = page.locator(DIALOG)
    expect(dialog).to_be_visible()
    expect(dialog.get_by_text("Inputs", exact=True).first).to_be_visible()
    dialog.locator(".sf__add").click()
    name = dialog.get_by_label("Name of field 1")
    name.fill("who")
    name.press("Enter")
    default = dialog.locator(".sf__extra")
    default.fill("Ann")
    default.press("Enter")
    eventually(
        lambda: _config(api, action, "trigger")["inputs"],
        [{"name": "who", "type": "text", "required": False, "description": "", "default": "Ann"}],
    )


def test_the_output_has_a_list_of_outputs_with_a_value_and_no_required_box(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = post(api, "/api/actions", name="Outputs")
    page.goto(f"{base_url}/actions/{action['slug']}")
    page.locator(".ge-node--output").dblclick(position={"x": 30, "y": 5})
    dialog = page.locator(DIALOG)
    dialog.locator(".sf__add").click()
    expect(
        dialog.locator(".sf__required")
    ).to_be_hidden()  # an output is worked out at the end: it is not "required"
    expect(dialog.locator(".sf__type option[value=choice]")).to_have_count(0)
    name = dialog.get_by_label("Name of field 1")
    name.fill("greeting")
    name.press("Enter")
    value = dialog.locator(".sf__extra")
    value.fill("Hello ${input.who}")
    value.press("Enter")
    eventually(
        lambda: [(o["name"], o.get("value")) for o in _config(api, action, "output")["outputs"]],
        [("greeting", "Hello ${input.who}")],
    )


def test_the_node_that_runs_an_action_has_one_row_per_input_and_saves_the_mapping(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _declared_action(api)
    pipeline = post(api, "/api/pipelines", name="Flow")
    stage = node(api, pipeline, "stage", name="Stage")
    connect(api, pipeline, kind_of(api, pipeline, "trigger"), "out", stage, "start")
    action = node(api, pipeline, "action", stage_id=stage["id"], x=24, y=48)
    api.patch(
        f"{graph_url(pipeline)}/nodes/{action['id']}", json={"definition_id": definition["id"]}
    ).raise_for_status()
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    _open_settings(page, action)
    dialog = page.locator(DIALOG)
    who = dialog.get_by_label(re.compile(r"^who"))
    expect(who).to_be_visible()
    expect(dialog.get_by_label(re.compile(r"^times"))).to_have_attribute(
        "placeholder", "Default: 2"
    )
    expect(dialog.locator(".ge-mapping__required")).to_have_count(1)  # only "who" is required
    who.fill("${card.title}")
    who.press("Enter")
    eventually(lambda: _config(api, pipeline, "action")["input_values"], {"who": "${card.title}"})


def test_an_action_without_inputs_shows_no_mapping(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    plain = post(api, "/api/actions", name="Plain")
    pipeline = post(api, "/api/pipelines", name="Flow plain")
    stage = node(api, pipeline, "stage", name="Stage")
    connect(api, pipeline, kind_of(api, pipeline, "trigger"), "out", stage, "start")
    action = node(api, pipeline, "action", stage_id=stage["id"], x=24, y=48)
    api.patch(
        f"{graph_url(pipeline)}/nodes/{action['id']}", json={"definition_id": plain["id"]}
    ).raise_for_status()
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    _open_settings(page, action)
    expect(page.locator(DIALOG)).to_be_visible()
    expect(page.locator(".ge-mapping")).to_have_count(0)


def test_the_same_action_placed_three_times_is_told_apart_by_its_number(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = post(api, "/api/actions", name="Check")
    pipeline = post(api, "/api/pipelines", name="Flow numbers")
    stage = node(api, pipeline, "stage", name="Stage")
    connect(api, pipeline, kind_of(api, pipeline, "trigger"), "out", stage, "start")
    for i in range(3):
        action = node(api, pipeline, "action", stage_id=stage["id"], x=24 + i * 10, y=48 + i * 80)
        api.patch(
            f"{graph_url(pipeline)}/nodes/{action['id']}", json={"definition_id": definition["id"]}
        ).raise_for_status()
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    names = page.locator(".ge-node--action .ge-node__name")
    expect(names).to_have_count(3)
    assert sorted(names.all_inner_texts()) == ["Check #1", "Check #2", "Check #3"]


def test_the_reference_list_inserts_the_id_and_shows_the_name_and_a_rename_changes_nothing(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = post(api, "/api/actions", name="Refs")
    fetch = node(api, action, "http", name="Fetch", config={"url": "http://example.test/a"})
    reader = node(api, action, "http", name="Reader", config={"url": "http://example.test/b"})
    connect(api, action, kind_of(api, action, "trigger"), "out", fetch, "in")
    connect(api, action, fetch, "pass", reader, "in")
    page.goto(f"{base_url}/actions/{action['slug']}")
    page.locator(f'.ge-node[data-node-id="{reader["id"]}"]').dblclick(position={"x": 30, "y": 5})
    field = page.locator(DIALOG).get_by_label("URL")
    field.fill("http://example.test/${")
    option = page.locator(".popover--suggest").get_by_text("(Fetch).", exact=False).first
    expect(option).to_be_visible()  # the list shows the name, not an id
    option.click()
    page.locator(".popover--suggest").get_by_text("(Fetch).output").click()
    field.press("Enter")
    stored = f"http://example.test/${{node:{fetch['id']}.output}}"
    eventually(
        lambda: [
            n["config"]["url"]
            for n in api.get(graph_url(action)).json()["nodes"]
            if n["id"] == reader["id"]
        ],
        [stored],
    )
    expect(page.locator(DIALOG).locator("[data-references]:not([hidden])")).to_have_text(
        "Reads: http://example.test/${(Fetch).output}"
    )
    api.patch(
        f"{graph_url(action)}/nodes/{fetch['id']}", json={"name": "Download"}
    ).raise_for_status()
    page.reload()
    page.locator(f'.ge-node[data-node-id="{reader["id"]}"]').dblclick(position={"x": 30, "y": 5})
    expect(page.locator(DIALOG).locator("[data-references]:not([hidden])")).to_have_text(
        "Reads: http://example.test/${(Download).output}"
    )  # the text still holds the id; the name shown is the new one
    assert (
        next(n for n in api.get(graph_url(action)).json()["nodes"] if n["id"] == reader["id"])[
            "config"
        ]["url"]
        == stored
    )


def test_a_duplicated_stage_reads_its_own_copy_of_the_action_before_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _declared_action(api)
    pipeline = post(api, "/api/pipelines", name="Flow copy")
    stage = node(api, pipeline, "stage", name="Stage")
    connect(api, pipeline, kind_of(api, pipeline, "trigger"), "out", stage, "start")
    first = node(api, pipeline, "action", stage_id=stage["id"], x=24, y=48)
    second = node(api, pipeline, "action", stage_id=stage["id"], x=24, y=140)
    for action in (first, second):
        api.patch(
            f"{graph_url(pipeline)}/nodes/{action['id']}",
            json={"definition_id": definition["id"]},
        ).raise_for_status()
    connect(api, pipeline, stage, "start", first, "in")
    connect(api, pipeline, first, "pass", second, "in")
    api.patch(
        f"{graph_url(pipeline)}/nodes/{second['id']}",
        json={"config": {"input_values": {"who": f"${{node:{first['id']}.data.greeting}}"}}},
    ).raise_for_status()
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    page.locator(".ge-node--stage .ge-stage__header").click(position={"x": 80, "y": 20})
    page.keyboard.press("Control+d")
    expect(page.locator(".ge-node--stage")).to_have_count(2)
    expect(page.locator(".ge-node--action")).to_have_count(4)

    def copies() -> list[dict[str, Any]]:
        nodes = api.get(graph_url(pipeline)).json()["nodes"]
        return [
            n for n in nodes if n["kind"] == "action" and n["id"] not in (first["id"], second["id"])
        ]

    eventually(
        lambda: (
            len(copies()) == 2
            and all(n["config"].get("input_values") is not None for n in copies())
        ),
        True,
    )
    mapped = [n for n in copies() if n["config"]["input_values"]]
    assert len(mapped) == 1
    copied_first = next(n for n in copies() if n is not mapped[0] and n["id"] != mapped[0]["id"])
    assert mapped[0]["config"]["input_values"]["who"] == (
        f"${{node:{copied_first['id']}.data.greeting}}"
    )  # the copy of the second reads the copy of the first, not the original
    original = next(
        n for n in api.get(graph_url(pipeline)).json()["nodes"] if n["id"] == second["id"]
    )
    assert original["config"]["input_values"]["who"] == f"${{node:{first['id']}.data.greeting}}"
