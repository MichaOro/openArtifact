"""Agents in the browser: the providers page, the page of an agent, the agent node's inspector and the
request of an agent step. The server has an access token and a secret key (so that an API key can be
stored) and may reach the local stand-in for a provider."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.agent_support import API_KEY, HEADERS, TOKEN, FakeLlm, completion, fake_llm
from tests.e2e.conftest import _serve
from tests.e2e.helpers import eventually
from tests.helpers import build_pipeline, connect, graph_url, kind_of, node, wait_until


@pytest.fixture(scope="module")
def agents_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    yield from _serve(
        tmp_path_factory.mktemp("agents"),
        api_token=TOKEN,
        secret_key="k" * 40,
    )


@pytest.fixture(scope="module")
def llm() -> Iterator[FakeLlm]:
    with fake_llm() as server:
        yield server


@pytest.fixture
def api(agents_url: str, llm: FakeLlm) -> Iterator[httpx.Client]:
    """REST client on a server without artifacts, graphs, agents and providers."""
    llm.script.clear()
    llm.hits.clear()
    with httpx.Client(base_url=agents_url, headers=HEADERS, timeout=30) as client:
        for task in client.get("/api/tasks").json():
            client.post(f"/api/tasks/{task['id']}/run/stop")
            assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
        for path in ("/api/pipelines", "/api/actions", "/api/agents", "/api/providers"):
            for item in client.get(path).json():
                if path == "/api/providers":
                    client.patch(f"{path}/{item['id']}", json={"is_default": False})
                assert client.delete(f"{path}/{item['id']}").status_code == 204, path
        yield client


@pytest.fixture
def signed_in(page: Page, agents_url: str) -> Page:
    page.goto(f"{agents_url}/login")
    page.fill("#token", TOKEN)
    page.click("button[type=submit]")
    expect(page.locator(".lane")).to_have_count(3)
    return page


def _provider(api: httpx.Client, llm: FakeLlm) -> dict[str, Any]:
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
    response = api.post("/api/providers", json=body)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def _agent(api: httpx.Client, **draft: Any) -> dict[str, Any]:
    config = {
        "user_prompt": "Analyse: ${input.ticket}",
        "inputs": [{"name": "ticket", "required": True}, {"name": "tone", "default": "neutral"}],
        "temperature": 0.2,
        **draft,
    }
    agent = api.post("/api/agents", json={"name": "Triage", "draft": config}).json()
    return api.post(f"/api/agents/{agent['id']}/publish").json()["agent"]  # type: ignore[no-any-return]


# ── providers ────────────────────────────────────────────────────────


def test_a_provider_is_tested_and_saved_and_its_models_are_switched_on(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    page = signed_in
    page.goto(f"{agents_url}/settings/providers")
    expect(page.locator("[data-provider-empty]")).to_be_visible()
    expect(page.locator('.nav-link[aria-current="page"]')).to_have_text("LLM providers")
    page.click("[data-new-provider]")
    dialog = page.locator("#provider-modal")
    dialog.get_by_label("Kind").select_option("openai_compatible")
    dialog.locator("#pv-name").fill("Local")
    expect(dialog.locator("[data-http-warning]")).to_be_hidden()
    expect(dialog.locator("[data-http-confirm]")).to_be_hidden()
    dialog.get_by_label("Base URL").fill("https://llm.example/v1")
    expect(dialog.locator("[data-http-confirm]")).to_be_hidden()  # https needs no confirmation
    dialog.get_by_label("Base URL").fill(llm.url())
    expect(
        dialog.locator("[data-http-warning]")
    ).to_be_visible()  # http: a clear warning, not a refusal
    dialog.get_by_label("Secret with the API key").fill("LLM_KEY")
    dialog.get_by_label(re.compile("^API key")).fill(API_KEY)
    expect(
        dialog.locator("[data-http-confirm]")
    ).to_be_visible()  # only an http address asks for it
    dialog.get_by_text("Allow unencrypted connection (HTTP)").click()
    dialog.locator("[data-test]").click()
    steps = dialog.locator(".ag-check-step")
    expect(steps).to_have_text(
        ["✓ Secret LLM_KEY is stored", "✓ /models lists 2 models in the OpenAI format"]
    )
    assert api.get("/api/providers").json() == []  # the test saved nothing but the key
    expect(dialog.get_by_label(re.compile("^API key"))).to_have_value("")
    dialog.locator("[data-submit]").click()
    expect(dialog).to_be_hidden()
    card = page.locator(".ag-provider")
    expect(card).to_have_count(1)
    expect(card.locator(".ag-provider__name")).to_have_text("Local")
    expect(card.get_by_text("Connection tested")).to_be_visible()
    expect(card.locator(".ag-warning")).to_contain_text("The address uses http")
    expect(card).not_to_contain_text(API_KEY)
    card.locator(".ag-models > summary").click()
    rows = card.locator(".ag-model")
    expect(rows).to_have_count(2)
    card.get_by_label("Use model small").check()
    eventually(
        lambda: [
            m["model_id"] for m in api.get("/api/providers").json()[0]["models"] if m["enabled"]
        ],
        ["small"],
    )
    card = page.locator(".ag-provider")
    expect(card.locator(".ag-models")).to_have_attribute(
        "open", ""
    )  # the list stays open after the reload
    card.get_by_label("Make small the default model").click()
    eventually(lambda: api.get("/api/providers").json()[0]["default_model"], "small")
    expect(page.locator('.ag-model[data-model-id="small"]')).to_contain_text("Default")
    assert api.get("/api/secrets").json()[0]["name"] == "LLM_KEY"


def test_a_provider_that_is_not_compatible_is_not_saved(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    page = signed_in
    page.goto(f"{agents_url}/settings/providers")
    page.click("[data-new-provider]")
    dialog = page.locator("#provider-modal")
    dialog.get_by_label("Kind").select_option("openai_compatible")
    dialog.locator("#pv-name").fill("A web page")
    dialog.get_by_label("Base URL").fill(llm.url("/html"))
    dialog.get_by_text("Allow unencrypted connection (HTTP)").click()
    dialog.get_by_label(re.compile("^Models defined by hand")).fill("some-model")
    dialog.locator("[data-submit]").click()
    expect(dialog.locator("[data-form-error]")).to_contain_text("The connection test failed")
    expect(dialog).to_be_visible()
    assert api.get("/api/providers").json() == []


# ── the page of an agent ─────────────────────────────────────────────


def test_an_agent_is_written_published_previewed_and_rolled_back(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    page = signed_in
    page.goto(f"{agents_url}/agents")
    page.click("[data-new-agent]")
    page.locator("#name-modal-field-name").fill("Triage")
    page.locator("#name-modal [data-submit]").click()
    expect(page).to_have_url(re.compile(r"/agents/[0-9a-f-]{36}$"))
    editor = page.locator("[data-agent-editor]")
    expect(editor.locator("[data-agent-name]")).to_have_text("Triage")
    expect(editor.locator("[data-chips]")).to_contain_text("Not published")
    editor.locator("[data-add-input]").click()
    row = editor.locator(".ag-input")
    row.get_by_label("Name", exact=True).fill("ticket")
    row.get_by_text("Required").click()
    expect(row.get_by_label("Default")).to_be_disabled()  # a required input has no default
    editor.get_by_label("User prompt").fill("Analyse: ${input.ticket} and ${input.missing}")
    editor.locator("[data-save]").click()
    expect(editor.locator("[data-problems] li")).to_have_text(
        ["User prompt: ${input.missing} is not a declared input"]
    )
    editor.locator("[data-publish]").click()
    expect(editor.locator("[data-save-error]")).to_contain_text("is not a declared input")
    editor.get_by_label("User prompt").fill("Analyse: ${input.ticket}")
    editor.locator("[data-publish]").click()
    expect(editor.locator("[data-notice]")).to_contain_text("Published as version 1")
    expect(editor.locator("[data-chips]")).to_contain_text("v1 published")
    expect(editor.locator("[data-versions] .ag-row")).to_have_count(1)
    expect(editor.locator("[data-draft-state]")).to_have_text(
        "The draft equals the published version 1."
    )

    # the preview fills the prompt with an example and sends nothing
    llm.hits.clear()
    editor.get_by_label("Example for ticket").fill("T-42")
    editor.locator("[data-preview]").click()
    result = editor.locator("[data-preview-result]")
    expect(result.get_by_label("User prompt")).to_have_text("Analyse: T-42")
    expect(result).to_contain_text("Provider: Local · Model: small")
    expect(result.get_by_label("System prompt")).to_have_count(0)  # switched off: not shown
    assert llm.hits == []

    # a second version, then back to the first: a third one with the first one's content
    editor.locator('[data-field="system_prompt_enabled"]').click()
    editor.get_by_label("System prompt", exact=True).fill("Be brief.")
    expect(editor.locator("[data-draft-state]")).to_contain_text("not saved yet")
    editor.locator("[data-publish]").click()
    expect(editor.locator("[data-notice]")).to_contain_text("Published as version 2")
    expect(editor.locator("[data-notice]")).to_contain_text(
        "Changed: Use a system prompt, System prompt."
    )
    editor.get_by_label("Publish version 1 again").click()
    page.locator("#confirm-modal [data-confirm]").click()
    expect(editor.locator("[data-notice]")).to_contain_text(
        "Version 1 is published again as version 3"
    )
    rows = editor.locator("[data-versions] .ag-row")
    expect(rows).to_have_count(3)
    expect(rows.nth(0)).to_contain_text("rollback to version 1")
    expect(rows.nth(0)).to_contain_text("In use")
    agent = api.get("/api/agents").json()[0]
    assert agent["published_number"] == 3
    assert (
        api.get(f"/api/agents/{agent['id']}").json()["published"]["system_prompt_enabled"] is False
    )

    # inactive, and back in the list
    editor.locator("[data-active]").click()
    expect(editor.locator("[data-chips]")).to_contain_text("Inactive")
    page.goto(f"{agents_url}/agents")
    item = page.locator(".ag-item")
    expect(item.locator(".ge-item__name")).to_have_text("Triage")
    expect(item.locator("[data-chips]")).to_contain_text("Inactive")
    expect(item.locator("[data-chips]")).to_contain_text("v3 published")


# ── the node ─────────────────────────────────────────────────────────


def test_the_inspector_shows_what_is_inherited_and_what_the_node_overrides(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    agent = _agent(api)
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    page = signed_in
    page.goto(f"{agents_url}/actions/{action['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.click("[data-add-menu]")
    page.click("[data-add=agent]")
    card = page.locator(".ge-node--agent")
    expect(card.locator(".ge-node__kind")).to_have_text("no agent yet")
    inspector = page.locator(".ge-inspector")
    inspector.get_by_label("Agent", exact=True).select_option(agent["id"])
    expect(inspector.locator(".ag-node__status")).to_contain_text("Runs version 1")
    expect(inspector.locator(".ag-problems li")).to_have_text(
        ["required input 'ticket' is not mapped"]
    )
    expect(card.locator(".ge-node__kind")).to_have_text("Triage")

    inspector.get_by_label("ticket * (string)").fill("${var.ticket}")
    inspector.get_by_label("ticket * (string)").press("Enter")
    expect(inspector.locator(".ag-problems")).to_have_count(0)

    def stored() -> dict[str, Any]:
        nodes = api.get(graph_url(action)).json()["nodes"]
        return next(n for n in nodes if n["kind"] == "agent")["config"]  # type: ignore[no-any-return]

    eventually(lambda: stored()["inputs"], "ticket = ${var.ticket}")

    temperature = inspector.locator('.ag-override[data-setting="temperature"]')
    expect(temperature).to_have_attribute("data-overridden", "false")
    expect(temperature.locator(".ag-chip")).to_have_text("From agent")
    expect(temperature.locator(".ag-override__inherited")).to_have_text("0.2")
    temperature.get_by_label("Override Temperature in this node").click()
    expect(temperature).to_have_attribute("data-overridden", "true")
    expect(temperature.locator(".ag-chip")).to_have_text("Overridden")
    eventually(lambda: stored()["temperature"], 0.2)  # it starts as a copy of the agent's value
    temperature.get_by_label("Temperature", exact=True).fill("1.5")
    temperature.get_by_label("Temperature", exact=True).press("Enter")
    eventually(lambda: stored()["temperature"], 1.5)
    expect(temperature.locator(".ag-override__inherited")).to_have_text("Agent: 0.2")

    # a value the agent does not set can be switched on by the node
    tokens = inspector.locator('.ag-override[data-setting="max_tokens"]')
    expect(tokens.locator(".ag-override__inherited")).to_have_text("not set")
    tokens.get_by_label("Override Max tokens in this node").click()
    tokens.get_by_label("Max tokens", exact=True).fill("9000")
    tokens.get_by_label("Max tokens", exact=True).press("Enter")
    expect(tokens.locator(".field__error")).to_contain_text("must be 1 to 8192")
    tokens.get_by_label("Max tokens", exact=True).fill("64")
    tokens.get_by_label("Max tokens", exact=True).press("Enter")
    eventually(lambda: stored()["max_tokens"], 64)
    expect(card.locator(".ge-node__kind")).to_have_text("Triage · 2 overrides")

    # a change of the agent reaches the fields the node does not override, and only those
    api.put(
        f"/api/agents/{agent['id']}/draft",
        json={**agent["draft"], "temperature": 0.9, "retries": 1},
    )
    api.post(f"/api/agents/{agent['id']}/publish").raise_for_status()
    page.reload()
    page.locator(".ge-node--agent").click(position={"x": 30, "y": 5})
    inspector = page.locator(".ge-inspector")
    expect(
        inspector.locator('.ag-override[data-setting="retries"] .ag-override__inherited')
    ).to_have_text("1")
    temperature = inspector.locator('.ag-override[data-setting="temperature"]')
    expect(temperature.get_by_label("Temperature", exact=True)).to_have_value("1.5")
    expect(temperature.locator(".ag-override__inherited")).to_have_text("Agent: 0.9")

    temperature.get_by_label("Reset Temperature to the agent's value").click()
    eventually(lambda: stored()["temperature"], None)
    expect(inspector.locator('.ag-override[data-setting="temperature"]')).to_have_attribute(
        "data-overridden", "false"
    )
    inspector.get_by_text("Reset all 1 overrides").click()
    eventually(lambda: stored()["max_tokens"], None)
    expect(page.locator(".ge-node--agent .ge-node__kind")).to_have_text("Triage")


def test_the_request_of_an_agent_step_is_shown_with_its_attempts(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    agent = _agent(api, system_prompt_enabled=True, system_prompt="Be brief.", retries=1)
    action = api.post("/api/actions", json={"name": "Answer"}).json()
    trigger, output = kind_of(api, action, "trigger"), kind_of(api, action, "output")
    for edge in api.get(graph_url(action)).json()["edges"]:
        api.delete(f"{graph_url(action)}/edges/{edge['id']}")
    ask = node(
        api,
        action,
        "agent",
        name="Ask",
        config={
            "agent_id": agent["id"],
            "inputs": "ticket = Login is broken",
            "request_timeout_seconds": 5,
        },
    )
    connect(api, action, trigger, "out", ask, "in")
    connect(api, action, ask, "pass", output, "pass")
    pipeline = build_pipeline(api, stages=1)
    api.patch(
        f"{graph_url(pipeline)}/nodes/{pipeline['stages'][0][1]['id']}",
        json={"definition_id": action["id"]},
    )
    llm.script = [
        (429, {"error": {"message": "slow down"}}, {"Retry-After": "0"}),
        (200, completion("Reset the password.")),
    ]
    task = api.post("/api/tasks", json={"title": "Item", "status": "backlog"}).json()
    api.post(
        f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]}
    ).raise_for_status()
    run = wait_until(
        lambda: next(r for r in api.get("/api/runs").json() if r["task_id"] == task["id"]),
        lambda r: r["status"] == "done",
        timeout=30,
    )
    page = signed_in
    page.goto(f"{agents_url}/artifacts/{task['number']}/executions/{run['execution_id']}")
    page.get_by_label("Open Answer").click()  # into the action: its nodes are the steps
    page.locator("[data-node-id]", has_text="Ask").locator(".ef-path__main").click()
    step = page.locator("[data-panel-detail] .history-step")
    expect(step.locator("[data-step-facts]")).to_contain_text("Local: small")
    expect(step.locator("[data-step-facts]")).to_contain_text("18 tokens (11 in, 7 out)")
    expect(step.locator("[data-step-facts]")).to_contain_text("2 attempts")
    step.locator("[data-step-agent] > summary").click()
    detail = step.locator(".ag-detail")
    expect(detail.get_by_label("System prompt as sent")).to_have_text("Be brief.")
    expect(detail.get_by_label("User prompt as sent")).to_have_text("Analyse: Login is broken")
    expect(detail).to_contain_text("Agent: Triage (version 1)")
    expect(detail).to_contain_text("Set by the node itself: Request timeout (seconds)")
    attempts = detail.get_by_label("Attempts").locator("tbody tr")
    expect(attempts).to_have_count(2)
    expect(attempts.nth(0)).to_contain_text("HTTP 429: rate limited: slow down")
    expect(attempts.nth(1)).to_contain_text("Answered")
    inputs = detail.get_by_label("Inputs").locator("tbody tr")
    expect(inputs.nth(0)).to_contain_text("Login is broken")
    expect(inputs.nth(1)).to_contain_text("default")
    expect(page.locator("body")).not_to_contain_text(API_KEY)
