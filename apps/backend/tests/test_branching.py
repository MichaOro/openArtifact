"""The If and Switch nodes (ADR-034): comparison rules, ports, validation and runs through the engine."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.engine.branching import (
    SHOWN_CHARS,
    UnevaluableError,
    compare,
    evaluate_if,
    evaluate_switch,
)
from openartifact.engine.context import NodeIndex, RunContext, RunView
from openartifact.engine.executors import _note_variables
from openartifact.engine.results import NodeResult
from openartifact.graph.node_types import OPERATORS, UNARY_OPERATORS, node_type
from openartifact.models import NodeKind
from tests.helpers import (
    alembic_config,
    build_pipeline,
    connect,
    graph_url,
    kind_of,
    link,
    make_task,
    node,
    post,
    run_of,
    wait_for_run,
)


def _view(
    variables: dict[str, Any] | None = None, nodes: dict[str, NodeResult] | None = None
) -> RunView:
    context = RunContext()
    context.set_vars(variables or {})
    graph = {"name": "A", "nodes": []}
    for name, result in (nodes or {}).items():
        context.record({"name": name, "kind": "code"}, result, "pass")
        graph["nodes"].append({"id": name, "kind": "code", "name": name})  # type: ignore[attr-defined]
    return RunView(context, NodeIndex.of_graphs([graph]))


def _if(**config: Any) -> dict[str, Any]:
    return config


def _row(left: str, operator: str = "equals", right: str = "", n: int = 1) -> dict[str, Any]:
    return {f"left_{n}": left, f"operator_{n}": operator, f"right_{n}": right}


# ── comparison rules ─────────────────────────────────────────────────

TRUE_CASES = [
    ("a", "equals", "a"),
    ("1.0", "equals", "1"),  # both numbers: numeric
    ("1e2", "equals", "100"),
    (" a \n", "equals", "a"),  # white space around is ignored
    ("a", "not equals", "b"),
    ("abc", "contains", "b"),
    ("abc", "not contains", "x"),
    ("abc", "starts with", "ab"),
    ("abc", "ends with", "bc"),
    ("", "is empty", ""),
    ("  ", "is empty", ""),
    ("null", "is empty", ""),
    ("[]", "is empty", ""),
    ("{ }", "is empty", ""),
    ("0", "is not empty", ""),
    ("[1]", "is not empty", ""),
    ("nullable", "is not empty", ""),
    ("10", "greater than", "9"),  # numbers, not text: "10" > "9"
    ("-1.5", "less than", "+2"),
    ("3", "greater or equal", "3"),
    ("3", "less or equal", "3.0"),
    ("true", "is true", ""),
    ("false", "is false", ""),
]
FALSE_CASES = [
    ("a", "equals", "b"),
    ("1", "equals", "1.5"),
    ("a", "not equals", "a"),
    ("abc", "contains", "x"),
    ("abc", "not contains", "b"),
    ("abc", "starts with", "bc"),
    ("abc", "ends with", "ab"),
    ("x", "is empty", ""),
    ("", "is not empty", ""),
    ("9", "greater than", "10"),
    ("2", "less than", "2"),
    ("2", "greater or equal", "3"),
    ("4", "less or equal", "3"),
    ("false", "is true", ""),
    ("true", "is false", ""),
]
ELSE_CASES = [
    ("abc", "greater than", "1"),
    ("1", "less than", "abc"),
    ("", "greater or equal", "1"),
    ("1", "less or equal", ""),
    ("yes", "is true", ""),
    ("True", "is false", ""),
    ("1", "is true", ""),
]


def test_every_operator_is_in_the_matrix() -> None:
    covered = {o for _, o, _ in TRUE_CASES} | {o for _, o, _ in FALSE_CASES}
    assert covered == set(OPERATORS)
    assert set(OPERATORS) >= UNARY_OPERATORS


@pytest.mark.parametrize(("left", "operator", "right"), TRUE_CASES)
def test_operators_that_hold(left: str, operator: str, right: str) -> None:
    assert compare(left, operator, right) is True


@pytest.mark.parametrize(("left", "operator", "right"), FALSE_CASES)
def test_operators_that_do_not_hold(left: str, operator: str, right: str) -> None:
    assert compare(left, operator, right) is False


@pytest.mark.parametrize(("left", "operator", "right"), ELSE_CASES)
def test_numbers_and_booleans_are_parsed_strictly(left: str, operator: str, right: str) -> None:
    with pytest.raises(UnevaluableError):
        compare(left, operator, right)


def test_case_sensitivity_is_on_by_default_and_can_be_switched_off() -> None:
    assert compare("Gold", "equals", "gold") is False
    assert compare("Gold", "equals", "gold", case_sensitive=False) is True
    assert compare("Gold", "contains", "OL", case_sensitive=False) is True
    assert compare("Gold", "starts with", "go") is False


def test_text_that_looks_like_a_number_only_on_one_side_compares_as_text() -> None:
    assert compare("1", "equals", "one") is False
    assert compare("007", "equals", "7") is True  # both numbers


# ── the If node ──────────────────────────────────────────────────────


def test_if_yes_no_and_the_recorded_rows() -> None:
    view = _view({"priority": "high", "n": 7})
    result = evaluate_if(_if(**_row("${var.priority}", "equals", "high")), view)
    assert (result.outcome, result.port, result.output) == ("pass", "yes", "yes")
    assert result.data == {
        "condition": True,
        "rows": [{"left": "high", "operator": "equals", "right": "high", "result": True}],
    }
    no = evaluate_if(_if(**_row("${var.n}", "greater than", "10")), view)
    assert (no.outcome, no.port, no.data["condition"]) == ("pass", "no", False)  # type: ignore[index]


def test_combine_all_and_any_over_several_rows_and_unused_rows_are_ignored() -> None:
    view = _view({"a": "1"})
    rows = {
        **_row("${var.a}", "equals", "1"),
        **_row("${var.a}", "equals", "2", n=3),
    }  # row 2 unused
    assert evaluate_if(_if(combine="all", **rows), view).port == "no"
    assert evaluate_if(_if(combine="any", **rows), view).port == "yes"
    only = evaluate_if(_if(**_row("${var.a}", "equals", "1", n=5)), view)
    assert only.port == "yes" and len(only.data["rows"]) == 1  # type: ignore[index]


def test_a_reference_that_cannot_be_resolved_goes_to_else_and_names_itself() -> None:
    result = evaluate_if(_if(**_row("${var.missing}", "equals", "x")), _view())
    assert (result.outcome, result.port) == ("fail", "else")
    assert result.reason is not None and "${var.missing}" in result.reason
    assert "variable 'missing' is not set" in result.reason
    assert result.data["condition"] is None  # type: ignore[index]
    ghost = evaluate_if(_if(**_row("${node.Nobody.output}", "is empty")), _view())
    assert ghost.port == "else" and 'no node is named "Nobody"' in str(ghost.reason)
    malformed = evaluate_if(_if(**_row("${node.x}", "is empty")), _view())
    assert malformed.port == "else" and "malformed reference" in str(malformed.reason)


def test_a_right_side_the_operator_ignores_is_not_resolved() -> None:
    result = evaluate_if(
        _if(**_row("", "is empty", "${var.missing}") | _row("x", "is empty", n=2)), _view()
    )
    assert result.port == "no"  # row 1 is unused (empty left); row 2 is false


def test_types_that_cannot_be_compared_and_no_condition_at_all_go_to_else() -> None:
    result = evaluate_if(_if(**_row("abc", "greater than", "1")), _view())
    assert (result.port, result.outcome) == ("else", "fail")
    assert "Condition 1" in str(result.reason)
    empty = evaluate_if(_if(), _view())
    assert empty.port == "else" and empty.reason == "No condition is set"
    first = evaluate_if(
        _if(**_row("abc", "less than", "1") | _row("${var.q}", "is empty", n=2)), _view()
    )
    assert str(first.reason).startswith("Condition 1")  # the first problem is the reason


def test_node_references_and_the_json_of_data_are_resolved_as_text() -> None:
    view = _view(
        nodes={"Check": NodeResult("pass", output="42\n", data={"tier": "gold", "n": [1]})}
    )
    config = _if(
        **_row("${node.Check.output}", "equals", "42")
        | _row("${node.Check.data.tier}", "equals", "gold", n=2)
        | _row("${node.Check.data.n}", "equals", "[1]", n=3)
        | _row("${node.Check.outcome}", "equals", "pass", n=4)
    )
    result = evaluate_if(config, view)
    assert result.port == "yes" and len(result.data["rows"]) == 4  # type: ignore[index]


def test_recorded_values_are_cut_and_secrets_are_never_replaced() -> None:
    view = _view({"long": "x" * 500})
    result = evaluate_if(_if(**_row("${var.long}", "contains", "x")), view)
    assert result.data["rows"][0]["left"] == "x" * SHOWN_CHARS + "…"  # type: ignore[index]
    secret = evaluate_if(_if(**_row("${secret:API_KEY}", "contains", "API_KEY")), view)
    assert secret.port == "yes"  # still the literal text (a stored config cannot hold one anyway)


# ── the Switch node ──────────────────────────────────────────────────


def test_switch_takes_the_first_matching_case_or_else() -> None:
    config = {"value": "${var.tier}", "case_1": "silver", "case_2": "gold", "case_4": "gold"}
    gold = evaluate_switch(config, _view({"tier": "gold"}))
    assert (gold.outcome, gold.port, gold.data) == (
        "pass",
        "case_2",
        {"value": "gold", "matched": "case_2"},
    )
    none = evaluate_switch(config, _view({"tier": "bronze"}))
    assert (none.outcome, none.port, none.data) == (
        "pass",
        "else",
        {"value": "bronze", "matched": None},
    )
    assert evaluate_switch(config, _view({"tier": " silver\n"})).port == "case_1"
    assert evaluate_switch(config, _view({"tier": "GOLD"})).port == "else"
    assert (
        evaluate_switch({**config, "case_sensitive": False}, _view({"tier": "GOLD"})).port
        == "case_2"
    )


def test_an_empty_case_never_matches_and_an_unresolvable_value_is_an_error() -> None:
    assert evaluate_switch({"value": "${var.x}", "case_1": ""}, _view({"x": ""})).port == "else"
    broken = evaluate_switch({"value": "${var.x}", "case_1": "a"}, _view())
    assert (broken.outcome, broken.port, broken.data) == (
        "fail",
        "else",
        {"value": None, "matched": None},
    )
    assert "${var.x}" in str(broken.reason)


# ── registry, settings and connection rules ──────────────────────────


def test_the_registry_describes_the_branching_nodes(client: TestClient) -> None:
    described = {t["kind"]: t for t in client.get("/api/node-types").json()}
    kinds = list(described)
    assert (
        kinds.index("if") > kinds.index("http") and kinds.index("switch") == kinds.index("if") + 1
    )
    for kind in ("if", "switch"):
        assert (
            described[kind]["scopes"],
            described[kind]["addable"],
            described[kind]["chain"],
        ) == (
            ["action"],
            True,
            True,
        )
        assert [p["name"] for p in described[kind]["inputs"]] == ["in"]
        assert not any(s["key"] == "on_failure" for s in described[kind]["settings"])
    assert [(p["name"], p["label"]) for p in described["if"]["outputs"]] == [
        ("yes", "Yes"),
        ("no", "No"),
        ("else", "Else"),
    ]
    assert [p["name"] for p in described["switch"]["outputs"]] == [
        *(f"case_{n}" for n in range(1, 7)),
        "else",
    ]
    settings = {s["key"]: s for s in described["if"]["settings"]}
    assert settings["operator_5"]["options"] == list(OPERATORS)
    assert (settings["left_3"]["group"], settings["right_3"]["group"]) == ("Condition 3",) * 2
    assert (
        settings["combine"]["options"] == ["all", "any"]
        and settings["case_sensitive"]["default"] is True
    )
    assert described["code"]["settings"][3]["key"] == "sets_variables"


def test_settings_are_validated_on_save_and_a_secret_is_refused(client: TestClient) -> None:
    action = post(client, "/api/actions", name="Rules")
    made = node(client, action, "if")
    assert made["config"]["combine"] == "all" and made["config"]["operator_2"] == "equals"
    url = f"{graph_url(action)}/nodes/{made['id']}"

    def patch(config: dict[str, Any]) -> Any:
        return client.patch(url, json={"config": config})

    assert patch({"left_1": "${var.a}", "operator_1": "is empty"}).status_code == 200
    assert patch({"operator_1": "matches"}).status_code == 422
    assert patch({"left_1": "x" * 501}).status_code == 422
    assert patch({"left_6": "x"}).status_code == 422  # only five rows
    assert patch({"combine": "some"}).status_code == 422
    refused = patch({"right_2": "${secret:API_KEY}"})
    assert (
        refused.status_code == 422
        and "secret" in refused.text
        and "API_KEY" not in refused.text.replace("${secret:NAME}", "")
    )
    switch = node(client, action, "switch")
    assert (
        client.patch(
            f"{graph_url(action)}/nodes/{switch['id']}", json={"config": {"value": "${secret:K}"}}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"{graph_url(action)}/nodes/{switch['id']}", json={"config": {"case_7": "x"}}
        ).status_code
        == 422
    )


def test_reference_hints_come_back_as_warnings(client: TestClient) -> None:
    action = post(client, "/api/actions", name="Hints")
    code = node(client, action, "code", name="Fetch")
    del code
    made = node(client, action, "if")
    url = f"{graph_url(action)}/nodes/{made['id']}"
    ok = client.patch(url, json={"config": {"left_1": "${node.Fetch.output}"}}).json()
    assert ok["warnings"] == []
    bad = client.patch(url, json={"config": {"left_2": "${node.Nobody.output} ${node.x}"}}).json()
    assert any("no node is named" in w for w in bad["warnings"])
    assert any("malformed" in w for w in bad["warnings"])
    switch = node(client, action, "switch")
    hint = client.patch(
        f"{graph_url(action)}/nodes/{switch['id']}",
        json={"config": {"value": "${node.Ghost.data}"}},
    ).json()
    assert any("Ghost" in w for w in hint["warnings"])


def test_only_declared_ports_exist_and_unused_cases_have_no_edge(client: TestClient) -> None:
    action = post(client, "/api/actions", name="Ports")
    output = kind_of(client, action, "output")
    branch, switch = (
        node(client, action, "if"),
        node(client, action, "switch", config={"case_2": "gold"}),
    )
    for source, port in (
        (branch, "pass"),
        (branch, "fail"),
        (branch, "out"),
        (switch, "case_7"),
        (switch, "yes"),
    ):
        response = client.post(
            f"{graph_url(action)}/edges",
            json={
                "source_id": source["id"],
                "source_port": port,
                "target_id": output["id"],
                "target_port": "pass",
            },
        )
        assert response.status_code == 422, (port, response.text)
    unused = client.post(
        f"{graph_url(action)}/edges",
        json={
            "source_id": switch["id"],
            "source_port": "case_1",
            "target_id": output["id"],
            "target_port": "pass",
        },
    )
    assert unused.status_code == 422 and "unused" in unused.text
    for source, port in (
        (branch, "yes"),
        (branch, "no"),
        (branch, "else"),
        (switch, "case_2"),
        (switch, "else"),
    ):
        connect(client, action, source, port, output, "pass")
    again = client.post(
        f"{graph_url(action)}/edges",
        json={
            "source_id": branch["id"],
            "source_port": "yes",
            "target_id": branch["id"],
            "target_port": "in",
        },
    )
    assert again.status_code == 422  # not to itself
    assert node_type(NodeKind.IF).input_names() == ("in",)
    before = len(client.get(graph_url(action)).json()["edges"])
    cleared = client.patch(
        f"{graph_url(action)}/nodes/{switch['id']}", json={"config": {"case_2": ""}}
    )
    assert cleared.status_code == 200
    edges = client.get(graph_url(action)).json()["edges"]
    assert len(edges) == before - 1  # the connection of the emptied case went with its output
    assert not any(e["source_id"] == switch["id"] and e["source_port"] == "case_2" for e in edges)


# ── sets_variables ───────────────────────────────────────────────────


def test_sets_variables_is_checked_on_save(client: TestClient) -> None:
    action = post(client, "/api/actions", name="Declared")
    made = node(client, action, "code")
    url = f"{graph_url(action)}/nodes/{made['id']}"
    assert client.patch(url, json={"config": {"sets_variables": "a\nb_2\n"}}).status_code == 200
    assert client.patch(url, json={"config": {"sets_variables": "Bad Name"}}).status_code == 422


def test_a_difference_from_the_declared_variables_is_noted_but_never_fails() -> None:
    config = {"sets_variables": "tier\nscore"}
    done = _note_variables(NodeResult("pass", variables={"tier": 1, "extra": 2}), config)
    assert done.outcome == "pass"
    assert done.reason == "undeclared variable 'extra'; declared variable 'score' was not set"
    same = _note_variables(NodeResult("pass", variables={"tier": 1, "score": 2}), config)
    assert same.reason is None
    failed = _note_variables(NodeResult("fail", reason="boom"), config)
    assert failed.reason == "boom"
    nothing_declared = _note_variables(
        NodeResult("pass", variables={"x": 1}), {"sets_variables": ""}
    )
    assert nothing_declared.reason is None


# ── engine: runs through a definition ────────────────────────────────


def _echo(port: str) -> dict[str, Any]:
    return {"language": "sh", "code": f"echo reached-{port}"}


def _branching_run(
    client: TestClient,
    setter: str,
    branch_kind: str,
    branch_config: dict[str, Any],
    wired: tuple[str, ...],
    *,
    declared: str = "",
    status: str = "done",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Trigger -> Code 'Classify' -> If/Switch 'Decide' -> a Code node per wired port -> Output.

    Ports in ``wired`` get a node ``Went <port>``; the others are dead ends. Returns the pipeline,
    the task and the definition; the run has finished.
    """
    pipeline = build_pipeline(client, stages=1)
    action = post(client, "/api/actions", name="Triage")
    trigger, output = kind_of(client, action, "trigger"), kind_of(client, action, "output")
    for edge in client.get(graph_url(action)).json()["edges"]:
        client.delete(f"{graph_url(action)}/edges/{edge['id']}")
    classify = node(
        client,
        action,
        "code",
        name="Classify",
        config={"language": "sh", "code": setter, "sets_variables": declared},
    )
    decide = node(client, action, branch_kind, name="Decide", config=branch_config)
    connect(client, action, trigger, "out", classify, "in")
    connect(client, action, classify, "pass", decide, "in")
    for port in wired:
        step = node(client, action, "code", name=f"Went {port}", config=_echo(port))
        connect(client, action, decide, port, step, "in")
        connect(client, action, step, "pass", output, "pass")
    link(client, pipeline, pipeline["stages"][0][1], action)
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(client, task, status)
    return pipeline, task, action


