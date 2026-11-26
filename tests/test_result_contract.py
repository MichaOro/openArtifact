"""The result contract (ADR-072): every node that ran leaves the same core in the run context, whatever its kind."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.engine.context import ContextError, NodeIndex, RunContext, RunView, parse, resolve
from openartifact.engine.executors import EXECUTORS, Limits
from openartifact.engine.results import NodeResult
from openartifact.graph.node_types import NODE_TYPES, node_type
from openartifact.models import NodeKind
from tests.helpers import build_pipeline as _pipeline
from tests.helpers import make_task as _make_task
from tests.helpers import run_of as _run
from tests.helpers import wait_for_run as _wait
from tests.test_execution_nodes import _definition, _start, _use

#: What every node that ran leaves in the context, and the type of each.
CORE: dict[str, tuple[type, ...]] = {
    "name": (str,),
    "kind": (str,),
    "success": (bool,),
    "outcome": (str,),
    "port": (str, type(None)),
    "exit_code": (int, type(None)),
    "output": (str,),
    "reason": (str, type(None)),
    "data": (dict, type(None)),
    "attempts": (int,),
    "duration_ms": (int, type(None)),
    "at": (str,),
}


def _config(kind: NodeKind) -> dict[str, Any]:
    """The defaults of the kind's settings: the node of a fresh drop, which most kinds fail quickly (nothing is set)."""
    return {
        s.key: s.default
        for s in node_type(kind).settings
        if s.stored_in == "config" and s.default is not None
    }


def test_success_is_the_outcome_and_nothing_else() -> None:
    assert NodeResult("pass").success is True
    assert NodeResult("fail").success is False
    assert NodeResult("pass").attempts == 1 and NodeResult("pass").duration_ms is None


@pytest.mark.parametrize("kind", sorted(EXECUTORS, key=str), ids=lambda k: k.value)
async def test_every_kind_that_executes_leaves_the_core(kind: NodeKind) -> None:
    node = {
        "id": "n1",
        "name": "The node",
        "kind": kind.value,
        "config": _config(kind),
        "seconds": 0,
    }
    result = await EXECUTORS[kind].run(node, Limits(), RunView())
    context = RunContext()
    context.record(node, result, "pass" if result.outcome == "pass" else "fail")
    entry = context.nodes["The_node"]
    assert set(entry) >= set(CORE), f"{kind.value} lacks {sorted(set(CORE) - set(entry))}"
    for field, types in CORE.items():
        assert isinstance(entry[field], types), (
            f"{kind.value}.{field} is {type(entry[field]).__name__}"
        )
    assert entry["success"] is (entry["outcome"] == "pass")  # one fact, said twice
    assert entry["attempts"] == 1


def test_a_kind_that_leaves_a_result_is_one_the_engine_executes() -> None:
    """A manifest that says `produces_result` for a kind with no executor would offer references that never resolve."""
    for kind, node in NODE_TYPES.items():
        if node.produces_result:
            assert kind in EXECUTORS, f"{kind.value} produces a result but has no executor"


def _ran(**fields: Any) -> tuple[RunContext, NodeIndex]:
    node = {"id": "a", "name": "Ping", "kind": "http"}
    context = RunContext()
    context.record(node, NodeResult(**fields), "pass")
    index = NodeIndex.of_graphs([{"name": "A", "nodes": [node]}])
    return context, index


def test_the_new_fields_are_references_and_success_reads_as_a_boolean_text() -> None:
    context, index = _ran(outcome="fail", reason="boom", attempts=3, duration_ms=1500)
    assert resolve(parse("(Ping).success"), context, index) is False
    assert resolve(parse("node.Ping.attempts"), context, index) == 3
    assert resolve(parse("(Ping).duration_ms"), context, index) == 1500
    view = RunView(context, index)
    assert (
        view.render("${(Ping).success}") == "false"
    )  # what `is true` / `is false` of an If node compares
    assert view.render("${(Ping).attempts} tries") == "3 tries"


def test_only_data_takes_a_path() -> None:
    with pytest.raises(ContextError, match="malformed reference"):
        parse("(Ping).success.more")


def test_a_context_stored_before_the_contract_still_answers() -> None:
    old = {
        "nodes": {
            "Ping": {
                "name": "Ping",
                "kind": "http",
                "outcome": "pass",
                "port": "pass",
                "exit_code": None,
                "output": "",
                "reason": None,
                "data": None,
                "at": "2026-11-22T10:00:00.000Z",
            }
        }
    }
    context = RunContext(old)
    index = NodeIndex.of_graphs(
        [{"name": "A", "nodes": [{"id": "a", "name": "Ping", "kind": "http"}]}]
    )
    assert resolve(parse("(Ping).success"), context, index) is True
    assert resolve(parse("(Ping).attempts"), context, index) == 1


def test_a_run_leaves_the_core_with_the_engine_measured_time(client: TestClient) -> None:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code="echo hi; exit 3"))
    _start(client, pipeline, task)
    run = _wait(client, task, "failed")
    execution = _run(client, task)["execution_id"]
    context = client.get(f"/api/tasks/{task['id']}/executions/{execution}/context").json()
    entry = context["nodes"]["Execute_Command"]
    assert (entry["success"], entry["outcome"], entry["exit_code"], entry["attempts"]) == (
        False,
        "fail",
        3,
        1,
    )
    assert isinstance(entry["duration_ms"], int) and entry["duration_ms"] >= 0
    assert [r["kind"] for r in run["node_results"]][-2:] == [
        "code",
        "output",
    ]  # the steps are as before the contract
