"""The optional areas of an agent (ADR-045): Inputs and Model & Limits are switched on or off; switched off they
are kept but not in effect, as the system prompt already was. Agents from before get the switches from their data."""

from __future__ import annotations

from collections.abc import Generator, Iterator

import pytest
from fastapi.testclient import TestClient

from openartifact.agents.schemas import AgentConfig
from openartifact.app import _create_app
from openartifact.config import Settings
from tests.agent_support import HEADERS, SECURE, FakeLlm, fake_llm, make_agent, make_provider
from tests.test_agent_node import _flow, _run


def test_an_agent_from_before_the_switches_has_them_from_its_data() -> None:
    plain = AgentConfig.loads('{"user_prompt": "Hi"}')
    assert (plain.inputs_enabled, plain.limits_enabled) == (None, None)  # nothing stored
    assert (plain.inputs_on, plain.limits_on) == (False, False)
    rich = AgentConfig.loads(
        '{"user_prompt": "Hi ${input.a}", "inputs": [{"name": "a"}], "temperature": 0.2}'
    )
    assert (rich.inputs_on, rich.limits_on) == (True, True)
    assert AgentConfig.loads('{"retries": 1}').limits_on is True  # a limit that differs counts too
    assert AgentConfig.loads('{"retries": 3}').limits_on is False  # the default does not


def test_switched_off_areas_are_kept_but_not_in_effect() -> None:
    config = AgentConfig(
        user_prompt="Hi",
        inputs=[{"name": "a"}],  # type: ignore[list-item]
        temperature=0.2,
        retries=1,
        model="big",
        inputs_enabled=False,
        limits_enabled=False,
    )
    effective = config.effective()
    assert effective.inputs == [] and effective.temperature is None and effective.model is None
    assert effective.retries == AgentConfig().retries  # the defaults of the backend
    assert config.inputs[0].name == "a" and config.temperature == 0.2  # the draft keeps them
    on = config.model_copy(update={"inputs_enabled": True, "limits_enabled": True}).effective()
    assert [i.name for i in on.inputs] == ["a"] and on.temperature == 0.2


def test_the_switches_are_saved_with_the_draft(api: TestClient) -> None:
    agent = make_agent(api, publish=False)
    draft = {**agent["draft"], "inputs_enabled": True, "limits_enabled": False}
    saved = api.put(f"/api/agents/{agent['id']}/draft", json=draft).json()
    assert (saved["draft"]["inputs_enabled"], saved["draft"]["limits_enabled"]) == (True, False)
    assert api.get(f"/api/agents/{agent['id']}").json()["draft"]["limits_enabled"] is False


def test_publishing_with_inputs_switched_off_refuses_a_prompt_that_reads_an_input(
    api: TestClient,
) -> None:
    agent = make_agent(api, publish=False, inputs_enabled=False)
    refused = api.post(f"/api/agents/{agent['id']}/publish")
    assert (
        refused.status_code == 422 and "ticket" in refused.text
    )  # ${input.ticket} has no input now


def test_a_run_with_model_and_limits_switched_off_uses_the_defaults(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    agent = make_agent(api, temperature=0.3, max_tokens=200, limits_enabled=False)
    llm.hits.clear()
    _run(api, _flow(api, agent))
    (request,) = llm.completions()
    assert "temperature" not in request["json"] and "max_tokens" not in request["json"]
    on = make_agent(api, name="On", temperature=0.3, max_tokens=200, limits_enabled=True)
    llm.hits.clear()
    _run(api, _flow(api, on))
    (request,) = llm.completions()
    assert (request["json"]["temperature"], request["json"]["max_tokens"]) == (0.3, 200)


def test_the_preview_follows_the_switches(api: TestClient, llm: FakeLlm) -> None:
    make_provider(api, llm)
    agent = make_agent(api, publish=False, user_prompt="Plain", inputs_enabled=False)
    preview = api.post(f"/api/agents/{agent['id']}/preview", json={"values": {}}).json()
    assert preview["inputs"] == [] and preview["user_prompt"] == "Plain"


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    with TestClient(_create_app(migrated_settings.model_copy(update=SECURE))) as client:
        client.headers.update(HEADERS)
        yield client


@pytest.fixture
def llm() -> Iterator[FakeLlm]:
    with fake_llm() as server:
        yield server