def _steps(client: TestClient, task: dict[str, Any]) -> list[dict[str, Any]]:
    execution_id = run_of(client, task)["execution_id"]
    detail = client.get(f"/api/tasks/{task['id']}/executions/{execution_id}").json()
    return detail["steps"]  # type: ignore[no-any-return]


SET_PRIORITY = """echo '{"ok": true, "vars": {"priority": "high", "score": 7}}'"""
IF_HIGH = {
    "left_1": "${var.priority}",
    "operator_1": "equals",
    "right_1": "high",
    "left_2": "${var.score}",
    "operator_2": "greater than",
    "right_2": "5",
}


def test_an_if_after_a_code_node_takes_the_yes_path_and_the_flow_shows_it(
    client: TestClient,
) -> None:
    _, task, _ = _branching_run(
        client, SET_PRIORITY, "if", IF_HIGH, ("yes", "no", "else"), declared="priority\nscore"
    )
    steps = _steps(client, task)
    names = [s["node_name"] for s in steps]
    assert names == ["Trigger", "Classify", "Decide", "Went yes", "Output"]
    classify, decide = steps[1], steps[2]
    assert classify["reason"] is None  # declared variables match
    assert (decide["outcome"], decide["port"]) == ("pass", "yes")
    assert decide["data"]["condition"] is True
    assert [r["result"] for r in decide["data"]["rows"]] == [True, True]
    assert run_of(client, task)["status"] == "done"
    execution = client.get(f"/api/tasks/{task['id']}/executions").json()["items"][0]
    flow = client.get(f"/api/tasks/{task['id']}/executions/{execution['id']}/flow").json()
    visit = flow["visits"][1]
    taken = [(e["source_port"], e["target_id"]) for e in visit["edges"]]
    yes_node = next(
        n for n in flow["graphs"][visit["graph_id"]]["nodes"] if n["name"] == "Went yes"
    )
    assert ("yes", yes_node["id"]) in taken and not any(p in ("no", "else") for p, _ in taken)
    assert (visit["outcome"], visit["left_port"]) == ("pass", "pass")


