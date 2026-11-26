"""The answer format in a real run: the model reports through the tool, one repair, a later node reads the data (ADR-085)."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from tests.agent_support import FakeLlm, completion, make_agent, make_provider
from tests.helpers import (
    build_pipeline,
    connect,
    graph_url,
    kind_of,
    link,
    node,
    post,
)
from tests.test_agent_tools_run import api, llm, tool_answer
from tests.test_handover_tool import run

__all__ = ["api", "llm"]  # the fixtures of the agent tool tests, used by name

FORMAT = [
    {"name": "passed", "type": "boolean", "required": True, "description": "Whether it holds"},
    {"name": "verdict", "type": "choice", "required": True, "choices": ["ship", "fix"]},
    {"name": "reasons", "type": "list"},
]
GOOD = {"passed": True, "verdict": "ship", "reasons": ["clear", "short"]}


def answer_flow(client: TestClient) -> dict[str, Any]:
    """trigger -> agent "Ask" (with an answer format) -> Edit Fields "Use" (reads its data) -> Output."""
    agent = make_agent(client)
    action = post(client, "/api/actions", name="Review")
    trigger, output = kind_of(client, action, "trigger"), kind_of(client, action, "output")
    for edge in client.get(graph_url(action)).json()["edges"]:
        client.delete(f"{graph_url(action)}/edges/{edge['id']}")
    ask = node(
        client,
        action,
        "agent",
        name="Ask",
        config={"agent_id": agent["id"], "inputs": "ticket = T-1", "answer_format": FORMAT},
    )
    use = node(
        client,
        action,
        "set",
        name="Use",
        config={"fields": "line = ${(Ask).data.verdict}: ${(Ask).data.passed}"},
    )
    connect(client, action, trigger, "out", ask, "in")
    connect(client, action, ask, "pass", use, "in")
    connect(client, action, use, "pass", output, "pass")
    pipeline = build_pipeline(client, stages=1)
    link(client, pipeline, pipeline["stages"][0][1], action)
    return pipeline


def test_the_report_is_the_answer_and_a_later_node_reads_its_fields(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    pipeline = answer_flow(api)
    llm.script = [(200, tool_answer(("c1", "report_result", GOOD)))]
    found = run(api, pipeline)
    assert len(llm.completions()) == 1  # the report ends the node: no request after it
    (first,) = llm.completions()
    assert [t["function"]["name"] for t in first["json"]["tools"]] == ["report_result"]
    entry = found["context"]["nodes"]["Ask"]
    assert (entry["kind"], entry["success"], entry["outcome"]) == ("agent", True, "pass")
    assert entry["data"]["passed"] is True and entry["data"]["verdict"] == "ship"
    assert entry["data"]["reasons"] == ["clear", "short"]
    assert json.loads(entry["output"]) == GOOD
    assert found["context"]["vars"] == {
        "line": "ship: true"
    }  # ${(Ask).data.verdict}: ${(Ask).data.passed}
    assert found["step"]["data"]["repaired"] is False


def test_a_report_that_does_not_fit_is_repaired_once_and_both_calls_stay_in_the_step(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    pipeline = answer_flow(api)
    llm.script = [
        (200, tool_answer(("c1", "report_result", {"passed": "yes", "extra": 1}))),
        (200, tool_answer(("c2", "report_result", GOOD))),
    ]
    found = run(api, pipeline)
    _first, second = llm.completions()
    refusal = second["json"]["messages"][-1]["content"]
    assert refusal.startswith("Error: the answer was not accepted:")
    assert "'passed' must be true or false" in refusal and "'verdict' is required" in refusal
    assert "unknown field 'extra'" in refusal
    assert found["step"]["data"]["repaired"] is True and found["step"]["data"]["answer_calls"] == 2
    calls = [c for t in found["read"]["detail"]["turns"] for c in t["tool_calls"]]
    assert [c["error"] for c in calls] == [True, False]
    assert found["context"]["vars"] == {"line": "ship: true"}


def test_a_report_that_does_not_fit_twice_fails_the_node_and_the_flow_stops(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    pipeline = answer_flow(api)
    llm.script = [
        (200, tool_answer(("c1", "report_result", {"passed": "yes"}))),
        (200, tool_answer(("c2", "report_result", {"passed": "no"}))),
    ]
    found = run(api, pipeline, status="failed")
    assert len(llm.completions()) == 2
    reason = found["step"]["reason"]
    assert "also after one correction" in reason and "'passed' must be true or false" in reason
    assert "Use" not in {s["node_name"] for s in found["steps"].values()}  # the next node never ran


def test_an_if_node_branches_on_a_field_of_the_answer(api: TestClient, llm: FakeLlm) -> None:
    make_provider(api, llm)
    agent = make_agent(api)
    action = post(api, "/api/actions", name="Branch")
    trigger, output = kind_of(api, action, "trigger"), kind_of(api, action, "output")
    for edge in api.get(graph_url(action)).json()["edges"]:
        api.delete(f"{graph_url(action)}/edges/{edge['id']}")
    ask = node(
        api,
        action,
        "agent",
        name="Ask",
        config={"agent_id": agent["id"], "inputs": "ticket = T-1", "answer_format": FORMAT},
    )
    decide = node(
        api,
        action,
        "if",
        name="Decide",
        config={"left_1": "${(Ask).data.passed}", "operator_1": "equals", "right_1": "true"},
    )
    went = node(api, action, "set", name="Went", config={"fields": "route = yes"})
    connect(api, action, trigger, "out", ask, "in")
    connect(api, action, ask, "pass", decide, "in")
    connect(api, action, decide, "yes", went, "in")
    connect(api, action, went, "pass", output, "pass")
    pipeline = build_pipeline(api, stages=1)
    link(api, pipeline, pipeline["stages"][0][1], action)
    llm.script = [(200, tool_answer(("c1", "report_result", GOOD)))]
    found = run(api, pipeline)
    assert found["context"]["vars"] == {
        "route": "yes"
    }  # ${(Ask).data.passed} is true: the yes path
    assert found["context"]["nodes"]["Decide"]["port"] == "yes"


def test_a_second_refusal_leaves_by_on_fail_with_the_reasons(api: TestClient, llm: FakeLlm) -> None:
    make_provider(api, llm)
    agent = make_agent(api)
    action = post(api, "/api/actions", name="Fallback")
    trigger, output = kind_of(api, action, "trigger"), kind_of(api, action, "output")
    for edge in api.get(graph_url(action)).json()["edges"]:
        api.delete(f"{graph_url(action)}/edges/{edge['id']}")
    ask = node(
        api,
        action,
        "agent",
        name="Ask",
        config={"agent_id": agent["id"], "inputs": "ticket = T-1", "answer_format": FORMAT},
    )
    fallback = node(api, action, "set", name="Fallback", config={"fields": "route = rework"})
    connect(api, action, trigger, "out", ask, "in")
    connect(api, action, ask, "fail", fallback, "in")  # switches On Fail on, as the editor does
    connect(api, action, fallback, "pass", output, "pass")
    pipeline = build_pipeline(api, stages=1)
    link(api, pipeline, pipeline["stages"][0][1], action)
    llm.script = [
        (200, tool_answer(("c1", "report_result", {"passed": "yes"}))),
        (200, tool_answer(("c2", "report_result", {"passed": "no"}))),
    ]
    found = run(api, pipeline)
    assert found["context"]["vars"] == {"route": "rework"}  # the flow went on by On Fail
    entry = found["context"]["nodes"]["Ask"]
    assert (entry["outcome"], entry["success"]) == ("fail", False)
    assert "also after one correction" in entry["reason"]
    assert "'passed' must be true or false" in entry["reason"]


def test_a_text_answer_gets_one_reminder_then_the_report_counts(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    pipeline = answer_flow(api)
    llm.script = [
        (200, completion("It holds.")),
        (200, tool_answer(("c1", "report_result", GOOD))),
    ]
    found = run(api, pipeline)
    _first, second = llm.completions()
    reminder = second["json"]["messages"][-1]
    assert reminder["role"] == "user" and "report_result" in reminder["content"]
    assert found["context"]["vars"] == {"line": "ship: true"}
