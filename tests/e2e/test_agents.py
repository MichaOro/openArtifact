"""Agents in the browser: the providers page, the page of an agent, the agent node's inspector and the
request of an agent step. The server has an access token and a secret key (so that an API key can be
stored) and may reach the local stand-in for a provider."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from playwright.sync_api import Locator, Page, expect

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
        llm_allow_private_networks="true",  # for the tools of agents (a provider needs no setting)
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


def _option(editor: Locator, key: str) -> None:
    """Flip an option of the agent editor's options panel (opened first when it is closed)."""
    panel = editor.locator("[data-options]")
    if panel.get_attribute("data-state") != "open":
        panel.locator("[data-options-toggle]").click()
    panel.locator(f'[data-option="{key}"] [role=switch]').click()


def _add_setting(editor: Locator, group: str, label: str) -> None:
    editor.locator(f'[data-settings="{group}"] [data-settings-add]').click()
    editor.page.get_by_role("menuitem", name=re.compile(rf"^{re.escape(label)}( ·|$)")).click()


def _tab(editor: Locator, name: str) -> None:
    editor.get_by_role("tab", name=name, exact=True).click()


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
    _option(editor, "inputs")
    _tab(editor, "Inputs")
    editor.locator("[data-add-input]").click()
    row = editor.locator(".ag-input")
    row.get_by_label("Name", exact=True).fill("ticket")
    row.get_by_label("Required", exact=True).select_option("required")
    expect(row.get_by_label("Default")).to_be_disabled()  # a required input has no default
    _tab(editor, "Prompts")
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
    expect(editor.locator("[data-versions] .ag-version")).to_have_count(1)
    expect(editor.locator("[data-draft-state]")).to_have_text(
        "The draft equals the published version 1."
    )

    # the preview fills the prompt with an example and sends nothing
    llm.hits.clear()
    _option(editor, "test")
    quick = editor.locator("[data-quick-test]")
    expect(quick).to_be_visible()  # a card on the right, not a tab
    expect(quick.get_by_label("Example for ticket")).to_have_attribute(
        "placeholder", "e.g. Login fails after the update"
    )  # a grey example of what goes in
    editor.get_by_label("Example for ticket").fill("T-42")
    editor.locator("[data-preview]").click()
    result = editor.locator("[data-preview-result]")
    expect(result.get_by_label("User prompt")).to_have_text("Analyse: T-42")
    expect(result).to_contain_text("Provider: Local · Model: small")
    expect(result.get_by_label("System prompt")).to_have_count(0)  # switched off: not shown
    assert llm.hits == []

    # a second version, then back to the first: a third one with the first one's content
    _option(editor, "system_prompt")
    _tab(editor, "Prompts")
    editor.get_by_role("textbox", name="System prompt").fill("Be brief.")
    expect(editor.locator("[data-draft-state]")).to_contain_text("not saved yet")
    editor.locator("[data-publish]").click()
    expect(editor.locator("[data-notice]")).to_contain_text("Published as version 2")
    expect(editor.locator("[data-notice]")).to_contain_text(
        "Changed: Use a system prompt, System prompt."
    )
    _tab(editor, "Versions & use")
    editor.get_by_label("Publish version 1 again").click()
    page.locator("#confirm-modal [data-confirm]").click()
    expect(editor.locator("[data-notice]")).to_contain_text(
        "Version 1 is published again as version 3"
    )
    rows = editor.locator("[data-versions] .ag-version")
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


def test_the_sidebar_stays_in_place_while_a_long_page_scrolls(
    signed_in: Page, agents_url: str, api: httpx.Client
) -> None:
    """The agent page is longer than a low window: the page scrolls, the navigation and the header do not."""
    agent = _agent(api)
    page = signed_in
    page.set_viewport_size({"width": 1270, "height": 420})
    page.goto(f"{agents_url}/agents/{agent['id']}")
    expect(page.locator("[data-agent-editor]")).to_be_visible()
    sidebar, header = page.locator(".sidebar"), page.locator(".app-header")
    expect(sidebar).to_be_visible()
    page.mouse.move(700, 300)
    page.mouse.wheel(0, 900)
    page.wait_for_function(  # the page really moved
        "() => window.scrollY > 0 || document.querySelector('.main').scrollTop > 0"
    )
    box, head = sidebar.bounding_box(), header.bounding_box()
    # Status & info starts level with the active area (no staircase under the tab bar)
    main_card = page.locator(".ag-card--panels").bounding_box()
    status = page.locator(".ag-status").bounding_box()
    assert main_card and status and abs(main_card["y"] - status["y"]) < 1
    assert box and head
    assert box["y"] == 0 and box["height"] == 420  # the navigation still fills the window
    assert head["y"] == 0  # and so does the header