def test_the_no_path_and_a_run_context_the_branch_node_leaves_behind(client: TestClient) -> None:
    config = {"left_1": "${var.score}", "operator_1": "less than", "right_1": "5"}
    _, task, _ = _branching_run(client, SET_PRIORITY, "if", config, ("yes", "no"))
    steps = _steps(client, task)
    assert [s["node_name"] for s in steps][-2:] == ["Went no", "Output"]
    execution_id = run_of(client, task)["execution_id"]
    context = client.get(f"/api/tasks/{task['id']}/executions/{execution_id}/context").json()
    assert context["nodes"]["Decide"]["port"] == "no"
    assert context["nodes"]["Decide"]["data"]["condition"] is False


def test_the_else_path_marks_the_step_failed_and_a_dead_end_fails_the_action(
    client: TestClient,
) -> None:
    config = {"left_1": "${var.nothing}", "operator_1": "is empty"}
    _, task, _ = _branching_run(client, SET_PRIORITY, "if", config, ("else",))
    steps = _steps(client, task)
    decide = steps[2]
    assert (decide["outcome"], decide["port"]) == ("fail", "else")
    assert "${var.nothing}" in decide["reason"] and steps[3]["node_name"] == "Went else"
    # nothing connected at 'else': the action fails like any dead end
    _, task2, _ = _branching_run(client, SET_PRIORITY, "if", config, ("yes",), status="failed")
    steps2 = _steps(client, task2)
    assert steps2[-1]["node_name"] == "Decide" and steps2[-1]["outcome"] == "fail"
    execution = client.get(f"/api/tasks/{task2['id']}/executions").json()["items"][0]
    flow = client.get(f"/api/tasks/{task2['id']}/executions/{execution['id']}/flow").json()
    assert flow["visits"][1]["outcome"] == "fail"


