"""Agents without a database: the configuration and its bounds, inputs and prompts, overrides."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from openartifact.agents.render import (
    MappingError,
    RenderError,
    fill,
    input_problems,
    parse_mapping,
    placeholders,
    prompt_problems,
    resolve_inputs,
)
from openartifact.agents.resolve import (
    ProviderInfo,
    freeze,
    merged,
    overrides_of,
    pick_provider,
    setting_states,
)
from openartifact.agents.schemas import OVERRIDABLE, AgentConfig, InputSpec
from openartifact.agents.service import publish_problems
from openartifact.engine.context import NodeIndex, RunContext, RunView
from openartifact.graph.node_types import SettingError, node_type

# ── the configuration ────────────────────────────────────────────────


def test_a_configuration_has_the_agreed_defaults() -> None:
    config = AgentConfig()
    assert (config.request_timeout_seconds, config.total_timeout_seconds, config.retries) == (
        60,
        600,
        3,
    )
    assert config.system_prompt_enabled is False
    assert config.temperature is None and config.max_tokens is None
    assert config.provider_id is None and config.model is None


@pytest.mark.parametrize(
    "change",
    [
        {"max_tokens": 8193},
        {"max_tokens": 0},
        {"temperature": 2.1},
        {"temperature": -0.1},
        {"request_timeout_seconds": 301},
        {"request_timeout_seconds": 0},
        {"total_timeout_seconds": 1801},
        {"retries": 5},
        {"retries": -1},
        {"user_prompt": "x" * 20001},
        {"user_prompt": "a\x00b"},
        {"unknown": 1},
        {"inputs": [{"name": "Ticket"}]},
        {"inputs": [{"name": "a"}, {"name": "a"}]},
        {"inputs": [{"name": "a", "type": "date"}]},
        {"inputs": [{"name": "a", "required": True, "default": "x"}]},
        {"inputs": [{"name": "a", "type": "number", "default": "x"}]},
        {"inputs": [{"name": "a", "type": "boolean", "default": 1}]},
        {"inputs": [{"name": "a", "default": "x" * 20001}]},
        {"inputs": [{"name": f"i{n}"} for n in range(31)]},
    ],
)
def test_values_outside_the_bounds_are_refused(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AgentConfig.model_validate(change)


def test_the_bounds_themselves_are_accepted_and_blank_references_mean_none() -> None:
    config = AgentConfig.model_validate(
        {
            "max_tokens": 8192,
            "temperature": 2,
            "request_timeout_seconds": 300,
            "total_timeout_seconds": 1800,
            "retries": 4,
            "provider_id": "  ",
            "model": "",
            "inputs": [
                {"name": "n", "type": "number", "default": 1.5},
                {"name": "b", "type": "boolean", "default": True},
                {"name": "s", "default": ""},
            ],
        }
    )
    assert config.provider_id is None and config.model is None
    assert config.inputs[2].default is None  # an empty default is no default


def test_a_stored_configuration_survives_a_round_trip_and_garbage_is_the_default() -> None:
    config = AgentConfig(user_prompt="Hi ${input.a}", inputs=[InputSpec(name="a")])
    assert AgentConfig.loads(config.dumps()) == config
    assert AgentConfig.loads("not json") == AgentConfig()
    assert AgentConfig.loads("[1]") == AgentConfig()
    assert AgentConfig.loads(None) == AgentConfig()


# ── prompts ──────────────────────────────────────────────────────────


def test_placeholders_are_found_in_order_without_repeats() -> None:
    assert placeholders("${input.b} and ${input.a}, again ${input.b}") == ["b", "a"]


def test_a_prompt_takes_only_declared_input_placeholders() -> None:
    assert (
        prompt_problems("Do ${input.ticket} now, $HOME and ${other}", ["ticket"], "User prompt")
        == []
    )
    problems = prompt_problems(
        "${node.Fetch.output} ${var.x} ${card.kind} ${secret:KEY} ${input.missing} ${input.Bad} ${input.",
        ["ticket"],
        "User prompt",
    )
    text = "\n".join(problems)
    for reference in ("${node.Fetch.output}", "${var.x}", "${card.kind}", "${secret:KEY}"):
        assert f"{reference} is not allowed" in text
    assert "${input.missing} is not a declared input" in text
    assert "${input.Bad} is not a valid placeholder" in text
    assert all(p.startswith("User prompt: ") for p in problems)
    # without a list of declared inputs only the form is checked (a node's own prompt)
    assert prompt_problems("${input.anything}", None, "Prompt") == []
    assert prompt_problems("${var.x}", None, "Prompt") != []


# ── the mapping of a node ────────────────────────────────────────────


def test_a_mapping_is_name_equals_value_per_line() -> None:
    mapping = parse_mapping("ticket = ${node.Fetch.output}\n\n  input.context=a = b \nempty =\n")
    assert mapping == {"ticket": "${node.Fetch.output}", "context": "a = b", "empty": ""}
    assert parse_mapping("") == {}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("ticket", "Line 1 is not 'name = value'"),
        ("ok = 1\nBad Name = 2", "Line 2 is not 'name = value'"),
        ("a = 1\na = 2", "Input 'a' is mapped twice"),
        ("a = ${secret:KEY}", "cannot be an input of an agent"),
        ("\n".join(f"i{n} = x" for n in range(31)), "At most 30 inputs"),
    ],
)
def test_a_wrong_mapping_says_what_is_wrong(text: str, message: str) -> None:
    with pytest.raises(MappingError, match=message):
        parse_mapping(text)


def _view(**nodes: str) -> RunView:
    context = RunContext({"vars": {"lang": "German", "count": 3}, "card": {"tier": "gold"}})
    listed: list[dict[str, str]] = []
    graph: dict[str, Any] = {"name": "Act", "nodes": listed}
    for name, output in nodes.items():
        listed.append({"id": name, "name": name, "kind": "http"})
        context.nodes[name] = {"output": output, "data": {"k": [1, {"deep": "v"}]}}
    return RunView(context, NodeIndex.of_graphs([graph]))


SPECS: list[dict[str, Any]] = [
    {"name": "ticket", "type": "string", "required": True},
    {"name": "context", "type": "string", "required": False, "default": "none"},
    {"name": "note", "type": "string", "required": False},
    {"name": "count", "type": "number", "required": False},
    {"name": "urgent", "type": "boolean", "required": False},
]


def test_inputs_are_resolved_from_the_run_context() -> None:
    mapping = {
        "ticket": "Ticket: ${node.Fetch.output} (${node.Fetch.data.k.1.deep})",
        "count": "${var.count}",
        "urgent": " TRUE ",
        "note": "${card.tier}",
    }
    states = {s.name: s for s in resolve_inputs(SPECS, mapping, _view(Fetch="broken login"))}
    assert states["ticket"].value == "Ticket: broken login (v)"
    assert states["ticket"].state == "mapped"
    assert states["ticket"].source == mapping["ticket"]
    assert (states["context"].state, states["context"].value) == ("default", "none")
    assert (states["note"].state, states["note"].value) == ("mapped", "gold")
    assert states["count"].value == "3"
    assert states["urgent"].state == "mapped"
    assert input_problems(list(states.values())) == []


def test_an_optional_input_without_mapping_and_default_is_empty_and_says_so() -> None:
    states = {s.name: s for s in resolve_inputs(SPECS, {"ticket": "t"}, _view())}
    assert (states["note"].state, states["note"].value) == ("unset", "")
    assert states["note"].error is None


def test_typed_defaults_are_rendered_as_text() -> None:
    specs = [
        {"name": "n", "type": "number", "default": 1.5},
        {"name": "b", "type": "boolean", "default": False},
    ]
    assert [s.value for s in resolve_inputs(specs, {}, _view())] == ["1.5", "false"]


def test_what_is_wrong_with_the_inputs_is_an_error_never_an_empty_text() -> None:
    mapping = {
        "context": "${node.Missing.output}",
        "note": "${var.unset}",
        "count": "many",
        "urgent": "maybe",
        "extra": "x",
    }
    states = resolve_inputs(SPECS, mapping, _view())
    by_name = {s.name: s for s in states}
    assert all(by_name[n].state == "error" for n in mapping)
    assert by_name["ticket"].error == "required input 'ticket' is not mapped"
    assert (
        by_name["context"].value is None
    )  # a mapping that fails does not fall back to the default
    assert 'no node is named "Missing"' in (by_name["context"].error or "")
    assert "variable 'unset' is not set" in (by_name["note"].error or "")
    assert by_name["count"].error == "input 'count' is not a number"
    assert by_name["urgent"].error == "input 'urgent' is neither true nor false"
    assert by_name["extra"].error == "input 'extra' is not declared by the agent"
    assert len(input_problems(states)) == 6


def test_a_required_input_that_resolves_to_nothing_is_an_error() -> None:
    view = RunView(RunContext({"vars": {"empty": ""}}))
    (state,) = resolve_inputs([SPECS[0]], {"ticket": "${var.empty}"}, view)
    assert state.error == "required input 'ticket' is empty"


def test_a_secret_is_never_a_source_even_if_it_got_into_a_mapping() -> None:
    (state,) = resolve_inputs([SPECS[0]], {"ticket": "${secret:KEY}"}, _view())
    assert state.state == "error" and "cannot be an input" in (state.error or "")


def test_a_preview_cannot_know_the_run_and_takes_example_values() -> None:
    mapping = {"ticket": "${node.Fetch.output}", "note": "fixed text"}
    states = {s.name: s for s in resolve_inputs(SPECS, mapping, None)}
    assert (states["ticket"].state, states["ticket"].value) == ("pending", None)
    assert (states["note"].state, states["note"].value) == ("mapped", "fixed text")
    assert input_problems(list(states.values())) == []
    sampled = {
        s.name: s
        for s in resolve_inputs(SPECS, mapping, None, samples={"ticket": "T-1", "count": "x"})
    }
    assert (sampled["ticket"].state, sampled["ticket"].value) == ("sample", "T-1")
    assert sampled["ticket"].source == "${node.Fetch.output}"
    assert sampled["count"].state == "error"


def test_prompts_are_filled_in_one_pass() -> None:
    states = resolve_inputs(
        SPECS[:3], {"ticket": "${var.lang}", "note": "${input.ticket} $1 \\1"}, _view()
    )
    assert (
        fill("A ${input.ticket} B ${input.context} C ${input.note} ${input.ticket}", states)
        == "A German B none C ${input.ticket} $1 \\1 German"
    )


def test_filling_fails_for_an_unknown_or_failed_input_unless_it_is_a_preview() -> None:
    states = resolve_inputs(SPECS[:1], {}, _view())
    with pytest.raises(RenderError, match="is not a declared input"):
        fill("${input.other}", states)
    with pytest.raises(RenderError, match="required input 'ticket' is not mapped"):
        fill("${input.ticket}", states)
    assert (
        fill("${input.ticket} ${input.other}", states, preview=True)
        == "${input.ticket} ${input.other}"
    )
    pending = resolve_inputs(SPECS[:1], {"ticket": "${var.x}"}, None)
    assert fill("Do ${input.ticket}", pending) == "Do ${input.ticket}"


# ── overrides and the provider in effect ─────────────────────────────


def _provider(
    pid: str, *models: str, default: bool = False, default_model: str | None = None
) -> ProviderInfo:
    return ProviderInfo(
        id=pid,
        kind="openai_compatible",
        name=pid.upper(),
        base_url=f"https://{pid}.example/v1",
        secret_name="KEY_" + pid.upper(),
        allow_private=False,
        default_model=default_model,
        is_default=default,
        models=frozenset(models),
    )


AGENT = AgentConfig(
    user_prompt="U ${input.a}",
    system_prompt="S",
    inputs=[InputSpec(name="a")],
    provider_id="p1",
    model="m1",
    temperature=0.2,
).model_dump()
PROVIDERS = {
    "p1": _provider("p1", "m1", "m2", default_model="m2"),
    "p2": _provider("p2", "x1", default=True, default_model="x1"),
    "p3": _provider("p3", "y1"),
}


def test_a_node_setting_that_is_not_set_is_inherited() -> None:
    node = {"agent_id": "a", "inputs": "a = 1", "temperature": None, "retries": 0, "max_tokens": 50}
    assert overrides_of(node) == {"retries": 0, "max_tokens": 50}
    assert overrides_of(None) == {}
    values = merged(AGENT, node)
    assert set(values) == set(OVERRIDABLE)
    assert (values["temperature"], values["retries"], values["max_tokens"]) == (0.2, 0, 50)
    states = {s.key: s for s in setting_states(AGENT, node)}
    assert states["retries"].overridden and states["retries"].inherited == 3
    assert not states["temperature"].overridden and states["temperature"].value == 0.2
    # a value the agent does not set can be switched on by the node: that is an override too
    assert states["max_tokens"].overridden and states["max_tokens"].inherited is None


def test_switching_the_system_prompt_off_is_an_override_although_it_is_false() -> None:
    agent = {**AGENT, "system_prompt_enabled": True}
    assert overrides_of({"system_prompt_enabled": False}) == {"system_prompt_enabled": False}
    assert merged(agent, {"system_prompt_enabled": False})["system_prompt_enabled"] is False


@pytest.mark.parametrize(
    ("agent", "node", "provider", "model", "problem"),
    [
        ({}, {}, "p1", "m1", None),
        ({}, {"model": "m2"}, "p1", "m2", None),
        # the node moves to another provider: the agent's model was chosen for p1, so p2's default applies
        ({}, {"provider_id": "p2"}, "p2", "x1", None),
        ({}, {"provider_id": "p2", "model": "x1"}, "p2", "x1", None),
        (
            {},
            {"provider_id": "p3"},
            "p3",
            None,
            'No model is set and provider "P3" has no default model',
        ),
        ({}, {"model": "nope"}, "p1", "nope", 'Model "nope" is not enabled for provider "P1"'),
        ({}, {"provider_id": "gone"}, None, None, "The provider of the agent no longer exists"),
        # an agent without a provider uses the default provider; its model belongs to that one
        ({"provider_id": None, "model": None}, {}, "p2", "x1", None),
        ({"provider_id": None, "model": "x1"}, {}, "p2", "x1", None),
        ({"provider_id": None, "model": "m1"}, {"provider_id": "p1"}, "p1", "m2", None),
        ({"model": None}, {}, "p1", "m2", None),
    ],
)
def test_the_provider_and_model_in_effect(
    agent: dict[str, Any],
    node: dict[str, Any],
    provider: str | None,
    model: str | None,
    problem: str | None,
) -> None:
    found, got_model, problems = pick_provider({**AGENT, **agent}, node, PROVIDERS)
    assert (found.id if found else None, got_model) == (provider, model)
    assert problems == ([problem] if problem else [])


def test_without_a_default_provider_an_agent_without_one_cannot_be_resolved() -> None:
    providers = {"p1": PROVIDERS["p1"]}
    _, _, problems = pick_provider({**AGENT, "provider_id": None}, {}, providers)
    assert problems == ["No provider is set and there is no default provider"]


def test_freezing_keeps_everything_a_run_needs_and_never_a_key() -> None:
    agent = {"id": "a1", "name": "Triage", "active": True, "version": 4, "config": AGENT}
    frozen = freeze(agent, {"agent_id": "a1", "retries": 1, "inputs": "a = x"}, PROVIDERS)
    assert frozen["error"] is None
    assert (frozen["agent_id"], frozen["name"], frozen["version"], frozen["active"]) == (
        "a1",
        "Triage",
        4,
        True,
    )
    assert frozen["config"] == AGENT
    assert frozen["overrides"] == {"retries": 1}
    assert frozen["settings"]["retries"] == 1 and frozen["settings"]["temperature"] == 0.2
    assert (frozen["settings"]["provider_id"], frozen["settings"]["model"], frozen["model"]) == (
        "p1",
        "m1",
        "m1",
    )
    assert frozen["inputs"] == AGENT["inputs"]
    assert frozen["provider"] == {
        "id": "p1",
        "kind": "openai_compatible",
        "name": "P1",
        "base_url": "https://p1.example/v1",
        "secret_name": "KEY_P1",
        "allow_private": False,
    }


@pytest.mark.parametrize(
    ("agent", "node", "error"),
    [
        (None, {}, "No agent is chosen"),
        (None, {"agent_id": "gone"}, "The agent of this node no longer exists"),
        ({"config": None}, {"agent_id": "a1"}, 'Agent "Triage" has no published version'),
        ({"active": False}, {"agent_id": "a1"}, 'Agent "Triage" is inactive'),
        ({}, {"agent_id": "a1", "model": "nope"}, 'Model "nope" is not enabled for provider "P1"'),
    ],
)
def test_a_node_that_cannot_run_is_frozen_with_the_reason(
    agent: dict[str, Any] | None, node: dict[str, Any], error: str
) -> None:
    base = {"id": "a1", "name": "Triage", "active": True, "version": 1, "config": AGENT}
    frozen = freeze(None if agent is None else {**base, **agent}, node, PROVIDERS)
    assert frozen["error"] == error


# ── what can be published ────────────────────────────────────────────


def test_a_complete_configuration_can_be_published() -> None:
    assert publish_problems(AgentConfig.model_validate(AGENT), PROVIDERS) == []
    # neither provider nor model: the default provider and the node decide
    assert publish_problems(AgentConfig(user_prompt="Hi"), {}) == []


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"user_prompt": "  "}, "The user prompt is empty"),
        ({"user_prompt": "${input.b}"}, "User prompt: ${input.b} is not a declared input"),
        ({"user_prompt": "${var.x}"}, "User prompt: ${var.x} is not allowed"),
        ({"system_prompt": "${node.A.output}"}, "System prompt: ${node.A.output} is not allowed"),
        (
            {"system_prompt_enabled": True, "system_prompt": ""},
            "The system prompt is switched on but empty",
        ),
        ({"provider_id": "gone"}, "The chosen provider does not exist"),
        ({"model": "nope"}, 'Model "nope" is not enabled for provider "P1"'),
    ],
)
def test_what_publishing_refuses(change: dict[str, Any], problem: str) -> None:
    problems = publish_problems(AgentConfig.model_validate({**AGENT, **change}), PROVIDERS)
    assert any(p.startswith(problem) for p in problems), problems


def test_a_model_without_any_provider_cannot_be_published() -> None:
    config = AgentConfig(user_prompt="Hi", model="m1")
    assert publish_problems(config, {"p1": PROVIDERS["p1"]}) == [
        "A model is chosen but no provider, and there is no default provider"
    ]


# ── the settings of the node ─────────────────────────────────────────


def test_the_agent_node_is_an_execution_node_whose_overrides_have_no_default() -> None:
    kind = node_type("agent")
    assert kind.describe()["scopes"] == ["action"]
    assert kind.addable and kind.output_names() == ("pass", "fail")
    effective = kind.effective_config({"agent_id": "a1"})
    assert effective["agent_id"] == "a1" and effective["inputs"] == ""
    assert all(effective[key] is None for key in OVERRIDABLE)
    assert effective["on_failure"] == "fail"


def test_overrides_are_validated_merged_and_reset_per_key() -> None:
    kind = node_type("agent")
    config = kind.merge_config(
        None,
        {
            "temperature": 0.5,
            "max_tokens": 100,
            "system_prompt_enabled": False,
            "user_prompt": "Do ${input.a}",
        },
    )
    assert config == {
        "temperature": 0.5,
        "max_tokens": 100,
        "system_prompt_enabled": False,
        "user_prompt": "Do ${input.a}",
    }
    config = kind.merge_config(config, {"temperature": None, "retries": 0})
    assert "temperature" not in config and config["retries"] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"max_tokens": 8193},
        {"temperature": 3},
        {"temperature": "hot"},
        {"temperature": True},
        {"request_timeout_seconds": 301},
        {"total_timeout_seconds": 1801},
        {"retries": 5},
        {"inputs": "no equals sign"},
        {"inputs": "a = ${secret:KEY}"},
        {"user_prompt": "${node.Other.output}"},
        {"system_prompt": "${secret:KEY}"},
        {"system_prompt": "${input.Bad}"},
        {"nonsense": 1},
    ],
)
def test_a_wrong_override_is_refused(change: dict[str, Any]) -> None:
    with pytest.raises(SettingError):
        node_type("agent").merge_config(None, change)
