"""The Edit Fields node: variables of the run set from text and references, without code."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.engine.context import NodeIndex, RunContext, RunView
from openartifact.engine.fields import FieldsError, parse_fields, run_set
from openartifact.engine.results import NodeResult
from openartifact.graph.node_types import SettingError, node_type
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


def _view(**variables: Any) -> RunView:
    context = RunContext({"vars": variables, "card": {"tier": "gold"}})
    context.record(
        {"name": "Fetch", "kind": "http"},
        NodeResult("pass", output="Login broken", data={"n": 3}),
        "pass",
    )
    graph = {"name": "A", "nodes": [{"id": "f", "kind": "http", "name": "Fetch"}]}
    return RunView(context, NodeIndex.of_graphs([graph]))


# ── the fields text ──────────────────────────────────────────────────


def test_fields_are_name_equals_value_per_line() -> None:
    assert parse_fields("a = 1\n\n  var.b=x = y \nc =") == {"a": "1", "b": "x = y", "c": ""}
    assert parse_fields("") == {}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("a", "Line 1 is not 'name = value'"),
        ("ok = 1\nBad = 2", "Line 2: 'Bad' is not a variable name"),
        ("a = 1\na = 2", "Field 'a' is set twice"),
        ("a = ${secret:KEY}", "cannot be a field"),
        ("\n".join(f"f{n} = 1" for n in range(101)), "At most 100 fields"),
    ],
)
def test_a_wrong_fields_text_says_what_is_wrong(text: str, message: str) -> None:
    with pytest.raises(FieldsError, match=message):
        parse_fields(text)
    with pytest.raises(SettingError, match=message):  # the same rule when the node is saved
        node_type("set").merge_config(None, {"fields": text})


# ── running ──────────────────────────────────────────────────────────


def test_values_are_filled_from_the_run_and_become_variables() -> None:
    fields = (
        "summary = ${node.Fetch.output} (${card.tier})\ncount = ${node.Fetch.data.n}\nlabel = plain"
    )
    result = run_set({"fields": fields}, _view())
    assert result.outcome == "pass"
    assert result.variables == {"summary": "Login broken (gold)", "count": "3", "label": "plain"}
    assert result.data == {"fields": ["summary", "count", "label"]}
    assert result.output == '{"summary":"Login broken (gold)","count":"3","label":"plain"}'


def test_detect_stores_json_values_as_what_they_are() -> None:
    fields = "\n".join(
        [
            "n = 3",
            "f = -1.5e3",
            "yes = true",
            "none = null",
            "items = [1, 2]",
            'obj = {"a": {"b": 1}}',
            "text = hello",
            'quoted = "x"',
            "data = ${node.Fetch.data}",
            "almost = 3 apples",
        ]
    )
    result = run_set({"fields": fields, "value_types": "detect"}, _view())
    assert result.variables == {
        "n": 3,
        "f": -1500.0,
        "yes": True,
        "none": None,
        "items": [1, 2],
        "obj": {"a": {"b": 1}},
        "text": "hello",
        "quoted": '"x"',  # a JSON string stays as written: detect never changes text into other text
        "data": {"n": 3},
        "almost": "3 apples",
    }
    as_text = run_set({"fields": "n = 3", "value_types": "text"}, _view())
    assert as_text.variables == {"n": "3"}


@pytest.mark.parametrize(
    ("config", "reason"),
    [
        ({"fields": ""}, "No field is set"),
        (
            {"fields": "a = ${var.missing}"},
            "Field 'a': ${var.missing}: variable 'missing' is not set",
        ),
        (
            {"fields": "a = ${node.Ghost.output}"},
            "Field 'a': ${node.Ghost.output}: no node is named",
        ),
        ({"fields": "broken"}, "Line 1 is not 'name = value'"),
        (
            {"fields": "deep = [[[[1]]]]", "value_types": "detect"},
            "Invalid fields: variable 'deep':",
        ),
    ],
)
def test_what_cannot_be_set_fails_the_node_and_sets_nothing(
    config: dict[str, Any], reason: str
) -> None:
    result = run_set(config, _view())
    assert result.outcome == "fail" and str(result.reason).startswith(reason)
    assert result.variables is None


def test_a_secret_that_got_into_the_config_is_never_replaced() -> None:
    result = run_set({"fields": "a = ${secret:KEY}"}, _view())
    assert result.outcome == "fail" and "cannot be a field" in str(result.reason)


# ── in a run ─────────────────────────────────────────────────────────


def test_an_edit_fields_node_sets_variables_that_later_nodes_read(client: TestClient) -> None:
    action = post(client, "/api/actions", name="Prepare")
    trigger, output = kind_of(client, action, "trigger"), kind_of(client, action, "output")
    for edge in client.get(graph_url(action)).json()["edges"]:
        client.delete(f"{graph_url(action)}/edges/{edge['id']}")
    first = node(
        client,
        action,
        "set",
        name="Set",
        config={"fields": "priority = high\nscore = 7", "value_types": "detect"},
    )
    second = node(
        client, action, "set", name="Use", config={"fields": "line = ${var.priority}/${var.score}"}
    )
    decide = node(
        client,
        action,
        "switch",
        name="Decide",
        config={"value": "${var.score}", "case_1": "5", "case_operator_1": "greater than"},
    )
    connect(client, action, trigger, "out", first, "in")
    connect(client, action, first, "pass", second, "in")
    connect(client, action, second, "pass", decide, "in")
    connect(client, action, decide, "case_1", output, "pass")
    pipeline = build_pipeline(client, stages=1)
    link(client, pipeline, pipeline["stages"][0][1], action)
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = wait_for_run(client, task, "done")
    steps = [s for s in run["node_results"] if s["kind"] in ("set", "switch")]
    assert [(s["node_name"], s["outcome"], s["port"]) for s in steps] == [
        ("Set", "pass", "pass"),
        ("Use", "pass", "pass"),
        ("Decide", "pass", "case_1"),
    ]
    context = client.get(f"/api/tasks/{task['id']}/executions/{run['execution_id']}/context").json()
    assert context["vars"] == {"priority": "high", "score": 7, "line": "high/7"}


def test_the_node_is_described_and_warns_about_unknown_references(client: TestClient) -> None:
    described = {t["kind"]: t for t in client.get("/api/node-types").json()}["set"]
    assert (described["label"], described["scopes"], described["addable"]) == (
        "Edit Fields",
        ["action"],
        True,
    )
    assert [p["name"] for p in described["outputs"]] == ["pass", "fail"]
    settings = {s["key"]: s for s in described["settings"]}
    assert (
        settings["value_types"]["options"] == ["text", "detect"]
        and settings["value_types"]["default"] == "text"
    )
    assert settings["fields"]["references"] == "context"
    action = post(client, "/api/actions", name="Hints")
    made = node(client, action, "set", config={"fields": "a = ${node.Nobody.output}"})
    assert made["warnings"] == ['${node.Nobody.output}: no node is named "Nobody"']
    refused = client.patch(
        f"{graph_url(action)}/nodes/{made['id']}", json={"config": {"fields": "a = ${secret:K}"}}
    )
    assert refused.status_code == 422