def test_a_switch_with_three_cases_and_an_else(client: TestClient) -> None:
    config = {"value": "${var.priority}", "case_1": "low", "case_2": "high", "case_3": "urgent"}
    _, task, _ = _branching_run(
        client, SET_PRIORITY, "switch", config, ("case_1", "case_2", "case_3", "else")
    )
    steps = _steps(client, task)
    decide = steps[2]
    assert (decide["port"], decide["data"]) == ("case_2", {"value": "high", "matched": "case_2"})
    assert steps[3]["node_name"] == "Went case_2"
    nothing = {**config, "case_2": "medium"}
    _, task2, _ = _branching_run(
        client, SET_PRIORITY, "switch", nothing, ("case_1", "case_2", "else")
    )
    steps2 = _steps(client, task2)
    assert (steps2[2]["outcome"], steps2[2]["port"]) == ("pass", "else")
    assert steps2[3]["node_name"] == "Went else"


def test_a_difference_from_sets_variables_is_noted_in_the_step(client: TestClient) -> None:
    _, task, _ = _branching_run(
        client, SET_PRIORITY, "if", IF_HIGH, ("yes",), declared="priority\nlevel"
    )
    classify = _steps(client, task)[1]
    assert classify["outcome"] == "pass"
    assert (
        classify["reason"] == "undeclared variable 'score'; declared variable 'level' was not set"
    )