# ── the editor's optional areas (ADR-045) ────────────────────────────


def _tabs(editor: Locator) -> list[str]:
    return [t for t in editor.locator("[data-ag-tabs] [role=tab]:visible").all_inner_texts()]


def test_a_new_agent_shows_only_the_prompts_and_the_options_switch_areas_on_and_off(
    signed_in: Page, agents_url: str, api: httpx.Client
) -> None:
    agent = api.post("/api/agents", json={"name": "Plain"}).json()
    page = signed_in
    page.goto(f"{agents_url}/agents/{agent['id']}")
    editor = page.locator("[data-agent-editor]")
    expect(editor.get_by_label("User prompt")).to_be_visible()
    assert _tabs(editor) == ["Prompts", "Versions & use"]
    expect(editor.locator("[data-system-field]")).to_be_hidden()
    panel = editor.locator("[data-options]")
    expect(panel).to_have_attribute("data-state", "closed")  # closed when the page opens
    _option(editor, "system_prompt")
    expect(
        editor.get_by_role("textbox", name="System prompt")
    ).to_be_visible()  # in Prompts, no tab of its own
    _option(editor, "inputs")
    _option(editor, "limits")
    _option(editor, "test")
    assert _tabs(editor) == ["Prompts", "Inputs", "Model & Limits", "Versions & use"]
    expect(editor.locator("[data-quick-test]")).to_be_visible()
    expect(editor.get_by_role("tab", name="Prompts")).to_have_attribute(
        "aria-selected", "true"
    )  # no jump
    # typing survives a tab change and switching an area off and on again
    _tab(editor, "Inputs")
    editor.locator("[data-add-input]").click()
    editor.locator(".ag-input").get_by_label("Name", exact=True).fill("ticket")
    _tab(editor, "Model & Limits")
    _add_setting(editor, "limits", "Retries")
    editor.get_by_label("Retries", exact=True).fill("1")
    _tab(editor, "Inputs")
    expect(editor.locator(".ag-input").get_by_label("Name", exact=True)).to_have_value("ticket")
    _option(editor, "inputs")  # the tab that is shown goes: back to Prompts
    expect(editor.get_by_role("tab", name="Prompts")).to_have_attribute("aria-selected", "true")
    assert "Inputs" not in _tabs(editor)
    _option(editor, "inputs")
    _tab(editor, "Inputs")
    expect(editor.locator(".ag-input").get_by_label("Name", exact=True)).to_have_value("ticket")
    panel.locator("[data-options-toggle]").click()  # closing the panel changes nothing
    expect(panel).to_have_attribute("data-state", "closed")
    assert len(_tabs(editor)) == 4


def test_the_switches_are_kept_with_the_draft_and_quick_test_and_the_panel_are_not(
    signed_in: Page, agents_url: str, api: httpx.Client
) -> None:
    agent = api.post("/api/agents", json={"name": "Kept"}).json()
    page = signed_in
    page.goto(f"{agents_url}/agents/{agent['id']}")
    editor = page.locator("[data-agent-editor]")
    editor.get_by_label("User prompt").fill("Hello")
    _option(editor, "limits")
    _option(editor, "test")
    editor.locator("[data-save]").click()
    expect(editor.locator("[data-draft-state]")).to_contain_text("The draft is saved")
    stored = api.get(f"/api/agents/{agent['id']}").json()["draft"]
    assert (stored["limits_enabled"], stored["inputs_enabled"]) == (True, False)
    assert "test" not in str(stored)  # Quick test is not part of the agent
    page.reload()
    editor = page.locator("[data-agent-editor]")
    expect(editor.get_by_label("User prompt")).to_have_value("Hello")
    expect(editor.locator("[data-options]")).to_have_attribute("data-state", "closed")
    assert _tabs(editor) == [
        "Prompts",
        "Model & Limits",
        "Versions & use",
    ]  # Quick test is off again
    # a switched-off area is kept, not deleted: Model & Limits off and on keeps its values
    _tab(editor, "Model & Limits")
    _add_setting(editor, "limits", "Retries")
    editor.get_by_label("Retries", exact=True).fill("1")
    _option(editor, "limits")
    _option(editor, "limits")
    _tab(editor, "Model & Limits")
    expect(editor.get_by_label("Retries", exact=True)).to_have_value("1")


