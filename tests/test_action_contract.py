"""Inputs and outputs of actions (ADR-083): what an action takes and hands back, by the node that runs it.

A definition declares its inputs on its Trigger and its outputs on its Output; the action node in a pipeline maps the inputs and later
nodes read the outputs by the id of that node (ADR-082), so one definition placed three times gives three independent results.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.graph.node_types import SettingError, node_type
from tests.helpers import (
    connect,
    graph_url,
    kind_of,
    make_task,
    node,
    post,
    run_of,
    wait_for_run,
)


@pytest.fixture
def ctx_client(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"http_allow_private_networks": True})
    with TestClient(_create_app(settings)) as client:
        yield client


def _declare(
    client: TestClient,
    definition: dict[str, Any],
    inputs: list[dict[str, Any]] | None,
    outputs: list[dict[str, Any]] | None,
) -> None:
    for kind, key, value in (("trigger", "inputs", inputs), ("output", "outputs", outputs)):
        if value is None:
            continue
        found = kind_of(client, definition, kind)
        response = client.patch(
            f"{graph_url(definition)}/nodes/{found['id']}", json={"config": {key: value}}
        )
        assert response.status_code == 200, response.text


def _greeting_action(
    client: TestClient,
    inputs: list[dict[str, Any]] | None = None,
    outputs: list[dict[str, Any]] | None = None,
    fields: str = "greeting = Hello ${input.who} x${input.times}",
) -> dict[str, Any]:
    """trigger -> Edit Fields -> output, with the inputs and outputs declared."""
    action = post(client, "/api/actions", name="Greet")
    trigger, output = kind_of(client, action, "trigger"), kind_of(client, action, "output")
    for edge in client.get(graph_url(action)).json()["edges"]:
        client.delete(f"{graph_url(action)}/edges/{edge['id']}")
    step = node(client, action, "set", name="Say", config={"fields": fields})
    connect(client, action, trigger, "out", step, "in")
    connect(client, action, step, "pass", output, "pass")
    _declare(client, action, inputs, outputs)
    return action


INPUTS = [
    {"name": "who", "type": "text", "required": True},
    {"name": "times", "type": "number", "required": False, "default": "2"},
]
OUTPUTS = [
    {"name": "greeting", "type": "text", "value": "${var.greeting}"},
    {"name": "count", "type": "number", "value": "${input.times}"},
]


def _stage_with(
    client: TestClient, definition: dict[str, Any], mappings: list[dict[str, str] | str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A pipeline with one stage that places ``definition`` once per entry of ``mappings`` (a dict of input values, or a text for
    the input ``who`` in which ``{0}``, ``{1}`` stand for ``node:<id>`` of the placements before it), in a row."""
    pipeline = post(client, "/api/pipelines", name="Flow")
    trigger, complete = kind_of(client, pipeline, "trigger"), kind_of(client, pipeline, "complete")
    stage = node(client, pipeline, "stage", name="Stage")
    connect(client, pipeline, trigger, "out", stage, "start")
    connect(client, pipeline, stage, "end", complete, "in")
    placed: list[dict[str, Any]] = []
    previous, port = stage, "start"
    for entry in mappings:
        action = node(client, pipeline, "action", stage_id=stage["id"], x=24, y=48)
        connect(client, pipeline, previous, port, action, "in")
        previous, port = action, "pass"
        values = (
            entry
            if isinstance(entry, dict)
            else {"who": entry.format(*[f"node:{p['id']}" for p in placed])}
        )
        response = client.patch(
            f"{graph_url(pipeline)}/nodes/{action['id']}",
            json={"definition_id": definition["id"], "config": {"input_values": values}},
        )
        assert response.status_code == 200, response.text
        placed.append(action)
    connect(client, pipeline, previous, port, stage, "end")
    return pipeline, placed


def _run(client: TestClient, pipeline: dict[str, Any], status: str = "done") -> dict[str, Any]:
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(client, task, status)
    execution_id = run_of(client, task)["execution_id"]
    detail = client.get(f"/api/tasks/{task['id']}/executions/{execution_id}").json()
    assert isinstance(detail, dict)
    return detail


def test_one_definition_placed_three_times_gives_three_independent_outputs(
    ctx_client: TestClient,
) -> None:
    definition = _greeting_action(ctx_client, INPUTS, OUTPUTS)
    pipeline, placed = _stage_with(
        ctx_client,
        definition,
        [
            {"who": "Ann"},
            {"who": "Bob", "times": "5"},
            "${{{0}.data.greeting}} / ${{{1}.data.greeting}}",  # the outputs of the first two, by their ids
        ],
    )
    nodes = _run(ctx_client, pipeline)["context"]["nodes"]
    by_id = {entry["id"]: entry for entry in nodes.values() if "id" in entry}
    assert by_id[placed[0]["id"]]["data"] == {"greeting": "Hello Ann x2", "count": 2}
    assert by_id[placed[1]["id"]]["data"] == {"greeting": "Hello Bob x5", "count": 5}
    assert by_id[placed[2]["id"]]["data"]["greeting"] == (
        "Hello Hello Ann x2 / Hello Bob x5 x2"  # inputs of the third: both earlier outputs
    )
    assert all(by_id[p["id"]]["success"] for p in placed)