def test_the_snapshot_freezes_the_condition(client: TestClient) -> None:
    _, task, action = _branching_run(client, SET_PRIORITY, "if", IF_HIGH, ("yes", "no"))
    decide = next(n for n in client.get(graph_url(action)).json()["nodes"] if n["name"] == "Decide")
    client.patch(f"{graph_url(action)}/nodes/{decide['id']}", json={"config": {"right_1": "low"}})
    execution = client.get(f"/api/tasks/{task['id']}/executions").json()["items"][0]
    flow = client.get(f"/api/tasks/{task['id']}/executions/{execution['id']}/flow").json()
    frozen = next(n for n in flow["graphs"][action["id"]]["nodes"] if n["name"] == "Decide")
    assert frozen["config"]["right_1"] == "high"


def test_migration_0029_allows_if_and_switch_and_the_downgrade_removes_them(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0028")
    insert = "INSERT INTO graph_nodes (id, graph_id, kind, name) VALUES (?, 'g', ?, ?)"
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO graphs (id, name, slug, kind) VALUES ('g', 'G', 'g', 'action')")
        with pytest.raises(sqlite3.IntegrityError, match="ck_graph_nodes_kind"):
            conn.execute(insert, ("i", "if", "If"))
    command.upgrade(alembic_config(), "0029")
    with sqlite3.connect(db) as conn:
        for node_id, kind in (("i", "if"), ("s", "switch"), ("c", "code")):
            conn.execute(insert, (node_id, kind, kind))
    command.downgrade(alembic_config(), "0028")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id FROM graph_nodes").fetchall() == [("c",)]
