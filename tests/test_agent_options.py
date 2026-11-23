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


# ── Model & Limits: every setting optional, unset is not the default (ADR-046) ──


def test_every_model_and_limit_setting_may_be_unset() -> None:
    config = AgentConfig(user_prompt="Hi")
    assert (config.request_timeout_seconds, config.total_timeout_seconds) == (None, None)
    assert (config.retries, config.max_iterations, config.provider_id, config.model) == (
        None,
        None,
        None,
        None,
    )
    assert config.limits_on is False  # nothing set: nothing to switch on
    assert (
        AgentConfig(retries=3).limits_on is True
    )  # an explicit value counts, even the default one


def test_a_stored_agent_from_before_reads_its_old_default_limits_as_unset() -> None:
    """Older drafts stored the four limits always; the runtime default and the old stored default are the same
    value, so treating them as unset changes no run and keeps the editor free of settings nobody chose."""
    old = AgentConfig.loads(
        '{"user_prompt": "Hi", "request_timeout_seconds": 60, "total_timeout_seconds": 600, '
        '"retries": 3, "max_iterations": 10}'
    )
    assert (old.request_timeout_seconds, old.retries, old.limits_on) == (None, None, False)
    chosen = AgentConfig.loads('{"user_prompt": "Hi", "retries": 1, "total_timeout_seconds": 600}')
    assert (chosen.retries, chosen.total_timeout_seconds) == (1, None)
    new = AgentConfig.loads('{"user_prompt": "Hi", "retries": 3, "limits_enabled": true}')
    assert new.retries == 3  # with the switch stored, a value is what the user set


def test_the_limits_out_of_range_are_still_refused() -> None:
    for field, value in (("retries", 5), ("request_timeout_seconds", 0), ("max_iterations", 51)):
        with pytest.raises(ValueError, match=field):
            AgentConfig(**{field: value})


def test_an_agent_without_provider_model_and_limits_is_published_and_a_run_uses_the_defaults(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)  # the default provider: it decides at the node
    agent = make_agent(api)
    assert agent["published"]["provider_id"] is None and agent["published"]["retries"] is None
    llm.hits.clear()
    run = _run(api, _flow(api, agent))
    assert llm.completions()[0]["json"]["model"] == "small"  # the provider's default model
    step = next(r for r in run["node_results"] if r["kind"] == "agent")
    detail = api.get(
        f"/api/tasks/{run['task']['id']}/executions/{run['execution_id']}/steps/{step['id']}"
    ).json()["detail"]
    assert detail["settings"]["retries"] == 3 and detail["settings"]["max_iterations"] == 10


def test_a_node_override_wins_over_the_agent_and_the_agent_over_the_default(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    agent = make_agent(api, max_tokens=50, temperature=0.4, limits_enabled=True)
    llm.hits.clear()
    _run(api, _flow(api, agent, max_tokens=7))
    sent = llm.completions()[0]["json"]
    assert (sent["max_tokens"], sent["temperature"]) == (7, 0.4)  # node, then agent


def test_without_any_provider_the_node_says_what_is_missing(api: TestClient) -> None:
    agent = make_agent(api)  # published although nothing chooses a provider
    run = _run(api, _flow(api, agent), "failed")
    reason = next(r for r in run["node_results"] if r["kind"] == "agent")["reason"]
    assert "provider" in reason.lower()