# ── Model & Limits: optional settings (ADR-046) ──────────────────────


def test_model_and_limit_settings_are_added_removed_and_saved_as_not_set(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    _provider(api, llm)
    agent = api.post(
        "/api/agents", json={"name": "Settings", "draft": {"user_prompt": "Hi"}}
    ).json()
    page = signed_in
    page.goto(f"{agents_url}/agents/{agent['id']}")
    editor = page.locator("[data-agent-editor]")
    _option(editor, "limits")
    _tab(editor, "Model & Limits")
    model, limits = (
        editor.locator('[data-settings="model"]'),
        editor.locator('[data-settings="limits"]'),
    )
    expect(model.locator(".setting")).to_have_count(0)  # nothing set
    expect(limits.locator(".settings-card__lead")).to_contain_text(
        "Defaults apply: node time limit 600 s"
    )
    # the menu offers only what is not added yet
    model.locator("[data-settings-add]").click()
    expect(page.get_by_role("menuitem")).to_have_text(
        [
            "Provider · default the default provider",
            "Model · default the provider's default model",
            "Temperature · default the model's own",
            "Max tokens · default the model's own",
        ]
    )  # each with the default it overrides
    page.get_by_role("menuitem", name="Temperature").click()
    expect(model.get_by_label("Temperature", exact=True)).to_be_focused()
    model.locator("[data-settings-add]").click()
    expect(page.get_by_role("menuitem")).to_have_count(3)  # Temperature is added: not offered again
    page.keyboard.press("Escape")
    model.get_by_label("Temperature", exact=True).fill("0.4")
    _add_setting(editor, "model", "Model")
    expect(model.get_by_label("Model", exact=True)).to_contain_text("Default of the provider")
    model.get_by_label("Model", exact=True).select_option("small")
    _add_setting(editor, "limits", "Retries")
    expect(limits.get_by_label("Retries", exact=True)).to_have_attribute(
        "placeholder", "3"
    )  # the default, grey
    limits.get_by_label("Retries", exact=True).fill("1")
    for label in ("Request timeout", "Node time limit", "Max iterations"):
        _add_setting(editor, "limits", label)
    expect(limits.locator("[data-settings-add]")).to_be_disabled()  # all four are added
    limits.get_by_role("button", name="Remove Max iterations").click()
    expect(limits.locator("[data-settings-add]")).to_be_enabled()
    limits.get_by_role("button", name="Remove Request timeout").click()
    limits.get_by_role("button", name="Remove Node time limit").click()
    editor.locator("[data-save]").click()
    expect(editor.locator("[data-draft-state]")).to_contain_text("The draft is saved")
    draft = api.get(f"/api/agents/{agent['id']}").json()["draft"]
    assert (draft["temperature"], draft["model"], draft["retries"]) == (0.4, "small", 1)
    assert (draft["max_iterations"], draft["request_timeout_seconds"], draft["provider_id"]) == (
        None,
        None,
        None,
    )  # removed or never added: not set, not a default
    page.reload()
    editor = page.locator("[data-agent-editor]")
    _tab(editor, "Model & Limits")
    expect(editor.locator('[data-settings="model"] .setting')).to_have_count(2)
    expect(editor.locator('[data-settings="limits"] .setting')).to_have_count(1)
    # a removed setting can be added again, empty
    editor.locator('[data-settings="limits"]').get_by_role("button", name="Remove Retries").click()
    _add_setting(editor, "limits", "Retries")
    expect(editor.get_by_label("Retries", exact=True)).to_have_value("")
    # an agent without provider and model is published: the node decides
    editor.locator('[data-settings="model"]').get_by_role("button", name="Remove Model").click()
    editor.locator("[data-publish]").click()
    expect(editor.locator("[data-notice]")).to_contain_text("Published as version 1")


def test_the_quick_test_explains_itself_in_its_name(
    signed_in: Page, agents_url: str, api: httpx.Client
) -> None:
    agent = api.post("/api/agents", json={"name": "Hint", "draft": {"user_prompt": "Hi"}}).json()
    page = signed_in
    page.goto(f"{agents_url}/agents/{agent['id']}")
    editor = page.locator("[data-agent-editor]")
    _option(editor, "test")
    name = editor.locator("[data-quick-test] .ag-hint")
    expect(name).to_have_text("Quick test")
    expect(name).to_have_attribute("title", re.compile("not an artifact id"))


# ── the inputs table ─────────────────────────────────────────────────


def test_the_inputs_table_has_a_required_column_and_a_description_only_when_one_is_added(
    signed_in: Page, agents_url: str, api: httpx.Client
) -> None:
    agent = api.post(
        "/api/agents",
        json={
            "name": "Table",
            "draft": {
                "user_prompt": "${input.repo} ${input.branch}",
                "inputs": [
                    {"name": "repo", "required": True},
                    {"name": "branch", "default": "main"},
                ],
            },
        },
    ).json()
    page = signed_in
    page.goto(f"{agents_url}/agents/{agent['id']}")
    editor = page.locator("[data-agent-editor]")
    _tab(editor, "Inputs")
    table = editor.locator("[data-inputs-table]")
    rows = table.locator(".ag-input")
    expect(rows).to_have_count(2)
    expect(rows.nth(0).get_by_label("Required", exact=True)).to_have_value("required")
    expect(rows.nth(0).get_by_label("Default", exact=True)).to_be_disabled()
    expect(rows.nth(1).get_by_label("Required", exact=True)).to_have_value("optional")
    expect(table.locator(".ag-inputs-head__description")).to_be_hidden()  # nobody has a description
    # the menu offers exactly the fitting action
    rows.nth(0).get_by_role("button", name="Input actions").click()
    expect(page.get_by_role("menuitem")).to_have_text(["Add description", "Remove input"])
    page.get_by_role("menuitem", name="Add description").click()
    expect(table.locator(".ag-inputs-head__description")).to_be_visible()
    rows.nth(0).get_by_label("Description", exact=True).fill("Repository name")
    rows.nth(1).get_by_role("button", name="Input actions").click()
    page.get_by_role("menuitem", name="Add description").click()
    rows.nth(1).get_by_label("Description", exact=True).fill("Branch name")
    rows.nth(0).get_by_role("button", name="Input actions").click()
    expect(page.get_by_role("menuitem")).to_have_text(["Remove description", "Remove input"])
    page.get_by_role("menuitem", name="Remove description").click()
    expect(
        table.locator(".ag-inputs-head__description")
    ).to_be_visible()  # the other one still has one
    expect(rows.nth(1).get_by_label("Description", exact=True)).to_have_value("Branch name")
    rows.nth(1).get_by_label("Required", exact=True).select_option("required")
    editor.locator("[data-save]").click()
    expect(editor.locator("[data-draft-state]")).to_contain_text("The draft is saved")
    inputs = api.get(f"/api/agents/{agent['id']}").json()["draft"]["inputs"]
    assert [(i["name"], i["required"], i["description"]) for i in inputs] == [
        ("repo", True, ""),
        ("branch", True, "Branch name"),
    ]
    page.reload()
    editor = page.locator("[data-agent-editor]")
    _tab(editor, "Inputs")
    table = editor.locator("[data-inputs-table]")
    rows = table.locator(".ag-input")
    expect(rows.nth(1).get_by_label("Description", exact=True)).to_have_value("Branch name")
    rows.nth(1).get_by_role("button", name="Input actions").click()
    page.get_by_role("menuitem", name="Remove description").click()
    expect(table.locator(".ag-inputs-head__description")).to_be_hidden()  # the last one went
    rows.nth(0).get_by_role("button", name="Input actions").click()
    page.get_by_role("menuitem", name="Remove input").click()
    expect(rows).to_have_count(1)


# ── Versions & use (ADR-047) ─────────────────────────────────────────


def test_versions_and_use_show_where_the_agent_runs_and_a_reference_is_removed_after_asking(
    signed_in: Page, agents_url: str, api: httpx.Client
) -> None:
    agent = _agent(api)
    actions = []
    for name in ("Triage action", "Release action"):
        action = api.post("/api/actions", json={"name": name}).json()
        node(api, action, "agent", name=f"Ask {name.split()[0]}", config={"agent_id": agent["id"]})
        actions.append(action)
    page = signed_in
    page.goto(f"{agents_url}/agents/{agent['id']}")
    editor = page.locator("[data-agent-editor]")
    _tab(editor, "Versions & use")
    uses = editor.locator("[data-uses] .ag-use")
    expect(uses).to_have_count(2)
    expect(uses.nth(0)).to_contain_text("Agent node · Action:")
    # the two columns: Used by on the left, Versions on the right
    left = editor.locator(".ag-uses-card").bounding_box()
    right = editor.locator(".ag-versions-card").bounding_box()
    assert left and right and left["x"] < right["x"] and abs(left["y"] - right["y"]) < 1
    versions = editor.locator("[data-versions] .ag-version")
    expect(versions).to_have_count(1)
    expect(versions.first).to_contain_text("In use")
    # Cancel changes nothing
    triage = uses.filter(has_text="Triage action")
    triage.get_by_role("button", name=re.compile("Remove the reference")).click()
    dialog = page.locator("#reference-modal")
    expect(dialog.locator(".modal__title")).to_have_text("Remove agent reference?")
    expect(dialog).to_contain_text("This will remove the connection to this agent from the action:")
    expect(dialog.locator(".confirm-text__subject")).to_have_text("Triage action")
    expect(dialog).to_contain_text("future executions may fail until the node is reconfigured")
    dialog.get_by_role("button", name="Cancel").click()
    assert len(api.get(f"/api/agents/{agent['id']}/uses").json()) == 2
    # confirmed: only that reference goes
    triage.get_by_role("button", name=re.compile("Remove the reference")).click()
    dialog.locator("[data-confirm]").click()
    expect(uses).to_have_count(1)
    expect(uses.first).to_contain_text("Release action")
    assert [u["graph_name"] for u in api.get(f"/api/agents/{agent['id']}/uses").json()] == [
        "Release action"
    ]
    assert api.get(f"/api/agents/{agent['id']}").status_code == 200
    # Open goes to the action, selects the node and offers the way back
    uses.first.get_by_role("link", name=re.compile("^Open")).click()
    expect(page).to_have_url(re.compile(r"/actions/release-action"))
    expect(page.locator(".ge-node--agent.is-selected")).to_have_count(1)
    back = page.locator("[data-back]")
    expect(back).to_have_text("Back to Triage")
    back.click()
    expect(page).to_have_url(re.compile(rf"/agents/{agent['id']}$"))


def test_publish_again_makes_a_new_version_in_use_and_the_empty_states_say_so(
    signed_in: Page, agents_url: str, api: httpx.Client
) -> None:
    fresh = api.post("/api/agents", json={"name": "Fresh", "draft": {"user_prompt": "Hi"}}).json()
    page = signed_in
    page.goto(f"{agents_url}/agents/{fresh['id']}")
    editor = page.locator("[data-agent-editor]")
    _tab(editor, "Versions & use")
    expect(editor.locator("[data-uses-empty]")).to_have_text(
        "This agent is not used by any actions yet."
    )
    expect(editor.locator("[data-versions-empty]")).to_have_text("No published versions yet.")
    api.post(f"/api/agents/{fresh['id']}/publish").raise_for_status()
    api.put(f"/api/agents/{fresh['id']}/draft", json={"user_prompt": "Hello"}).raise_for_status()
    api.post(f"/api/agents/{fresh['id']}/publish").raise_for_status()
    page.reload()
    editor = page.locator("[data-agent-editor]")
    _tab(editor, "Versions & use")
    versions = editor.locator("[data-versions] .ag-version")
    expect(versions).to_have_count(2)
    expect(versions.nth(0)).to_contain_text("In use")
    expect(versions.nth(1)).not_to_contain_text("In use")
    versions.nth(1).get_by_role("button", name="Publish version 1 again").click()
    page.locator("#confirm-modal [data-confirm]").click()
    expect(versions).to_have_count(3)
    expect(versions.nth(0)).to_contain_text("Version 3")
    expect(versions.nth(0)).to_contain_text("In use")
    expect(versions.nth(0)).to_contain_text("rollback to version 1")
    published = api.get(f"/api/agents/{fresh['id']}").json()
    assert published["published"]["user_prompt"] == "Hi" and published["published_number"] == 3
