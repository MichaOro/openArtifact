"""The card as a source of the run in the browser (ADR-064): the picker, the pre-filled artifact input of an agent, the
input mapping of an agent node end to end (the dialog, a reload, a run against the fake model), the resolved preview,
the stale mapping key, and the standard rows of the artifact fields."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.agent_support import API_KEY, HEADERS, TOKEN, FakeLlm, fake_llm
from tests.e2e.conftest import _serve
from tests.e2e.helpers import pick_node
from tests.helpers import build_pipeline, graph_url, node, wait_until

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
    expect(inspector.locator(".ag-node__status")).to_contain_text("Runs version")
    return inspector


def _reopen(page: Page, card_url: str, action: dict[str, Any]) -> Any:
    page.goto(f"{card_url}/actions/{action['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.locator(".ge-node--agent").first.dblclick(position={"x": 30, "y": 5})
    inspector = page.locator(".ge-inspector")
    expect(inspector.locator(".ag-node__status")).to_contain_text("Runs version")
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
    field = inspector.get_by_label("t * (string)")
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


# ── (e) the dialog: pre-fill, warnings, typo, reload, second node ────


def test_an_artifact_input_is_pre_filled_and_every_warning_follows_the_mapping(
    signed_in: Page, card_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    agent = _agent(
        api,
        [
            {"name": "epic", "type": "artifact", "required": True},
            {"name": "ticket", "required": True},
        ],
        "E=${input.epic}|T=${input.ticket}",
    )
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    page = signed_in
    inspector = _open_agent_node(page, card_url, action, agent)
    epic, ticket = (
        inspector.get_by_label("epic * (artifact)"),
        inspector.get_by_label("ticket * (string)"),
    )
    problems = inspector.locator(".ag-problems li")
    expect(epic).to_have_value("${card.text}")  # the card of the run, there without being asked for
    expect(epic).to_have_attribute("placeholder", "Defaults to ${card.text}")
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
    # an artifact input cleared on purpose stays empty (an error: required and empty), also after a reload
    epic.fill("")
    epic.press("Enter")
    expect(problems).to_have_text(["required input 'epic' is empty"])
    inspector = _reopen(page, card_url, action)
    expect(inspector.get_by_label("epic * (artifact)")).to_have_value("")
    expect(inspector.get_by_label("ticket * (string)")).to_have_value(
        "Epic: ${card.title} / ${card.body}"
    )
    expect(inspector.locator(".ag-problems li")).to_have_text(["required input 'epic' is empty"])
    inspector.get_by_label("epic * (artifact)").fill("${card.body}")
    inspector.get_by_label("epic * (artifact)").press("Enter")
    expect(inspector.locator(".ag-problems")).to_have_count(0)
    assert (
        _mapping(api, action) == "epic = ${card.body}\nticket = Epic: ${card.title} / ${card.body}"
    )
    inspector = _reopen(page, card_url, action)
    expect(inspector.get_by_label("epic * (artifact)")).to_have_value("${card.body}")
    # a second node of the same agent gets its own pre-fill
    node(api, action, "agent", name="Second", x=700, y=420)
    page.goto(f"{card_url}/actions/{action['slug']}")
    page.locator(".ge-node--agent", has_text="Second").dblclick(position={"x": 30, "y": 5})
    second = page.locator(".ge-inspector")
    second.get_by_label("Agent", exact=True).select_option(agent["id"])
    expect(second.get_by_label("epic * (artifact)")).to_have_value("${card.text}")


# ── (f) a mapping key the agent no longer declares ───────────────────


def test_a_mapping_key_the_agent_no_longer_declares_is_shown_with_a_remove_button(
    signed_in: Page, card_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    agent = _agent(api, [{"name": "t", "required": True}], "T=${input.t}")
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    page = signed_in
    inspector = _open_agent_node(page, card_url, action, agent)
    field = inspector.get_by_label("t * (string)")
    field.fill("${card.title}")
    field.press("Enter")
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


# ── the resolved preview ─────────────────────────────────────────────


def test_a_field_with_references_shows_what_it_becomes_with_the_chosen_card(
    signed_in: Page, card_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    task = api.post(
        "/api/tasks", json={"title": "Der letzte Leuchtturm", "body": "A body line"}
    ).json()
    agent = _agent(api, [{"name": "t", "required": True}], "T=${input.t}")
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    page = signed_in
    inspector = _open_agent_node(page, card_url, action, agent)
    field = inspector.get_by_label("t * (string)")
    field.fill("Epic: ${card.title} / ${card.body} / ${(Fetch).output} / ${var.x}")
    field.press("Enter")
    expect(
        inspector.locator(".field__preview")
    ).to_be_hidden()  # no card chosen: nothing is resolved
    box = inspector.get_by_label("Preview with card")
    box.click()
    box.fill(str(task["number"]))
    page.locator(".combobox__list [role=option]").first.click()
    preview = inspector.locator(".field__preview").first
    expect(preview).to_have_text(
        "Epic: Der letzte Leuchtturm / A body line / \u2039output of Fetch\u203a / \u2039variable x\u203a"
    )
    expect(preview).to_have_attribute("data-state", "ok")
    field.fill("${card.titel}")
    field.press("Enter")
    expect(preview).to_contain_text("Not resolved: card.titel")
    # the artifact itself is untouched by a preview
    assert api.get(f"/api/tasks/{task['id']}").json()["body"] == "A body line"


# ── a run through the dialog's mapping, against the fake model ───────


def test_the_mapping_made_in_the_dialog_reaches_the_model_in_a_run_from_a_card(
    signed_in: Page, card_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    task = api.post("/api/tasks", json={"title": "Epic A", "body": BODY}).json()
    agent = _agent(
        api, [{"name": "epic", "type": "artifact", "required": True}], "Epic:\n${input.epic}"
    )
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    page = signed_in
    _open_agent_node(page, card_url, action, agent)  # the dialog pre-fills the mapping
    expect(page.locator(".ge-inspector").get_by_label("epic * (artifact)")).to_have_value(
        "${card.text}"
    )
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
    field = inspector.get_by_label("t * (string)")
    field.click()
    field.fill("${card.")
    options = page.locator(".popover--suggest [role=option]")
    expect(options).to_have_count(5 + len(FIELDS))
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
    field = inspector.get_by_label("t * (string)")
    field.fill("${card.epic_url}")
    field.press("Enter")
    expect(inspector.locator(".ag-problems")).to_have_count(0)
    api.put("/api/artifact-fields", json={"fields": FIELDS[1:]}).raise_for_status()
    inspector = _reopen(page, card_url, action)
    expect(inspector.locator(".ag-problems li").first).to_contain_text(
        '${card.epic_url}: the artifact has no field "epic_url"'
    )
    expect(inspector.get_by_label("t * (string)")).to_have_value(
        "${card.epic_url}"
    )  # nothing is dropped silently
