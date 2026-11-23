"""Agents through the API: drafts, publishing, versions, rollback, references, preview, the three ways in."""

from __future__ import annotations

from collections.abc import Generator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from tests.agent_support import HEADERS, SECURE, FakeLlm, fake_llm, make_agent, make_provider
from tests.helpers import graph_url as _url
from tests.helpers import node as _node
from tests.helpers import post as _post


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    """A client with a token and a secret key (secrets can be stored) that may reach a local provider."""
    with TestClient(_create_app(migrated_settings.model_copy(update=SECURE))) as client:
        client.headers.update(HEADERS)
        yield client


@pytest.fixture
def published(api: TestClient) -> list[tuple[str, dict[str, Any]]]:
    """Everything the application publishes on its event bus."""
    events: list[tuple[str, dict[str, Any]]] = []
    bus = api.app.state.event_bus  # type: ignore[attr-defined]
    original = bus.publish

    def spy(event_type: str, data: dict[str, Any]) -> Any:
        events.append((event_type, data))
        return original(event_type, data)

    bus.publish = spy
    return events


@pytest.fixture
def llm() -> Iterator[FakeLlm]:
    with fake_llm() as server:
        yield server


def _agent_node(
    client: TestClient, agent: dict[str, Any], name: str = "Ask", **config: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    action = _post(client, "/api/actions", name=f"Action of {name}")
    node = _node(client, action, "agent", name=name, config={"agent_id": agent["id"], **config})
    return action, node


# ── create, read, rename ─────────────────────────────────────────────


def test_a_new_agent_has_a_draft_and_nothing_published(api: TestClient) -> None:
    response = api.post("/api/agents", json={"name": " Triage ", "description": "Sorts tickets"})
    assert response.status_code == 201, response.text
    agent = response.json()
    assert (agent["name"], agent["description"], agent["active"]) == (
        "Triage",
        "Sorts tickets",
        True,
    )
    assert agent["published_number"] is None and agent["published"] is None
    assert agent["draft_changed"] is True and agent["versions"] == [] and agent["node_count"] == 0
    assert (
        agent["draft"]["retries"] is None and agent["draft"]["request_timeout_seconds"] is None
    )  # not set (ADR-046)
    assert agent["problems"] == ["The user prompt is empty"]
    assert api.get(f"/api/agents/{agent['id']}").json() == agent
    assert api.get("/api/agents/triage").json()["id"] == agent["id"]  # by name, ignoring case
    listed = api.get("/api/agents").json()
    assert [a["name"] for a in listed] == ["Triage"]
    assert "draft" not in listed[0]


def test_names_are_unique_ignoring_case_and_unknown_agents_are_404(api: TestClient) -> None:
    first = make_agent(api, "Triage", publish=False)
    assert api.post("/api/agents", json={"name": "TRIAGE"}).status_code == 409
    other = make_agent(api, "Other", publish=False)
    clash = api.patch(f"/api/agents/{other['id']}", json={"name": "triage"})
    assert clash.status_code == 409 and 'named "Triage"' in clash.json()["detail"]
    assert (
        api.patch(f"/api/agents/{first['id']}", json={"name": "TRIAGE"}).json()["name"] == "TRIAGE"
    )
    assert api.post("/api/agents", json={"name": "   "}).status_code == 422
    assert api.post("/api/agents", json={"name": "x", "extra": 1}).status_code == 422
    for call in (
        api.get("/api/agents/nope"),
        api.patch("/api/agents/nope", json={"active": False}),
        api.put("/api/agents/nope/draft", json={}),
        api.post("/api/agents/nope/publish"),
        api.post("/api/agents/nope/draft/discard"),
        api.get("/api/agents/nope/versions"),
        api.get("/api/agents/nope/uses"),
        api.post("/api/agents/nope/preview", json={}),
        api.delete("/api/agents/nope"),
    ):
        assert call.status_code == 404, call.request.url
        assert call.json() == {"detail": "Agent not found"}


def test_description_and_the_active_switch_can_be_changed(api: TestClient) -> None:
    agent = make_agent(api, publish=False)
    changed = api.patch(
        f"/api/agents/{agent['id']}", json={"description": "New", "active": False}
    ).json()
    assert (changed["description"], changed["active"], changed["name"]) == ("New", False, "Triage")


# ── drafts and publishing ────────────────────────────────────────────


def test_a_draft_changes_nothing_until_it_is_published(api: TestClient) -> None:
    agent = make_agent(api)
    assert agent["published_number"] == 1 and agent["draft_changed"] is False
    draft = {**agent["draft"], "user_prompt": "New: ${input.ticket}", "temperature": 0.7}
    saved = api.put(f"/api/agents/{agent['id']}/draft", json=draft).json()
    assert saved["draft"]["user_prompt"] == "New: ${input.ticket}"
    assert saved["draft_changed"] is True and saved["published_number"] == 1
    assert saved["published"]["user_prompt"].startswith("Analyse:")  # what executions use
    assert saved["published"]["temperature"] is None
    assert [v["number"] for v in saved["versions"]] == [1]


def test_a_wrong_draft_is_refused_with_one_line_per_problem(api: TestClient) -> None:
    agent = make_agent(api, publish=False)
    response = api.put(
        f"/api/agents/{agent['id']}/draft",
        json={"max_tokens": 9000, "inputs": [{"name": "Bad Name"}], "retries": 7},
    )
    assert response.status_code == 422
    assert api.get(f"/api/agents/{agent['id']}").json()["draft"] == agent["draft"]


def test_an_incomplete_draft_can_be_saved_but_not_published(api: TestClient) -> None:
    agent = make_agent(api, publish=False)
    draft = {"user_prompt": "Use ${input.missing} and ${var.x}", "provider_id": "gone"}
    saved = api.put(f"/api/agents/{agent['id']}/draft", json=draft)
    assert saved.status_code == 200
    problems = saved.json()["problems"]
    assert "User prompt: ${input.missing} is not a declared input" in problems
    assert any("${var.x} is not allowed" in p for p in problems)
    assert "The chosen provider does not exist" in problems
    refused = api.post(f"/api/agents/{agent['id']}/publish")
    assert refused.status_code == 422
    assert refused.json()["detail"].splitlines() == problems
    assert api.get(f"/api/agents/{agent['id']}").json()["versions"] == []


def test_publishing_makes_a_new_unchangeable_version_each_time(
    api: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    agent = make_agent(api)
    first = api.get(f"/api/agents/{agent['id']}/versions/1").json()
    assert first["config"]["user_prompt"].startswith("Analyse:") and first["current"] is True
    assert (first["published_via"], first["source_number"]) == ("user", None)
    published.clear()
    api.put(
        f"/api/agents/{agent['id']}/draft",
        json={**agent["draft"], "user_prompt": "Second ${input.ticket}", "max_tokens": 100},
    )
    result = api.post(f"/api/agents/{agent['id']}/publish").json()
    assert result["version"]["number"] == 2 and result["version"]["current"] is True
    assert result["changed"] == ["user_prompt", "max_tokens"]
    assert result["agent"]["published_number"] == 2 and result["agent"]["draft_changed"] is False
    assert [e[0] for e in published] == ["agents.changed", "agents.changed"]
    versions = api.get(f"/api/agents/{agent['id']}/versions").json()
    assert [(v["number"], v["current"]) for v in versions] == [(2, True), (1, False)]
    assert versions[1]["config"] == first["config"]  # version 1 is as it was
    assert api.get(f"/api/agents/{agent['id']}/versions/9").status_code == 404
    assert api.get(f"/api/agents/{agent['id']}/versions/x").status_code == 422


def test_discarding_the_draft_goes_back_to_the_published_version(api: TestClient) -> None:
    unpublished = make_agent(api, "Fresh", publish=False)
    assert api.post(f"/api/agents/{unpublished['id']}/draft/discard").status_code == 409
    agent = make_agent(api)
    api.put(f"/api/agents/{agent['id']}/draft", json={**agent["draft"], "user_prompt": "Scrap"})
    back = api.post(f"/api/agents/{agent['id']}/draft/discard").json()
    assert back["draft"] == agent["published"] and back["draft_changed"] is False


# ── rollback ─────────────────────────────────────────────────────────


def test_a_rollback_is_a_new_version_with_the_old_content(api: TestClient) -> None:
    agent = make_agent(api, user_prompt="One ${input.ticket}")
    for text in ("Two ${input.ticket}", "Three ${input.ticket}"):
        api.put(f"/api/agents/{agent['id']}/draft", json={**agent["draft"], "user_prompt": text})
        assert api.post(f"/api/agents/{agent['id']}/publish").status_code == 200
    result = api.post(f"/api/agents/{agent['id']}/versions/1/republish")
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["version"]["number"] == 4 and body["version"]["source_number"] == 1
    assert body["version"]["config"]["user_prompt"] == "One ${input.ticket}"
    assert body["changed"] == ["user_prompt"]
    assert body["agent"]["published_number"] == 4
    # a draft that had no changes of its own follows the rollback
    assert (
        body["agent"]["draft"]["user_prompt"] == "One ${input.ticket}"
        and body["agent"]["draft_changed"] is False
    )
    versions = api.get(f"/api/agents/{agent['id']}/versions").json()
    assert [
        (v["number"], v["source_number"], v["config"]["user_prompt"][:5]) for v in versions
    ] == [
        (4, 1, "One $"),
        (3, None, "Three"),
        (2, None, "Two $"),
        (1, None, "One $"),
    ]


def test_a_rollback_keeps_a_draft_that_is_being_edited_and_numbers_are_never_reused(
    api: TestClient,
) -> None:
    agent = make_agent(api, user_prompt="One ${input.ticket}")
    api.put(
        f"/api/agents/{agent['id']}/draft",
        json={**agent["draft"], "user_prompt": "Two ${input.ticket}"},
    )
    api.post(f"/api/agents/{agent['id']}/publish")
    api.put(
        f"/api/agents/{agent['id']}/draft",
        json={**agent["draft"], "user_prompt": "Work in progress"},
    )
    body = api.post(f"/api/agents/{agent['id']}/versions/1/republish").json()
    assert (
        body["agent"]["draft"]["user_prompt"] == "Work in progress"
        and body["agent"]["draft_changed"] is True
    )
    assert (
        api.post(f"/api/agents/{agent['id']}/versions/3/republish").status_code == 409
    )  # it is the published one
    assert api.post(f"/api/agents/{agent['id']}/versions/8/republish").status_code == 404
    assert api.post(f"/api/agents/{agent['id']}/publish").json()["version"]["number"] == 4


def test_a_version_that_cannot_be_used_any_more_is_not_republished(
    api: TestClient, llm: FakeLlm
) -> None:
    provider = make_provider(api, llm)
    agent = make_agent(api, provider_id=provider["id"], model="small")
    api.put(f"/api/agents/{agent['id']}/draft", json={**agent["draft"], "model": None})
    api.post(f"/api/agents/{agent['id']}/publish")
    small = next(m for m in provider["models"] if m["model_id"] == "small")
    api.patch(f"/api/providers/{provider['id']}", json={"default_model": None})
    assert (
        api.patch(
            f"/api/providers/{provider['id']}/models/{small['id']}", json={"enabled": False}
        ).status_code
        == 200
    )
    refused = api.post(f"/api/agents/{agent['id']}/versions/1/republish")
    assert refused.status_code == 422
    assert (
        refused.json()["detail"]
        == 'Version 1 cannot be published now:\nModel "small" is not enabled for provider "Local"'
    )


# ── references and deleting ──────────────────────────────────────────


def test_an_agent_that_nodes_refer_to_cannot_be_deleted(api: TestClient) -> None:
    agent = make_agent(api)
    action, node = _agent_node(api, agent, "Ask", retries=0, max_tokens=20)
    other, _ = _agent_node(api, agent, "Second")
    uses = api.get(f"/api/agents/{agent['id']}/uses").json()
    assert [(u["node_name"], u["graph_name"], u["overrides"]) for u in uses] == [
        ("Ask", "Action of Ask", ["max_tokens", "retries"]),
        ("Second", "Action of Second", []),
    ]
    assert uses[0]["graph_id"] == action["id"] and uses[0]["graph_slug"] == action["slug"]
    assert api.get("/api/agents").json()[0]["node_count"] == 2
    refused = api.delete(f"/api/agents/{agent['id']}")
    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        '2 agent nodes refer to this agent: "Ask" in action "Action of Ask", "Second" in action "Action of Second"'
    )
    api.delete(f"{_url(action)}/nodes/{node['id']}")
    assert "1 agent node refers" in api.delete(f"/api/agents/{agent['id']}").json()["detail"]
    api.delete(_url(other))  # deleting the action removes its nodes
    assert api.delete(f"/api/agents/{agent['id']}").status_code == 204
    assert api.get(f"/api/agents/{agent['id']}").status_code == 404
    assert api.get("/api/agents").json() == []


def test_publishing_tells_which_nodes_override_a_changed_field(api: TestClient) -> None:
    agent = make_agent(api)
    _agent_node(api, agent, "Keeps its own", max_tokens=50, retries=1)
    _agent_node(api, agent, "Follows")
    _agent_node(api, agent, "Other field", temperature=1)
    api.put(f"/api/agents/{agent['id']}/draft", json={**agent["draft"], "max_tokens": 900})
    result = api.post(f"/api/agents/{agent['id']}/publish").json()
    assert result["changed"] == ["max_tokens"]
    assert [(u["node_name"], u["overrides"]) for u in result["overriding"]] == [
        ("Keeps its own", ["max_tokens", "retries"])
    ]


def test_saving_an_agent_node_warns_about_what_will_fail(api: TestClient, llm: FakeLlm) -> None:
    make_provider(api, llm)
    agent = make_agent(api)
    action = _post(api, "/api/actions", name="Act")
    node = _node(api, action, "agent")
    assert node["warnings"] == ["No agent is chosen"]
    url = f"{_url(action)}/nodes/{node['id']}"

    def warnings(**config: Any) -> list[str]:
        response = api.patch(url, json={"config": config})
        assert response.status_code == 200, response.text
        return response.json()["warnings"]  # type: ignore[no-any-return]

    assert warnings(agent_id="nope") == ["The chosen agent does not exist"]
    assert warnings(agent_id=agent["id"]) == ["required input 'ticket' is not mapped"]
    assert warnings(inputs="ticket = ${node.Missing.output}") == [
        '${node.Missing.output}: no node is named "Missing"'
    ]
    assert warnings(inputs="ticket = text\nextra = 1") == [
        "input 'extra' is not declared by the agent"
    ]
    assert warnings(inputs="ticket = ${var.ticket}") == []
    assert warnings(user_prompt="Only ${input.nope}") == [
        "User prompt: ${input.nope} is not a declared input"
    ]
    assert warnings(user_prompt=None, model="unknown") == [
        'Model "unknown" is not enabled for provider "Local"'
    ]
    assert warnings(model=None) == []
    api.patch(f"/api/agents/{agent['id']}", json={"active": False})
    assert warnings(retries=1) == ['Agent "Triage" is inactive: the node will fail']
    fresh = make_agent(api, "Fresh", publish=False)
    assert warnings(agent_id=fresh["id"]) == [
        'Agent "Fresh" has no published version: the node will fail'
    ]
    refused = api.patch(url, json={"config": {"inputs": "ticket = ${secret:KEY}"}})
    assert (
        refused.status_code == 422 and "cannot be an input of an agent" in refused.json()["detail"]
    )


def test_an_agent_node_resets_an_override_with_null(api: TestClient) -> None:
    agent = make_agent(api)
    action, node = _agent_node(api, agent, inputs="ticket = x", temperature=0.9, retries=0)
    assert (
        node["config"]["temperature"],
        node["config"]["retries"],
        node["config"]["max_tokens"],
    ) == (0.9, 0, None)
    url = f"{_url(action)}/nodes/{node['id']}"
    reset = api.patch(url, json={"config": {"temperature": None}}).json()
    assert reset["config"]["temperature"] is None and reset["config"]["retries"] == 0
    assert api.get(f"/api/agents/{agent['id']}/uses").json()[0]["overrides"] == ["retries"]
    assert api.patch(url, json={"config": {"max_tokens": 9000}}).status_code == 422


# ── preview ──────────────────────────────────────────────────────────


def test_the_preview_shows_only_active_prompts_and_sends_nothing(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    llm.hits.clear()
    agent = make_agent(api, system_prompt="Be brief about ${input.ticket}.")
    preview = api.post(
        f"/api/agents/{agent['id']}/preview", json={"values": {"ticket": "T-1"}}
    ).json()
    assert preview["system_prompt"] is None  # switched off: not shown
    assert preview["user_prompt"] == "Analyse: T-1\nContext: none"
    assert [(i["name"], i["state"], i["value"]) for i in preview["inputs"]] == [
        ("ticket", "sample", "T-1"),
        ("context", "default", "none"),
    ]
    assert preview["problems"] == [] and preview["version"] is None
    assert (preview["provider"], preview["model"]) == ("Local", "small")
    api.put(
        f"/api/agents/{agent['id']}/draft", json={**agent["draft"], "system_prompt_enabled": True}
    )
    preview = api.post(
        f"/api/agents/{agent['id']}/preview", json={"values": {"ticket": "T-1"}}
    ).json()
    assert preview["system_prompt"] == "Be brief about T-1."
    assert llm.hits == []  # no request left the application


def test_the_preview_reports_missing_values_and_keeps_their_placeholders(api: TestClient) -> None:
    agent = make_agent(
        api,
        inputs=[
            {"name": "ticket", "required": True},
            {"name": "context"},
            {"name": "n", "type": "number"},
        ],
        user_prompt="A ${input.ticket} B ${input.context} C ${input.n}",
    )
    preview = api.post(f"/api/agents/{agent['id']}/preview", json={"values": {"n": "many"}}).json()
    assert preview["user_prompt"] == "A ${input.ticket} B  C ${input.n}"
    states = {i["name"]: i for i in preview["inputs"]}
    assert states["ticket"]["state"] == "error" and states["context"]["state"] == "unset"
    assert preview["problems"] == [
        "required input 'ticket' is not mapped",
        "input 'n' is not a number",
        "No provider is set and there is no default provider",
    ]


def test_the_preview_can_show_the_published_or_a_numbered_version(api: TestClient) -> None:
    agent = make_agent(api, user_prompt="One ${input.ticket}")
    api.put(
        f"/api/agents/{agent['id']}/draft",
        json={**agent["draft"], "user_prompt": "Draft ${input.ticket}"},
    )
    values = {"values": {"ticket": "x"}}
    assert (
        api.post(f"/api/agents/{agent['id']}/preview", json=values).json()["user_prompt"]
        == "Draft x"
    )
    published = api.post(
        f"/api/agents/{agent['id']}/preview", json={**values, "source": "published"}
    ).json()
    assert (published["user_prompt"], published["version"]) == ("One x", 1)
    numbered = api.post(f"/api/agents/{agent['id']}/preview", json={**values, "version": 1}).json()
    assert numbered["user_prompt"] == "One x"
    assert api.post(f"/api/agents/{agent['id']}/preview", json={"version": 5}).status_code == 404
    fresh = make_agent(api, "Fresh", publish=False)
    assert (
        api.post(f"/api/agents/{fresh['id']}/preview", json={"source": "published"}).status_code
        == 409
    )


def test_the_preview_of_a_node_applies_its_overrides_and_mapping(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    agent = make_agent(api, temperature=0.2)
    _, node = _agent_node(
        api,
        agent,
        inputs="ticket = ${node.Fetch.output}\ncontext = fixed",
        user_prompt="Short ${input.ticket}/${input.context}",
        temperature=1.5,
        model="large",
    )
    body = {"source": "published", "node_id": node["id"]}
    preview = api.post(f"/api/agents/{agent['id']}/preview", json=body).json()
    assert preview["user_prompt"] == "Short ${input.ticket}/fixed"  # the run is not known here
    states = {i["name"]: i for i in preview["inputs"]}
    assert (states["ticket"]["state"], states["ticket"]["source"]) == (
        "pending",
        "${node.Fetch.output}",
    )
    assert (states["context"]["state"], states["context"]["value"]) == ("mapped", "fixed")
    settings = {s["key"]: s for s in preview["settings"]}
    assert settings["temperature"] == {
        "key": "temperature",
        "value": 1.5,
        "inherited": 0.2,
        "overridden": True,
    }
    assert (
        settings["retries"]["overridden"] is False and settings["retries"]["value"] is None
    )  # not set: the runtime default
    assert preview["model"] == "large" and preview["problems"] == [
        'Model "large" is not enabled for provider "Local"'
    ]
    sampled = api.post(
        f"/api/agents/{agent['id']}/preview", json={**body, "values": {"ticket": "T-9"}}
    ).json()
    assert sampled["user_prompt"] == "Short T-9/fixed"
    other = make_agent(api, "Other")
    assert api.post(f"/api/agents/{other['id']}/preview", json=body).status_code == 422
    assert (
        api.post(f"/api/agents/{agent['id']}/preview", json={"node_id": "nope"}).status_code == 404
    )


def test_a_broken_mapping_is_a_problem_of_the_preview(api: TestClient) -> None:
    agent = make_agent(api)
    action, node = _agent_node(api, agent)
    import sqlite3

    settings = api.app.state.settings  # type: ignore[attr-defined]
    with sqlite3.connect(settings.data_dir / settings.database_filename) as db:
        db.execute(
            "UPDATE graph_nodes SET config = json_set(config, '$.inputs', 'broken') WHERE id = ?",
            (node["id"],),
        )
    preview = api.post(f"/api/agents/{agent['id']}/preview", json={"node_id": node["id"]}).json()
    assert preview["problems"][0] == "Input mapping: Line 1 is not 'name = value'"
    assert api.patch(f"{_url(action)}/nodes/{node['id']}", json={"name": "Renamed"}).json()[
        "warnings"
    ] == ["Input mapping: Line 1 is not 'name = value'"]


# ── /api/v1 and MCP ──────────────────────────────────────────────────


def test_the_integration_api_has_the_same_operations_and_records_its_origin(
    api: TestClient,
) -> None:
    created = api.post("/api/v1/agents", json={"name": "Scripted", "draft": {"user_prompt": "Hi"}})
    assert created.status_code == 201
    agent = created.json()
    assert (
        api.put(f"/api/v1/agents/{agent['id']}/draft", json={"user_prompt": "Hello"}).status_code
        == 200
    )
    result = api.post("/api/v1/agents/Scripted/publish").json()
    assert result["version"]["published_via"] == "api"
    api.put(f"/api/v1/agents/{agent['id']}/draft", json={"user_prompt": "Again"})
    api.post(f"/api/v1/agents/{agent['id']}/publish")
    rollback = api.post(f"/api/v1/agents/{agent['id']}/versions/1/republish").json()
    assert (rollback["version"]["number"], rollback["version"]["published_via"]) == (3, "api")
    assert [v["number"] for v in api.get(f"/api/v1/agents/{agent['id']}/versions").json()] == [
        3,
        2,
        1,
    ]
    assert (
        api.get(f"/api/v1/agents/{agent['id']}/versions/2").json()["config"]["user_prompt"]
        == "Again"
    )
    assert api.get("/api/v1/agents").json()[0]["name"] == "Scripted"
    assert api.get(f"/api/v1/agents/{agent['id']}").json()["published_number"] == 3
    assert api.get(f"/api/v1/agents/{agent['id']}/uses").json() == []
    assert (
        api.post(f"/api/v1/agents/{agent['id']}/preview", json={}).json()["user_prompt"] == "Hello"
    )
    assert api.post(f"/api/v1/agents/{agent['id']}/draft/discard").status_code == 200
    assert (
        api.patch(f"/api/v1/agents/{agent['id']}", json={"active": False}).json()["active"] is False
    )
    assert api.delete(f"/api/v1/agents/{agent['id']}").status_code == 204


def test_the_integration_api_needs_the_token(api: TestClient) -> None:
    for path in ("/api/v1/agents", "/api/v1/providers", "/api/agents", "/api/providers"):
        assert api.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_at_most_500_agents(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("openartifact.agents.service.MAX_AGENTS", 1)
    make_agent(api, "One", publish=False)
    refused = api.post("/api/agents", json={"name": "Two"})
    assert refused.status_code == 409 and refused.json()["detail"] == "At most 1 agents"
