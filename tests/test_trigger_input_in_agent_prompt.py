"""The inputs the Trigger of a graph declares reach the prompt of an agent node in that graph (ADR-089 addendum 1).

The owner typed a value for the Trigger input ``mield`` in the Dry run form of an action and wrote ``${input.mield}`` in the User prompt of the
node's agent: the run stopped before the model ("is not a declared input") because a prompt reads the inputs of its agent only. The agent's own
inputs still come first; a name that only the Trigger declares is read from the inputs of the run."""

from __future__ import annotations

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
from tests.test_agent_tools_run import api, llm

__all__ = ["api", "llm"]  # the fixtures of the agent tool tests, used by name

TEXT = "let the party start it"


def _action(client: TestClient, user_prompt: str, *, agent_inputs: bool = True) -> dict[str, Any]:
    """An action whose Trigger declares ``mield`` and whose agent node overrides the User prompt (the owner's case)."""
    agent = make_agent(client)
    action = post(client, "/api/actions", name="Greeter")
    trigger, output = kind_of(client, action, "trigger"), kind_of(client, action, "output")
    client.patch(
        f"{graph_url(action)}/nodes/{trigger['id']}",
        json={"config": {"inputs": [{"name": "mield", "type": "text", "required": True}]}},
    ).raise_for_status()
    for edge in client.get(graph_url(action)).json()["edges"]:
        client.delete(f"{graph_url(action)}/edges/{edge['id']}")
    ask = node(
        client,
        action,
        "agent",
        name="Ask",
        config={
            "agent_id": agent["id"],
            "inputs": "ticket = T-1" if agent_inputs else "",
            "user_prompt": user_prompt,
        },
    )
    connect(client, action, trigger, "out", ask, "in")
    connect(client, action, ask, "pass", output, "pass")
    action["ask"] = ask
    return action


def _dry_run(client: TestClient, action: dict[str, Any], **body: Any) -> dict[str, Any]:
    response = client.post(f"/api/graphs/{action['id']}/dry-run", json=body)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def test_a_dry_run_hands_the_typed_trigger_input_to_the_prompt_of_the_agent_node(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    action = _action(api, "Say: ${input.mield} (ticket ${input.ticket})")
    llm.script = [(200, completion("done"))]
    started = _dry_run(api, action, inputs={"mield": TEXT})
    run = wait_for_run(api, {"id": started["task_id"]}, "done", timeout=30)
    (request,) = llm.completions()
    sent = [m["content"] for m in request["json"]["messages"] if m["role"] == "user"]
    assert sent == [f"Say: {TEXT} (ticket T-1)"], (
        "the typed value and the agent's own input are both in the prompt"
    )
    assert [s["kind"] for s in run["node_results"]] == ["trigger", "agent", "output"]


def test_an_input_of_the_agent_with_the_same_name_wins_over_the_trigger_input(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    action = _action(api, "Ticket: ${input.ticket}")
    trigger = kind_of(api, action, "trigger")
    api.patch(
        f"{graph_url(action)}/nodes/{trigger['id']}",
        json={"config": {"inputs": [{"name": "ticket", "type": "text", "required": True}]}},
    ).raise_for_status()
    llm.script = [(200, completion("done"))]
    started = _dry_run(api, action, inputs={"ticket": "from the form"})
    wait_for_run(api, {"id": started["task_id"]}, "done", timeout=30)
    (request,) = llm.completions()
    sent = [m["content"] for m in request["json"]["messages"] if m["role"] == "user"]
    assert sent == ["Ticket: T-1"], (
        "the agent's own input, mapped in the node, is not replaced by the Trigger's"
    )


def test_a_name_nobody_declares_still_stops_the_node_before_the_model(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    action = _action(api, "Say: ${input.nothing}")
    started = _dry_run(api, action, inputs={"mield": TEXT})
    run = wait_for_run(api, {"id": started["task_id"]}, "failed", timeout=30)
    agent = next(s for s in run["node_results"] if s["kind"] == "agent")
    assert "${input.nothing} is not a declared input" in str(agent["reason"])
    assert llm.completions() == [], "nothing was sent to the model"


def test_a_real_run_through_a_pipeline_hands_the_input_mapped_at_the_placement_to_the_prompt(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    action = _action(api, "Say: ${input.mield}")
    pipeline = build_pipeline(api, stages=1)
    placed = pipeline["stages"][0][1]
    link(api, pipeline, placed, action)
    api.patch(
        f"{graph_url(pipeline)}/nodes/{placed['id']}",
        json={"config": {"input_values": {"mield": "${card.title}"}}},
    ).raise_for_status()
    llm.script = [(200, completion("done"))]
    task = make_task(api, title="Hello from the card")
    post(api, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(api, task, "done", timeout=30)
    (request,) = llm.completions()
    sent = [m["content"] for m in request["json"]["messages"] if m["role"] == "user"]
    assert sent == ["Say: Hello from the card"]


def test_the_node_check_knows_the_trigger_inputs_and_still_names_a_wrong_one(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    action = _action(api, "Say: ${input.mield}")
    ask = action["ask"]
    read = api.get(f"{graph_url(action)}/nodes/{ask['id']}").json()
    # the check runs when the node is saved: save it again with the same prompt
    saved = api.patch(
        f"{graph_url(action)}/nodes/{ask['id']}",
        json={"config": {"user_prompt": "Say: ${input.mield}"}},
    )
    assert saved.status_code == 200, saved.text
    assert not [w for w in saved.json().get("warnings", []) if "not a declared input" in w], (
        read,
        saved.json(),
    )
    wrong = api.patch(
        f"{graph_url(action)}/nodes/{ask['id']}",
        json={"config": {"user_prompt": "Say: ${input.nothing}"}},
    )
    warnings = [w for w in wrong.json().get("warnings", []) if "not a declared input" in w]
    assert len(warnings) == 1
    assert "${input.nothing}" in warnings[0]
    assert "the Trigger of this graph declares: mield" in warnings[0]