def test_a_required_input_without_a_value_fails_the_run_and_names_the_input(
    ctx_client: TestClient,
) -> None:
    definition = _greeting_action(ctx_client, INPUTS, OUTPUTS)
    pipeline, _ = _stage_with(ctx_client, definition, [{"times": "3"}])
    run = _run(ctx_client, pipeline, "failed")
    assert run["note"] == "\"Greet\" failed: Greet: input 'who' is required and has no value"


def test_a_value_that_does_not_fit_the_type_fails_with_the_input_and_the_value(
    ctx_client: TestClient,
) -> None:
    definition = _greeting_action(ctx_client, INPUTS, OUTPUTS)
    pipeline, _ = _stage_with(ctx_client, definition, [{"who": "Ann", "times": "many"}])
    run = _run(ctx_client, pipeline, "failed")
    assert (
        run["note"]
        == "\"Greet\" failed: Greet: input 'times': 'times' must be a number, not 'many'"
    )


def test_the_default_of_an_input_applies_when_nothing_is_mapped(ctx_client: TestClient) -> None:
    definition = _greeting_action(ctx_client, INPUTS, OUTPUTS)
    pipeline, placed = _stage_with(ctx_client, definition, [{"who": "Ann"}])
    nodes = _run(ctx_client, pipeline)["context"]["nodes"]
    entry = next(e for e in nodes.values() if e.get("id") == placed[0]["id"])
    assert entry["data"] == {"greeting": "Hello Ann x2", "count": 2}


def test_an_unknown_input_reference_fails_the_node_and_lists_the_inputs(
    ctx_client: TestClient,
) -> None:
    definition = _greeting_action(ctx_client, INPUTS, OUTPUTS, fields="greeting = ${input.nobody}")
    pipeline, _ = _stage_with(ctx_client, definition, [{"who": "Ann"}])
    run = _run(ctx_client, pipeline, "failed")
    assert "there is no input 'nobody' here (the inputs are: who, times)" in str(run["note"])


def test_an_output_that_cannot_be_worked_out_fails_the_action_and_names_the_output(
    ctx_client: TestClient,
) -> None:
    broken = [{"name": "missing", "type": "text", "value": "${var.not_set}"}]
    definition = _greeting_action(ctx_client, INPUTS, broken)
    pipeline, _ = _stage_with(ctx_client, definition, [{"who": "Ann"}])
    run = _run(ctx_client, pipeline, "failed")
    assert "output 'missing': ${var.not_set}: variable 'not_set' is not set" in str(run["note"])


def test_a_definition_without_a_contract_runs_as_before_and_leaves_no_result_of_its_node(
    ctx_client: TestClient,
) -> None:
    definition = _greeting_action(ctx_client, None, None, fields="greeting = plain")
    pipeline, placed = _stage_with(ctx_client, definition, [{}])
    nodes = _run(ctx_client, pipeline)["context"]["nodes"]
    assert list(nodes) == ["Say"]  # only the node inside; the action node has no entry
    assert not any(e.get("id") == placed[0]["id"] for e in nodes.values())


def test_the_settings_of_the_contract_say_what_is_wrong() -> None:
    with pytest.raises(SettingError, match="Field 1 has no option 'type2'"):
        node_type("trigger").merge_config(None, {"inputs": [{"name": "a", "type2": "x"}]})
    with pytest.raises(SettingError, match="Field 'a': the value is a text of at most 2000"):
        node_type("output").merge_config(None, {"outputs": [{"name": "a", "value": "x" * 2001}]})
    with pytest.raises(SettingError, match="'input_values': 'beta!' is no input name"):
        node_type("action").merge_config(None, {"input_values": {"beta!": "x"}})
    with pytest.raises(SettingError, match="must be an object of input name: value"):
        node_type("action").merge_config(None, {"input_values": ["x"]})
    # a trigger takes a default, an output a value, and neither takes the other's extra
    assert node_type("trigger").merge_config(None, {"inputs": [{"name": "a", "default": "1"}]})
    with pytest.raises(SettingError, match="Field 1 has no option 'value'"):
        node_type("trigger").merge_config(None, {"inputs": [{"name": "a", "value": "1"}]})
