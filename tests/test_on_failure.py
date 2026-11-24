"""The three answers to a failure, for the nodes of an action and for an action itself (ADR-061).

``on_failure`` is ``fail`` (the default: the failure ends the action, and the action's own setting decides what happens
to the run), ``continue`` (the failure is recorded and the flow goes on through On Pass) or ``error_output`` (the flow goes
on through the error output, which exists only with this value).
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.helpers import build_definition as _failing_definition
from tests.helpers import build_pipeline as _pipeline
from tests.helpers import graph_url as _url
from tests.helpers import kind_of
from tests.helpers import make_task as _make_task
from tests.helpers import node as _node
from tests.helpers import post as _post
from tests.helpers import wait_for_run as _wait


def _raw_connect(
    client: TestClient,
    graph: dict[str, Any],
    a: dict[str, Any],
    ap: str,
    b: dict[str, Any],
    bp: str,
) -> Any:
    """POST an edge as it is (the shared ``connect`` helper switches the error output on first)."""
    return client.post(
        f"{_url(graph)}/edges",
        json={"source_id": a["id"], "source_port": ap, "target_id": b["id"], "target_port": bp},
    )


def _set(client: TestClient, graph: dict[str, Any], node: dict[str, Any], value: str) -> Any:
    return client.patch(f"{_url(graph)}/nodes/{node['id']}", json={"config": {"on_failure": value}})


def _code_definition(client: TestClient, mode: str | None, code: str = "exit 1") -> dict[str, Any]:
    """trigger -> code -> Output (On Pass only; On Fail off), the code node set to ``mode``."""
    action = _post(client, "/api/actions", name="Do code")
    trigger, output = kind_of(client, action, "trigger"), kind_of(client, action, "output")
    config: dict[str, Any] = {"code": code}
    if mode is not None:
        config["on_failure"] = mode
    step = _node(client, action, "code", config=config)
    # the default trigger -> output edge is replaced by connecting the trigger to the code node
    _raw_connect(client, action, trigger, "out", step, "in").raise_for_status()
    _raw_connect(client, action, step, "pass", output, "pass").raise_for_status()
    action["node"], action["output"] = step, output
    return action


def _run(client: TestClient, pipeline: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    shell = pipeline["stages"][0][1]
    assert (
        client.patch(
            f"{_url(pipeline)}/nodes/{shell['id']}", json={"definition_id": action["id"]}
        ).status_code
        == 200
    )
    task = _make_task(client)
    _post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    task["steps"] = lambda: client.get(f"/api/runs/{task['id']}/results").json()
    task["shell"] = shell
    return task


def test_the_setting_has_three_values_and_the_default_stops_the_run(client: TestClient) -> None:
    description = {k["kind"]: k for k in client.get("/api/node-types").json()}
    for kind in ("code", "http", "github", "postgres", "artifact", "agent", "set", "action"):
        setting = next(s for s in description[kind]["settings"] if s["key"] == "on_failure")
        assert setting["options"] == ["fail", "continue", "error_output"], kind
        assert setting["default"] == "fail"
        assert set(setting["option_labels"]) == {"fail", "continue", "error_output"}
    assert (
        next(s for s in description["action"]["settings"] if s["key"] == "on_failure")["label"]
        == "If the action fails"
    )


def test_the_error_output_is_shown_only_with_the_third_value(client: TestClient) -> None:
    description = {k["kind"]: k for k in client.get("/api/node-types").json()}
    for kind, port in (("code", "fail"), ("http", "fail"), ("action", "error")):
        output = next(p for p in description[kind]["outputs"] if p["name"] == port)
        assert output["visible_when"] == {"setting": "on_failure", "equals": "error_output"}
    # the pass outputs are always there
    assert "visible_when" not in next(
        p for p in description["code"]["outputs"] if p["name"] == "pass"
    )


def test_a_connection_at_a_hidden_error_output_is_refused(client: TestClient) -> None:
    action = _code_definition(client, None)
    response = _raw_connect(client, action, action["node"], "fail", action["output"], "pass")
    assert response.status_code == 422
    assert "error output" in response.json()["detail"]
    assert _set(client, action, action["node"], "error_output").status_code == 200
    assert (
        _raw_connect(client, action, action["node"], "fail", action["output"], "pass").status_code
        == 201
    )


def test_the_error_output_cannot_be_hidden_while_it_is_connected(client: TestClient) -> None:
    action = _code_definition(client, "error_output")
    _raw_connect(
        client, action, action["node"], "fail", action["output"], "pass"
    ).raise_for_status()
    for value in ("fail", "continue"):
        refused = _set(client, action, action["node"], value)
        assert refused.status_code == 422, value
        assert "remove that connection first" in refused.json()["detail"]
    node = next(
        n for n in client.get(_url(action)).json()["nodes"] if n["id"] == action["node"]["id"]
    )
    assert node["config"]["on_failure"] == "error_output"  # nothing changed
    edge = next(e for e in client.get(_url(action)).json()["edges"] if e["source_port"] == "fail")
    assert client.delete(f"{_url(action)}/edges/{edge['id']}").status_code == 204
    assert _set(client, action, action["node"], "continue").status_code == 200


def test_an_unknown_value_is_refused(client: TestClient) -> None:
    action = _code_definition(client, None)
    refused = _set(client, action, action["node"], "ignore")
    assert refused.status_code == 422
    assert "on_failure" in refused.json()["detail"]


# ── a failing node ──────────────────────────────────────────────────────────


def test_stop_ends_the_action_and_the_run_fails(client: TestClient) -> None:
    pipeline = _pipeline(client, stages=1)
    task = _run(client, pipeline, _code_definition(client, None))
    run = _wait(client, task, "failed")
    assert '"Do code" failed' in run["note"]
    steps = task["steps"]()
    code = next(s for s in steps if s["kind"] == "code")
    assert code["outcome"] == "fail"
    assert code["data"]["error"]["mode"] == "fail"  # the failure is data even when the run stops
    assert not any(s["kind"] == "output" for s in steps)


def test_continue_goes_on_through_on_pass_and_keeps_the_error_as_data(
    client: TestClient,
) -> None:
    pipeline = _pipeline(client, stages=1)
    task = _run(client, pipeline, _code_definition(client, "continue", code="echo partial; exit 3"))
    _wait(client, task, "done")
    steps = task["steps"]()
    code = next(s for s in steps if s["kind"] == "code")
    assert (code["outcome"], code["port"]) == ("fail", "pass")
    assert code["output"].strip() == "partial"  # what the node produced stays
    assert code["data"]["error"]["mode"] == "continue"
    assert code["data"]["error"]["message"]
    assert "continued through On Pass" in code["reason"]
    assert [s["kind"] for s in steps][-1] == "output"


def test_the_error_output_leads_to_the_fallback_and_without_one_the_action_fails(
    client: TestClient,
) -> None:
    pipeline = _pipeline(client, stages=1)
    action = _code_definition(client, "error_output")
    fallback = _node(client, action, "code", config={"code": "echo fallback"})
    _raw_connect(client, action, action["node"], "fail", fallback, "in").raise_for_status()
    _raw_connect(client, action, fallback, "pass", action["output"], "pass").raise_for_status()
    task = _run(client, pipeline, action)
    _wait(client, task, "done")
    steps = task["steps"]()
    assert [(s["kind"], s["port"]) for s in steps if s["kind"] == "code"] == [
        ("code", "fail"),
        ("code", "pass"),
    ]
    error = next(s for s in steps if s["kind"] == "code")["data"]["error"]
    assert error["mode"] == "error_output"

    bare = _code_definition(
        client, "error_output"
    )  # the output is on but nothing is connected there
    other = _pipeline(client, stages=1, name="Other")
    task = _run(client, other, bare)
    run = _wait(client, task, "failed")
    assert '"Do code" failed' in run["note"]


# ── a failing action ────────────────────────────────────────────────────────


def _always_failing(client: TestClient) -> dict[str, Any]:
    return _failing_definition(client, "Breaks", output="fail", fail_enabled=True)


def test_an_action_that_fails_stops_the_run_by_default(client: TestClient) -> None:
    pipeline = _pipeline(client, stages=1)
    task = _run(client, pipeline, _always_failing(client))
    run = _wait(client, task, "failed")
    assert '"Breaks" failed' in run["note"]


def test_an_action_set_to_continue_goes_on_through_on_pass(client: TestClient) -> None:
    pipeline = _pipeline(client, stages=1)
    shell = pipeline["stages"][0][1]
    assert _set(client, pipeline, shell, "continue").status_code == 200
    task = _run(client, pipeline, _always_failing(client))
    _wait(client, task, "done")


def test_an_action_set_to_the_error_output_follows_it(client: TestClient) -> None:
    pipeline = _pipeline(client, stages=1)
    stage, shell = pipeline["stages"][0]
    refused = _raw_connect(client, pipeline, shell, "error", stage, "end")
    assert refused.status_code == 422 and "error output" in refused.json()["detail"]
    assert _set(client, pipeline, shell, "error_output").status_code == 200
    _raw_connect(client, pipeline, shell, "error", stage, "end").raise_for_status()
    task = _run(client, pipeline, _always_failing(client))
    _wait(client, task, "done")
    # and it cannot be hidden while it is connected
    refused = _set(client, pipeline, shell, "continue")
    assert refused.status_code == 422 and "remove that connection first" in refused.json()["detail"]


def test_an_action_set_to_the_error_output_with_nothing_connected_fails_the_run(
    client: TestClient,
) -> None:
    pipeline = _pipeline(client, stages=1)
    shell = pipeline["stages"][0][1]
    assert _set(client, pipeline, shell, "error_output").status_code == 200
    task = _run(client, pipeline, _always_failing(client))
    run = _wait(client, task, "failed")
    assert '"Breaks" failed' in run["note"]


def test_the_error_output_of_an_action_no_longer_depends_on_its_definition(
    client: TestClient,
) -> None:
    """Before, On Error needed an Output with On Fail in the definition; now the action's own setting decides."""
    pipeline = _pipeline(client, stages=1)
    stage, shell = pipeline["stages"][0]
    plain = _failing_definition(client, "Plain")  # an Output without On Fail
    assert (
        client.patch(
            f"{_url(pipeline)}/nodes/{shell['id']}", json={"definition_id": plain["id"]}
        ).status_code
        == 200
    )
    assert _set(client, pipeline, shell, "error_output").status_code == 200
    assert _raw_connect(client, pipeline, shell, "error", stage, "end").status_code == 201
