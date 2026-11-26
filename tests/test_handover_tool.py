"""The Hand Over Tool: an agent hands over a document, the server checks it, a later node reads it (ADR-080)."""

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
    make_task,
    node,
    post,
    wait_for_run,
)
from tests.test_agent_tools_run import api, llm, tool_answer

__all__ = ["api", "llm"]  # the fixtures of the agent tool tests, used by name

FIELDS = [
    {"name": "passed", "type": "boolean", "required": True, "description": "Whether it holds"},
    {"name": "verdict", "type": "choice", "required": True, "choices": ["approve", "reject"]},
    {"name": "reasons", "type": "list"},
    {"name": "note", "type": "text"},
]
GOOD = {"passed": True, "verdict": "approve", "reasons": ["a", "b"], "note": "fine"}


def handover_flow(client: TestClient, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """trigger -> agent "Ask" (with the Hand Over Tool "Review") -> Edit Fields "Use" -> Build Context "Pack" -> Output."""
    agent = make_agent(client)
    action = post(client, "/api/actions", name="Answer")
    trigger, output = kind_of(client, action, "trigger"), kind_of(client, action, "output")
    for edge in client.get(graph_url(action)).json()["edges"]:
        client.delete(f"{graph_url(action)}/edges/{edge['id']}")
    ask = node(
        client,
        action,
        "agent",
        name="Ask",
        config={"agent_id": agent["id"], "inputs": "ticket = T-1"},
    )
    tool = node(
        client,
        action,
        "handover_tool",
        name="Review",
        config={"tool_name": "report", "fields": FIELDS if fields is None else fields},
        x=100,
        y=300,
    )
    use = node(
        client,
        action,
        "set",
        name="Use",
        config={"fields": "line = ${(Review).data.verdict}: ${(Review).data.passed}"},
    )
    pack = node(
        client,
        action,
        "context",
        name="Pack",
        config={"sources": [{"source": "handovers", "names": []}]},
    )
    connect(client, action, trigger, "out", ask, "in")
    connect(client, action, tool, "tool", ask, "tools")
    connect(client, action, ask, "pass", use, "in")
    connect(client, action, use, "pass", pack, "in")
    connect(client, action, pack, "pass", output, "pass")
    pipeline = build_pipeline(client, stages=1)
    link(client, pipeline, pipeline["stages"][0][1], action)
    return pipeline


def run(client: TestClient, pipeline: dict[str, Any], status: str = "done") -> dict[str, Any]:
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    done = wait_for_run(client, task, status, timeout=30)
    detail = client.get(f"/api/tasks/{task['id']}/executions/{done['execution_id']}").json()
    steps = {s["kind"]: s for s in done["node_results"]}
    step = steps["agent"]
    read = client.get(
        f"/api/tasks/{task['id']}/executions/{done['execution_id']}/steps/{step['id']}"
    ).json()
    return {"context": detail["context"], "step": step, "read": read, "steps": steps}


def setup(
    api: TestClient, llm: FakeLlm, fields: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    make_provider(api, llm)
    return handover_flow(api, fields)


def test_an_invalid_document_goes_back_with_every_problem_and_the_model_may_call_again(
    api: TestClient, llm: FakeLlm
) -> None:
    pipeline = setup(api, llm)
    llm.script = [
        (200, tool_answer(("c1", "report", {"passed": "yes", "extra": 1}))),
        (200, tool_answer(("c2", "report", GOOD))),
        (200, completion("Handed over.")),
    ]
    found = run(api, pipeline)
    first, second, third = llm.completions()
    assert [t["function"]["name"] for t in first["json"]["tools"]] == ["report"]
    schema = first["json"]["tools"][0]["function"]["parameters"]
    assert schema["required"] == ["passed", "verdict"] and schema["additionalProperties"] is False
    assert schema["properties"]["verdict"]["enum"] == ["approve", "reject"]
    refusal = second["json"]["messages"][-1]
    assert refusal["content"] == (
        "Error: the document was not accepted: unknown field 'extra' (the fields are: passed, verdict, reasons, note); "
        "'passed' must be true or false; 'verdict' is required. Call the tool again with a corrected document."
    )
    assert third["json"]["messages"][-1]["content"] == "handed over"
    refused, accepted = (
        found["read"]["detail"]["turns"][0]["tool_calls"][0],
        found["read"]["detail"]["turns"][1]["tool_calls"][0],
    )
    assert (refused["error"], accepted["error"], accepted["result"]) == (True, False, "handed over")
    assert refused["node_name"] == accepted["node_name"] == "Review"  # the step keeps every call


def test_the_accepted_document_is_the_result_of_the_tool_node_in_the_run_context(
    api: TestClient, llm: FakeLlm
) -> None:
    pipeline = setup(api, llm)
    llm.script = [
        (200, tool_answer(("c1", "report", {"passed": "yes"}))),
        (200, tool_answer(("c2", "report", GOOD))),
        (200, completion("Handed over.")),
    ]
    found = run(api, pipeline)
    entry = found["context"]["nodes"]["Review"]
    assert (entry["kind"], entry["success"], entry["outcome"], entry["reason"]) == (
        "handover_tool",
        True,
        "pass",
        None,
    )
    assert entry["data"] == GOOD
    assert json.loads(entry["output"]) == GOOD
    assert entry["attempts"] == 2  # a refused call and the one that passed
    assert found["step"]["data"]["handovers"] == {"Review": GOOD}


def test_a_later_node_reads_the_document_as_data_of_the_tool_node(
    api: TestClient, llm: FakeLlm
) -> None:
    pipeline = setup(api, llm)
    llm.script = [(200, tool_answer(("c1", "report", GOOD))), (200, completion("Done."))]
    found = run(api, pipeline)
    assert found["context"]["vars"] == {
        "line": "approve: true"
    }  # ${(Review).data.verdict}: ${(Review).data.passed}


def test_the_documents_are_a_source_of_the_package_a_later_agent_gets(
    api: TestClient, llm: FakeLlm
) -> None:
    pipeline = setup(api, llm)
    llm.script = [(200, tool_answer(("c1", "report", GOOD))), (200, completion("Done."))]
    found = run(api, pipeline)
    pack = found["context"]["nodes"]["Pack"]
    assert "## Handover documents" in pack["output"]
    assert "### Review\npassed: true\nverdict: approve\nreasons: a, b\nnote: fine" in pack["output"]
    (included,) = pack["data"]["included"]
    assert (included["source"], included["label"], included["items"], included["available"]) == (
        "handovers",
        "Handover documents",
        1,
        1,
    )


def test_the_last_document_that_passes_counts_and_every_call_is_counted(
    api: TestClient, llm: FakeLlm
) -> None:
    pipeline = setup(api, llm)
    again = {**GOOD, "verdict": "reject", "passed": False}
    llm.script = [
        (200, tool_answer(("c1", "report", GOOD))),
        (200, tool_answer(("c2", "report", again))),
        (200, completion("Changed my mind.")),
    ]
    found = run(api, pipeline)
    entry = found["context"]["nodes"]["Review"]
    assert entry["data"] == again and entry["attempts"] == 2
    assert found["context"]["vars"] == {"line": "reject: false"}


def test_a_text_that_looks_like_a_reference_stays_text_in_every_place_it_goes(
    api: TestClient, llm: FakeLlm
) -> None:
    pipeline = setup(api, llm)
    hostile = "${secret:GITHUB_TOKEN} ${var.line} ${(Review).data.passed}"
    llm.script = [
        (200, tool_answer(("c1", "report", {**GOOD, "note": hostile}))),
        (200, completion("Done.")),
    ]
    found = run(api, pipeline)
    assert found["context"]["nodes"]["Review"]["data"]["note"] == hostile
    assert (
        f"note: {hostile}" in found["context"]["nodes"]["Pack"]["output"]
    )  # pasted, never evaluated


def test_nothing_is_stored_when_no_document_ever_passed(api: TestClient, llm: FakeLlm) -> None:
    pipeline = setup(api, llm)
    llm.script = [
        (200, tool_answer(("c1", "report", {"passed": "no"}))),
        (200, completion("I give up.")),
    ]
    found = run(api, pipeline, "failed")  # "Use" cannot read a document that was never handed over
    assert "Review" not in found["context"]["nodes"]
    assert "handovers" not in (found["step"]["data"] or {})


def test_a_tool_without_fields_fails_the_node_before_the_model_is_asked(
    api: TestClient, llm: FakeLlm
) -> None:
    pipeline = setup(api, llm, fields=[])
    found = run(api, pipeline, "failed")
    assert found["step"]["reason"] == (
        "Tool Review: No fields are defined: the model would have nothing to hand over"
    )
    assert llm.completions() == []


def test_the_fields_are_checked_when_the_setting_is_saved(api: TestClient) -> None:
    action = post(api, "/api/actions", name="Fields")
    made = node(api, action, "handover_tool")
    url = f"{graph_url(action)}/nodes/{made['id']}"
    refused = api.patch(url, json={"config": {"fields": [{"name": "Bad name"}]}})
    assert (
        refused.status_code == 422 and "the name is lowercase letters, digits and _" in refused.text
    )
    refused = api.patch(url, json={"config": {"fields": [{"name": "a"}, {"name": "a"}]}})
    assert refused.status_code == 422 and "The field 'a' is there twice" in refused.text
    refused = api.patch(url, json={"config": {"max_bytes": 10}})
    assert refused.status_code == 422
    ok = api.patch(
        url, json={"config": {"fields": [{"name": "answer", "type": "text", "required": True}]}}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["config"]["fields"] == [
        {"name": "answer", "type": "text", "required": True, "description": ""}
    ]  # stored with every option present


def test_the_node_is_an_agent_tool_with_a_result_of_its_own(api: TestClient) -> None:
    described = {t["kind"]: t for t in api.get("/api/node-types").json()}["handover_tool"]
    assert described["tool"] is True and described["produces_result"] is True
    assert [s["key"] for s in described["settings"]] == [
        "tool_name",
        "description",
        "fields",
        "max_bytes",
    ]
    fields = next(s for s in described["settings"] if s["key"] == "fields")
    assert fields["type"] == "fields" and fields["max_fields"] == 30
    assert fields["field_types"] == ["text", "number", "boolean", "choice", "list"]
