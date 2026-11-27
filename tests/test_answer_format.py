"""The answer format of an agent: the final answer as a checked document, one repair (ADR-085)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from openartifact.agents import answer_format
from openartifact.agents.client import Completion
from openartifact.agents.resolve import ProviderInfo, freeze
from openartifact.agents.runtime import run_node
from openartifact.agents.schemas import AgentConfig, InputSpec
from openartifact.agents.tools import Tool
from openartifact.graph import field_schema
from tests.agent_support import make_agent
from tests.helpers import graph_url
from tests.test_agent_loop import WEATHER, Recorder, _asks, _box, _with_tools
from tests.test_agent_runtime import OK, VIEW, Scripted, _frozen
from tests.test_agents_api import _agent_node, api  # noqa: F401 (the fixture of the API tests)

REVIEW = [
    {"name": "passed", "type": "boolean", "required": True, "description": "Did it pass?"},
    {"name": "reasons", "type": "list", "required": False, "description": ""},
    {
        "name": "verdict",
        "type": "choice",
        "required": False,
        "description": "",
        "choices": ["ship", "fix"],
    },
]
GOOD = '{"passed": true, "reasons": ["clear", "short"], "verdict": "ship"}'
BAD = '{"reasons": ["clear"], "verdict": "maybe", "extra": 1}'


def _report(arguments: str, call_id: str = "r1") -> Completion:
    return _asks((call_id, "report_result", arguments))


async def _run(script: Scripted, frozen: dict[str, Any] | None = None, tools: Any = None) -> Any:
    return await run_node(
        frozen or _frozen(answer_format=REVIEW),
        VIEW,
        "key",
        complete=script.complete,
        sleep=script.sleep,
        open_tools=tools or _box(),
    )


async def test_a_valid_report_is_the_answer_at_once_and_its_fields_are_the_data() -> None:
    script = Scripted(_report(GOOD))
    result = await _run(script)
    assert (
        result.outcome == "pass" and len(script.calls) == 1
    )  # no further request after the answer
    assert result.data["passed"] is True
    assert result.data["reasons"] == ["clear", "short"]
    assert result.data["verdict"] == "ship"
    assert result.data["repaired"] is False and result.data["answer_calls"] == 1
    assert json.loads(result.output) == {
        "passed": True,
        "reasons": ["clear", "short"],
        "verdict": "ship",
    }
    # the model was told the one tool, with exactly the fields as parameters
    (tool,) = script.calls[0]["tools"]
    assert tool["function"]["name"] == "report_result"
    assert tool["function"]["parameters"] == field_schema.json_schema(REVIEW)
    assert result.detail["answer"]["document"]["passed"] is True


async def test_a_report_that_does_not_fit_gets_the_reasons_and_one_repair() -> None:
    script = Scripted(_report(BAD), _report(GOOD, "r2"))
    result = await _run(script)
    assert result.outcome == "pass" and len(script.calls) == 2
    assert result.data["repaired"] is True and result.data["answer_calls"] == 2
    told = script.calls[1]["messages"][-1]
    assert told["role"] == "tool"
    assert told["content"].startswith("Error: the answer was not accepted:")
    for problem in (
        "'passed' is required",
        "'verdict' must be one of: ship, fix",
        "unknown field 'extra'",
    ):
        assert problem in told["content"]  # all problems at once
    assert "corrected once" in (result.reason or "")
    refused = result.detail["answer"]["refused"]
    assert len(refused) == 1 and "'passed' is required" in refused[0]
    calls = [c for t in result.detail["turns"] for c in t["tool_calls"]]
    assert [c["error"] for c in calls] == [True, False]  # both attempts stay in the step


async def test_a_second_report_that_does_not_fit_fails_the_step_with_the_reasons() -> None:
    script = Scripted(_report(BAD), _report('{"passed": "yes"}', "r2"))
    result = await _run(script)
    assert result.outcome == "fail" and len(script.calls) == 2
    assert "also after one correction" in (result.reason or "")
    assert "'passed' must be true or false" in (result.reason or "")
    assert len(result.detail["answer"]["refused"]) == 2
    assert "passed" not in (result.data or {})


async def test_arguments_that_are_no_json_object_count_as_a_report_that_did_not_fit() -> None:
    script = Scripted(_report("not json"), _report(GOOD, "r2"))
    result = await _run(script)
    assert result.outcome == "pass" and result.data["repaired"] is True
    assert "the arguments are not valid JSON" in script.calls[1]["messages"][-1]["content"]


async def test_a_text_answer_gets_one_reminder_and_then_the_report() -> None:
    script = Scripted(Completion("It passed.", "stop", 3, 1, 4, 200), _report(GOOD))
    result = await _run(script)
    assert result.outcome == "pass" and len(script.calls) == 2
    reminder = script.calls[1]["messages"][-1]
    assert reminder["role"] == "user"
    assert reminder["content"] == answer_format.REMINDER.format(tool="report_result")
    assert script.calls[1]["messages"][-2] == {"role": "assistant", "content": "It passed."}


async def test_a_text_answer_twice_fails_the_step() -> None:
    script = Scripted(
        Completion("It passed.", "stop", 3, 1, 4, 200), Completion("Really.", "stop", 3, 1, 4, 200)
    )
    result = await _run(script)
    assert result.outcome == "fail" and len(script.calls) == 2
    assert "did not report a result" in (result.reason or "")
    assert "report_result" in (result.reason or "")


async def test_other_tools_may_come_first_and_the_report_is_added_to_them() -> None:
    weather = Recorder("Sunny")
    script = Scripted(_asks(("c1", "weather", '{"city": "Bonn"}')), _report(GOOD))
    result = await _run(
        script,
        _with_tools(answer_format=REVIEW),
        _box(Tool("weather", "The weather", WEATHER, weather)),
    )
    assert result.outcome == "pass" and weather.seen == [{"city": "Bonn"}]
    names = [t["function"]["name"] for t in script.calls[0]["tools"]]
    assert names == ["weather", "report_result"]
    assert result.data["passed"] is True


async def test_a_tool_named_like_the_report_tool_keeps_its_name_and_the_report_gets_another() -> (
    None
):
    clash = Recorder("x")
    script = Scripted(_asks(("r1", "report_result_2", GOOD)))
    # an MCP tool may be called report_result too: the report tool is added after it and the loop knows the name it was given
    result = await _run(
        script,
        _with_tools(answer_format=REVIEW),
        _box(Tool("report_result", "Another tool", WEATHER, clash)),
    )
    names = [t["function"]["name"] for t in script.calls[0]["tools"]]
    assert names == ["report_result", "report_result_2"]
    assert result.outcome == "pass" and result.data["passed"] is True
    assert clash.seen == []  # the other tool was not called


async def test_at_the_iteration_limit_the_final_request_offers_the_report_tool_only() -> None:
    weather = Recorder("Sunny")
    script = Scripted(_asks(("c1", "weather", '{"city": "Bonn"}')), _report(GOOD, "r1"))
    frozen = _with_tools(answer_format=REVIEW, max_iterations=1)
    result = await _run(script, frozen, _box(Tool("weather", "The weather", WEATHER, weather)))
    assert result.outcome == "pass" and result.data["passed"] is True
    final = script.calls[1]
    assert [t["function"]["name"] for t in final["tools"]] == ["report_result"]
    assert (
        "Give your final answer now by calling the tool report_result"
        in final["messages"][-1]["content"]
    )
    assert "may be incomplete" in (result.reason or "")


async def test_a_text_at_the_iteration_limit_fails_instead_of_inventing_an_answer() -> None:
    weather = Recorder("Sunny")
    script = Scripted(
        _asks(("c1", "weather", '{"city": "Bonn"}')), Completion("Just text", "stop", 3, 1, 4, 200)
    )
    frozen = _with_tools(answer_format=REVIEW, max_iterations=1)
    result = await _run(script, frozen, _box(Tool("weather", "The weather", WEATHER, weather)))
    assert result.outcome == "fail"
    assert "did not report a result with the tool report_result" in (result.reason or "")


async def test_a_secret_reference_in_a_field_stays_literal_text() -> None:
    fields = [{"name": "note", "type": "text", "required": True, "description": ""}]
    script = Scripted(_report('{"note": "${secret:TOKEN} and ${var.ticket}"}'))
    result = await _run(script, _frozen(answer_format=fields))
    assert result.outcome == "pass"
    assert result.data["note"] == "${secret:TOKEN} and ${var.ticket}"  # never read as a reference


async def test_an_agent_without_an_answer_format_is_unchanged() -> None:
    script = Scripted(OK)
    result = await _run(script, _frozen())
    assert (result.outcome, result.output) == ("pass", "Fine")
    assert "tools" not in script.calls[0]
    assert "answer" not in (result.detail or {})
    assert "repaired" not in (result.data or {})


def _agent_with_format(node_config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = AgentConfig(
        user_prompt="Review ${input.ticket}",
        inputs=[InputSpec(name="ticket", required=True)],
        provider_id="p1",
        model="small",
        answer_format=REVIEW,
    ).model_dump()
    providers = {
        "p1": ProviderInfo(
            "p1",
            "openai_compatible",
            "Local",
            "https://llm.example/v1",
            "LLM_KEY",
            True,
            "small",
            True,
            frozenset({"small"}),
        )
    }
    agent = {"id": "a1", "name": "Reviewer", "active": True, "version": 1, "config": config}
    node = {"agent_id": "a1", "inputs": "ticket = ${var.ticket}", **(node_config or {})}
    return {
        "id": "n1",
        "name": "Review",
        "kind": "agent",
        "config": node,
        "agent": freeze(agent, node, providers),
    }


async def test_the_format_of_the_agent_applies_and_a_node_may_switch_it_off_with_an_empty_list() -> (
    None
):
    script = Scripted(_report(GOOD))
    result = await _run(script, _agent_with_format())
    assert result.outcome == "pass" and result.data["passed"] is True
    script = Scripted(OK)
    result = await _run(script, _agent_with_format({"answer_format": []}))
    assert (result.outcome, result.output) == ("pass", "Fine")
    assert "tools" not in script.calls[0]


async def test_a_node_may_set_a_format_of_its_own_over_the_agents() -> None:
    own = [{"name": "ok", "type": "boolean", "required": True, "description": ""}]
    script = Scripted(_report('{"ok": false}'))
    result = await _run(script, _agent_with_format({"answer_format": own}))
    assert result.outcome == "pass" and result.data["ok"] is False and "passed" not in result.data


def test_a_field_named_like_the_data_of_the_agent_is_refused() -> None:
    with pytest.raises(ValidationError, match="'model' is used by the agent's own data"):
        AgentConfig(answer_format=[{"name": "model", "type": "text", "required": False}])
    with pytest.raises(ValueError, match="'usage' is used by the agent's own data"):
        answer_format.fields_of([{"name": "usage", "type": "text", "required": False}])


def test_the_answer_format_is_part_of_the_draft_and_of_the_published_version(
    api: TestClient,  # noqa: F811
) -> None:
    agent = make_agent(api, answer_format=REVIEW)
    assert agent["draft"]["answer_format"] == field_schema.normalise(REVIEW)
    assert agent["published_number"] == 1
    version = api.get(f"/api/agents/{agent['id']}/versions/1").json()
    assert version["config"]["answer_format"] == field_schema.normalise(REVIEW)
    # no format is the default: an agent from before has none and nothing changes for it
    plain = make_agent(api, name="Plain")
    assert plain["draft"]["answer_format"] == []


def test_a_field_named_like_the_data_of_the_agent_is_refused_by_the_api(
    api: TestClient,  # noqa: F811
) -> None:
    agent = make_agent(api)
    draft = {
        **agent["draft"],
        "answer_format": [{"name": "usage", "type": "text", "required": False}],
    }
    response = api.put(f"/api/agents/{agent['id']}/draft", json=draft)
    assert response.status_code == 422
    assert "'usage' is used by the agent's own data" in response.text


def test_a_node_sets_its_own_answer_format_and_the_same_rules_apply(
    api: TestClient,  # noqa: F811
) -> None:
    agent = make_agent(api)
    action, node = _agent_node(api, agent, "Reviewer", answer_format=REVIEW)
    assert node["config"]["answer_format"] == field_schema.normalise(REVIEW)
    url = f"{graph_url(action)}/nodes/{node['id']}"
    refused = api.patch(
        url,
        json={"config": {"answer_format": [{"name": "model", "type": "text", "required": False}]}},
    )
    assert refused.status_code in (400, 422)
    assert "'model' is used by the agent's own data" in refused.text


def test_publishing_a_changed_answer_format_tells_the_nodes_that_set_their_own(
    api: TestClient,  # noqa: F811
) -> None:
    agent = make_agent(api, answer_format=REVIEW)
    _agent_node(api, agent, "Own format", answer_format=REVIEW[:1])
    _agent_node(api, agent, "Follows")
    api.put(
        f"/api/agents/{agent['id']}/draft", json={**agent["draft"], "answer_format": REVIEW[:2]}
    )
    result = api.post(f"/api/agents/{agent['id']}/publish").json()
    assert result["changed"] == ["answer_format"]
    assert [(u["node_name"], u["overrides"]) for u in result["overriding"]] == [
        ("Own format", ["answer_format"])
    ]


def test_the_check_is_the_one_of_the_hand_over_tool() -> None:
    """One module for both: the answer format neither copies the schema nor its check."""
    assert vars(answer_format)["field_schema"] is field_schema
    fields = field_schema.normalise(REVIEW)
    sink = answer_format.AnswerSink()
    tool = answer_format.report_tool(fields, sink)
    assert tool.parameters == field_schema.json_schema(fields)
