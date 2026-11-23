"""The metadata every setting carries for the node dialog (ADR-053): where it goes (section), how prominent it is (level)
and what it inherits from. Persisted configurations are not touched by it."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openartifact.graph.node_types import NODE_TYPES, ON_FAILURE, Setting, node_type
from openartifact.models import NodeKind


def test_a_setting_without_metadata_is_a_core_setting_of_the_definition_with_no_parent() -> None:
    plain = Setting("x", "X", "text")
    assert (plain.section, plain.level, plain.inherits) == ("definition", "core", None)
    described = plain.describe()
    assert (described["section"], described["level"], described["inherits"]) == (
        "definition",
        "core",
        None,
    )


def test_the_old_keys_of_a_description_keep_their_meaning() -> None:
    data = Setting(
        "n",
        "N",
        "integer",
        minimum=1,
        maximum=5,
        default=3,
        stored_in="config",
        group="G",
        references="all",
    ).describe()
    assert {
        k: data[k]
        for k in (
            "key",
            "label",
            "type",
            "minimum",
            "maximum",
            "default",
            "stored_in",
            "group",
            "references",
        )
    } == {
        "key": "n",
        "label": "N",
        "type": "integer",
        "minimum": 1,
        "maximum": 5,
        "default": 3,
        "stored_in": "config",
        "group": "G",
        "references": "all",
    }


@pytest.mark.parametrize(
    "bad",
    [{"section": "middle"}, {"level": "expert"}, {"inherits": ""}],
)
def test_metadata_that_means_nothing_is_refused_when_the_setting_is_declared(
    bad: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match=next(iter(bad))):
        Setting("x", "X", "text", **bad)


def test_every_kind_declares_valid_metadata_and_the_shared_failure_setting_is_behaviour() -> None:
    assert (ON_FAILURE.section, ON_FAILURE.level, ON_FAILURE.inherits) == (
        "behaviour",
        "core",
        None,
    )
    for node in NODE_TYPES.values():
        for setting in node.settings:
            assert setting.section in ("definition", "behaviour"), (node.kind, setting.key)
            assert setting.level in ("core", "optional", "advanced"), (node.kind, setting.key)
        keys = [s.key for s in node.settings if s.key == "on_failure"]
        assert all(s.section == "behaviour" for s in node.settings if s.key == "on_failure"), (
            node.kind
        )
        assert len(keys) <= 1


def _by_key(kind: NodeKind) -> dict[str, Setting]:
    return {s.key: s for s in node_type(kind).settings}


def test_the_agent_overrides_inherit_from_the_agent_and_sit_in_their_groups() -> None:
    settings = _by_key(NodeKind.AGENT)
    for key in ("provider_id", "model", "temperature", "max_tokens"):
        assert (
            settings[key].section,
            settings[key].level,
            settings[key].inherits,
            settings[key].group,
        ) == ("behaviour", "optional", "agent", "Model & Generation"), key
    for key in ("request_timeout_seconds", "total_timeout_seconds", "retries", "max_iterations"):
        assert (
            settings[key].section,
            settings[key].level,
            settings[key].inherits,
            settings[key].group,
        ) == ("behaviour", "optional", "agent", "Execution limits"), key
    for key in ("system_prompt_enabled", "system_prompt", "user_prompt"):
        assert (settings[key].section, settings[key].level, settings[key].inherits) == (
            "definition",
            "core",
            "agent",
        ), key
    for key in ("agent_id", "inputs"):
        assert (settings[key].section, settings[key].inherits) == ("definition", None), (
            key
        )  # the agent block draws these itself
    assert settings["on_failure"].section == "behaviour"


def test_only_the_agent_inherits_anything() -> None:
    for node in NODE_TYPES.values():
        inheriting = [s.key for s in node.settings if s.inherits]
        assert not inheriting or node.kind is NodeKind.AGENT, (node.kind, inheriting)


def test_if_and_switch_are_all_definition_and_have_no_behaviour_column() -> None:
    for kind in (NodeKind.IF, NodeKind.SWITCH):
        assert {s.section for s in node_type(kind).settings} == {"definition"}


def test_http_and_code_put_how_they_run_in_the_behaviour_section() -> None:
    http = _by_key(NodeKind.HTTP)
    assert [http[k].section for k in ("method", "url", "headers", "body")] == ["definition"] * 4
    assert (http["timeout_seconds"].section, http["timeout_seconds"].level) == (
        "behaviour",
        "optional",
    )
    assert (http["success_status"].section, http["success_status"].level) == (
        "behaviour",
        "advanced",
    )
    assert (http["on_failure"].section, http["on_failure"].level) == ("behaviour", "core")
    code = _by_key(NodeKind.CODE)
    assert [code[k].section for k in ("language", "code")] == ["definition"] * 2
    assert [(code[k].section, code[k].level) for k in ("secrets", "sets_variables")] == [
        ("definition", "advanced")
    ] * 2
    assert (code["timeout_seconds"].section, code["timeout_seconds"].level) == (
        "behaviour",
        "optional",
    )


def test_the_editor_receives_the_metadata(client: TestClient) -> None:
    kinds = {k["kind"]: k for k in client.get("/api/node-types").json()}
    agent = {s["key"]: s for s in kinds["agent"]["settings"]}
    assert (
        agent["temperature"]["section"],
        agent["temperature"]["level"],
        agent["temperature"]["inherits"],
    ) == ("behaviour", "optional", "agent")
    http = {s["key"]: s for s in kinds["http"]["settings"]}
    assert http["success_status"]["level"] == "advanced"
    assert all(
        "section" in s and "level" in s and "inherits" in s
        for k in kinds.values()
        for s in k["settings"]
    )


def test_what_the_agent_node_inherits_is_exactly_what_a_node_may_override() -> None:
    """The single source: the settings with a parent are the agent's OVERRIDABLE fields (the browser has no list of its own)."""
    from openartifact.agents.schemas import OVERRIDABLE

    inheriting = {s.key for s in node_type(NodeKind.AGENT).settings if s.inherits}
    assert inheriting == set(OVERRIDABLE)


def test_the_bounds_of_an_override_are_the_agents_own_and_come_from_the_server() -> None:
    settings = _by_key(NodeKind.AGENT)
    assert (settings["max_iterations"].minimum, settings["max_iterations"].maximum) == (1, 50)
    assert (settings["max_tokens"].minimum, settings["max_tokens"].maximum) == (1, 8192)
