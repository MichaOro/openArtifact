"""The card as a source of the run in the browser (ADR-064): the picker, the inputs of an agent node (the ones that come
from the artifact are fixed rows, the others are mapped), the mapping end to end (the dialog, a reload, a run against
the fake model), the stale and the undeclared mapping line, and the standard rows of the artifact fields."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.agent_support import API_KEY, HEADERS, TOKEN, FakeLlm, fake_llm
from tests.e2e.conftest import _serve
from tests.e2e.helpers import eventually, pick_node
from tests.helpers import build_pipeline, graph_url, wait_until

BODY = 'First line\nSecond "line" with ${not.a.reference}'


@pytest.fixture(scope="module")
def card_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    yield from _serve(
        tmp_path_factory.mktemp("card"),
        api_token=TOKEN,
        secret_key="k" * 40,
        llm_allow_private_networks="true",
    )


@pytest.fixture(scope="module")
def llm() -> Iterator[FakeLlm]:
    with fake_llm() as server:
        yield server


@pytest.fixture
def api(card_url: str, llm: FakeLlm) -> Iterator[httpx.Client]:
    llm.script.clear()
    llm.hits.clear()
    with httpx.Client(base_url=card_url, headers=HEADERS, timeout=30) as client:
        for task in client.get("/api/tasks").json():
            client.post(f"/api/tasks/{task['id']}/run/stop")
            assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
        for path in ("/api/pipelines", "/api/actions", "/api/agents", "/api/providers"):
            for item in client.get(path).json():
                if path == "/api/providers":
                    client.patch(f"{path}/{item['id']}", json={"is_default": False})
                assert client.delete(f"{path}/{item['id']}").status_code == 204, path
        client.put("/api/artifact-fields", json={"fields": []})
        yield client


@pytest.fixture
def signed_in(page: Page, card_url: str) -> Page:
    page.goto(f"{card_url}/login")
    page.fill("#token", TOKEN)
    page.click("button[type=submit]")
    expect(page.locator(".lane")).to_have_count(3)
    return page


def _provider(api: httpx.Client, llm: FakeLlm) -> None:
    api.put("/api/secrets/LLM_KEY", json={"value": API_KEY}).raise_for_status()
    body = {
        "kind": "openai_compatible",
        "name": "Local",
        "base_url": llm.url(),
        "secret_name": "LLM_KEY",
        "allow_http": True,
        "default_model": "small",
        "is_default": True,
    }
    assert api.post("/api/providers", json=body).status_code == 201


def _agent(api: httpx.Client, inputs: list[dict[str, Any]], prompt: str) -> dict[str, Any]:
    made = api.post(
        "/api/agents", json={"name": "Epic", "draft": {"user_prompt": prompt, "inputs": inputs}}
    )
    assert made.status_code == 201, made.text
    published = api.post(f"/api/agents/{made.json()['id']}/publish")
    assert published.status_code == 200, published.text
    return published.json()["agent"]  # type: ignore[no-any-return]


def _open_agent_node(
    page: Page, card_url: str, action: dict[str, Any], agent: dict[str, Any]
) -> Any:
    page.goto(f"{card_url}/actions/{action['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.click("[data-add-menu]")
    pick_node(page, "agent")
    page.locator(".ge-node--agent").last.dblclick(position={"x": 30, "y": 5})
    inspector = page.locator(".ge-inspector")
    inspector.get_by_label("Agent", exact=True).select_option(agent["id"])
    expect(page.locator("#node-modal [data-node-version]")).to_have_text(re.compile(r"v\d+"))
    return inspector


def _reopen(page: Page, card_url: str, action: dict[str, Any]) -> Any:
    page.goto(f"{card_url}/actions/{action['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.locator(".ge-node--agent").first.dblclick(position={"x": 30, "y": 5})
    inspector = page.locator(".ge-inspector")
    expect(page.locator("#node-modal [data-node-version]")).to_have_text(re.compile(r"v\d+"))
    return inspector


def _mapping(api: httpx.Client, action: dict[str, Any]) -> str:
    nodes = api.get(graph_url(action)).json()["nodes"]
    return str(next(n for n in nodes if n["kind"] == "agent")["config"].get("inputs") or "")


# ── the picker ───────────────────────────────────────────────────────


def test_the_picker_offers_the_card_of_this_run_first_with_title_and_body(
    signed_in: Page, card_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    agent = _agent(api, [{"name": "t", "required": True}], "${input.t}")
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    inspector = _open_agent_node(signed_in, card_url, action, agent)
    field = inspector.get_by_label("Value for ${input.t}")
    field.click()
    field.fill("${")
    options = signed_in.locator(".popover--suggest [role=option]")
    expect(options.first).to_contain_text("card.")
    expect(options.first).to_contain_text("Card of this run")
    options.first.click()
    expect(signed_in.locator(".popover--suggest [role=option]").nth(0)).to_contain_text(
        "card.title"
    )
    expect(signed_in.locator(".popover--suggest [role=option]").nth(1)).to_contain_text("card.body")


# ── (e) the dialog: fixed rows, warnings, typo, reload ───────────────


def test_an_input_from_the_artifact_is_a_fixed_row_and_every_warning_follows_the_mapping(
    signed_in: Page, card_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    agent = _agent(
        api,
        [
            {"name": "epic", "source": "artifact", "part": "title_body"},
            {"name": "ticket", "required": True},
        ],
        "E=${input.epic}|T=${input.ticket}",
    )
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    page = signed_in
    inspector = _open_agent_node(page, card_url, action, agent)
    ticket = inspector.get_by_label("Value for ${input.ticket}")
    problems = inspector.locator(".ag-problems li")
    expect(inspector.locator(".ag-node__fixed")).to_have_count(
        0
    )  # the node does not list what the agent fixes
    expect(inspector.get_by_label("Value for ${input.epic}")).to_have_count(
        0
    )  # nothing to type: the agent fixes it
    assert _mapping(api, action) == ""  # and nothing was written into the node
    expect(problems).to_have_text(["required input 'ticket' is not mapped"])
    # mapped: the warning goes away; cleared: it comes back
    ticket.fill("${card.title}")
    ticket.press("Enter")
    expect(problems).to_have_count(0)
    ticket.fill("")
    ticket.press("Enter")
    expect(problems).to_have_text(["required input 'ticket' is not mapped"])
    # a typo in a card reference is told, naming what the artifact has
    ticket.fill("${card.titel}")
    ticket.press("Enter")
    expect(problems.first).to_contain_text(
        '${card.titel}: the artifact has no field "titel" (it has: title, body, text, number, id'
    )
    ticket.fill("Epic: ${card.title} / ${card.body}")
    ticket.press("Enter")
    expect(problems).to_have_count(0)
    assert _mapping(api, action) == "ticket = Epic: ${card.title} / ${card.body}"
    inspector = _reopen(page, card_url, action)
    expect(inspector.get_by_label("Value for ${input.ticket}")).to_have_value(
        "Epic: ${card.title} / ${card.body}"
    )
    expect(inspector.locator(".ag-node__fixed")).to_have_count(0)


def test_a_line_left_for_an_input_that_now_comes_from_the_artifact_is_shown_as_ignored_and_removable(
    signed_in: Page, card_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    agent = _agent(api, [{"name": "epic"}], "${input.epic}")
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    page = signed_in
    inspector = _open_agent_node(page, card_url, action, agent)
    inspector.get_by_label("Value for ${input.epic}").fill("typed once")
    inspector.get_by_label("Value for ${input.epic}").press("Enter")
    eventually(lambda: _mapping(api, action), "epic = typed once", page=page)
    # the agent now takes the artifact for this input: the line stays in the node but is ignored
    config = {
        "user_prompt": "${input.epic}",
        "inputs": [{"name": "epic", "source": "artifact", "part": "title"}],
    }
    api.put(f"/api/agents/{agent['id']}/draft", json=config).raise_for_status()
    api.post(f"/api/agents/{agent['id']}/publish").raise_for_status()
    inspector = _reopen(page, card_url, action)
    stale = inspector.locator(".ag-node__stale")
    expect(stale).to_have_count(1)
    expect(stale).to_contain_text("now comes from the artifact, this line is ignored")
    stale.get_by_role("button", name="Remove the mapping of epic").click()
    expect(inspector.locator(".ag-node__stale")).to_have_count(0)
    eventually(lambda: _mapping(api, action), "", page=page)


# ── (f) a mapping key the agent no longer declares ───────────────────


def test_a_mapping_key_the_agent_no_longer_declares_is_shown_with_a_remove_button(
    signed_in: Page, card_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    agent = _agent(api, [{"name": "t", "required": True}], "T=${input.t}")
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    page = signed_in
    inspector = _open_agent_node(page, card_url, action, agent)
    field = inspector.get_by_label("Value for ${input.t}")
    field.fill("${card.title}")
    field.press("Enter")
    # the save of the field must have landed before the second writer comes, else it overwrites it (a wrong order)
    eventually(lambda: _mapping(api, action), "t = ${card.title}")
    page.wait_for_load_state(
        "networkidle"
    )  # no write of the dialog is still on its way when the second writer comes
    nodes = api.get(graph_url(action)).json()["nodes"]
    node = next(n for n in nodes if n["kind"] == "agent")
    api.patch(
        f"{graph_url(action)}/nodes/{node['id']}",
        json={"config": {"inputs": "t = ${card.title}\nold = ${card.body}"}},
    ).raise_for_status()
    inspector = _reopen(page, card_url, action)
    stale = inspector.locator(".ag-node__stale")
    expect(stale).to_have_count(1)
    expect(stale).to_contain_text("old")
    expect(inspector.locator(".ag-problems li")).to_have_text(
        ["input 'old' is not declared by the agent"]
    )
    stale.get_by_role("button", name="Remove the mapping of old").click()
    expect(inspector.locator(".ag-node__stale")).to_have_count(0)
    expect(inspector.locator(".ag-problems")).to_have_count(0)
    assert _mapping(api, action) == "t = ${card.title}"


# ── a run through the dialog's mapping, against the fake model ───────


def test_the_mapping_made_in_the_dialog_reaches_the_model_in_a_run_from_a_card(
    signed_in: Page, card_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    task = api.post("/api/tasks", json={"title": "Epic A", "body": BODY}).json()
    agent = _agent(
        api, [{"name": "epic", "source": "artifact", "part": "title_body"}], "Epic:\n${input.epic}"
    )
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    page = signed_in
    _open_agent_node(
        page, card_url, action, agent
    )  # the agent fixes the input: the node maps nothing
    expect(page.locator(".ge-inspector .ag-node__fixed")).to_have_count(0)
    nodes = api.get(graph_url(action)).json()
    trigger = next(n for n in nodes["nodes"] if n["kind"] == "trigger")
    output = next(n for n in nodes["nodes"] if n["kind"] == "output")
    ask = next(n for n in nodes["nodes"] if n["kind"] == "agent")
    for edge in nodes["edges"]:
        api.delete(f"{graph_url(action)}/edges/{edge['id']}")
    for source, port, target, to in ((trigger, "out", ask, "in"), (ask, "pass", output, "pass")):
        api.post(
            f"{graph_url(action)}/edges",
            json={
                "source_id": source["id"],
                "source_port": port,
                "target_id": target["id"],
                "target_port": to,
            },
        ).raise_for_status()
    pipeline = build_pipeline(api, stages=1)
    shell = pipeline["stages"][0][1]
    api.patch(
        f"{graph_url(pipeline)}/nodes/{shell['id']}", json={"definition_id": action["id"]}
    ).raise_for_status()
    llm.hits.clear()
    api.post(
        f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]}
    ).raise_for_status()
    wait_until(lambda: len(llm.completions()), lambda n: n == 1)
    asked = llm.completions()[0]["json"]["messages"][-1]["content"]
    assert asked == f"Epic:\n#{task['number']} Epic A\n\n{BODY}"


# ── the standard rows of the artifact fields ─────────────────────────


def test_the_fields_dialog_shows_title_and_body_as_standard_rows_and_names_a_clash(
    signed_in: Page, api: httpx.Client
) -> None:
    page = signed_in
    page.locator("[data-board-menu]").click()
    page.get_by_role("menuitem", name="Artifact fields").click()
    editor = page.locator("#fields-modal")
    rows = editor.locator(".af-standard__row")
    expect(rows).to_have_count(2)
    expect(rows.nth(0)).to_contain_text("Title")
    expect(rows.nth(0)).to_contain_text("${card.title}")
    expect(rows.nth(1)).to_contain_text("${card.body}")
    expect(rows.locator(".tag")).to_have_text(["Standard", "Standard"])
    assert not rows.locator("button").count()  # nothing to change, remove or reorder
    editor.locator("[data-add-first]").click()
    editor.locator("[data-key=label]").fill("Title")
    expect(editor.locator("[data-key=name]")).to_have_value(re.compile(r"^title_field$"))


# ── (h) custom fields in the picker and a stale reference ────────────

FIELDS = [
    {"name": "epic_url", "label": "Epic URL", "kind": "text"},
    {"name": "priority", "label": "Priority", "kind": "number"},
    {"name": "needs_review", "label": "Needs review", "kind": "boolean"},
    {"name": "repo", "label": "Repo", "kind": "choice", "options": ["api", "web"]},
]


def test_every_custom_field_is_offered_in_the_card_group_and_a_new_one_without_a_reload(
    signed_in: Page, card_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    api.put("/api/artifact-fields", json={"fields": FIELDS}).raise_for_status()
    agent = _agent(api, [{"name": "t", "required": True}], "${input.t}")
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    page = signed_in
    inspector = _open_agent_node(page, card_url, action, agent)
    field = inspector.get_by_label("Value for ${input.t}")
    field.click()
    field.fill("${card.")
    options = page.locator(".popover--suggest [role=option]")
    expect(options).to_have_count(4 + len(FIELDS))
    for name in ("epic_url", "priority", "needs_review", "repo"):
        expect(page.locator(".popover--suggest")).to_contain_text(f"card.{name}")
    # a field defined while the editor is open shows up the next time the picker opens
    api.put(
        "/api/artifact-fields",
        json={"fields": [*FIELDS, {"name": "due_2026", "label": "Due", "kind": "text"}]},
    ).raise_for_status()
    page.keyboard.press("Escape")
    page.wait_for_timeout(1100)  # the list is fetched again at most once a second
    field.fill("")
    field.click()
    field.fill("${card.due")
    expect(page.locator(".popover--suggest")).to_contain_text("card.due_2026")


def test_a_field_deleted_after_it_was_mapped_is_named_in_the_dialog(
    signed_in: Page, card_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    api.put("/api/artifact-fields", json={"fields": FIELDS}).raise_for_status()
    agent = _agent(api, [{"name": "t", "required": True}], "${input.t}")
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    page = signed_in
    inspector = _open_agent_node(page, card_url, action, agent)
    field = inspector.get_by_label("Value for ${input.t}")
    field.fill("${card.epic_url}")
    field.press("Enter")
    expect(inspector.locator(".ag-problems")).to_have_count(0)
    api.put("/api/artifact-fields", json={"fields": FIELDS[1:]}).raise_for_status()
    inspector = _reopen(page, card_url, action)
    expect(inspector.locator(".ag-problems li").first).to_contain_text(
        '${card.epic_url}: the artifact has no field "epic_url"'
    )
    expect(inspector.get_by_label("Value for ${input.t}")).to_have_value(
        "${card.epic_url}"
    )  # nothing is dropped silently
