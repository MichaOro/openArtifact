"""The order of a pipeline and the way through it, on plain dicts (no database, no HTTP)."""

from __future__ import annotations

from typing import Any

import pytest

from openartifact.engine.chain import edge_from, locate, pipeline_chain
from openartifact.engine.targets import TargetError, pick_start


def n(id_: str, kind: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": id_,
        "kind": kind,
        "stage_id": None,
        "name": id_,
        "label": id_,
        "definition_id": None,
        "seconds": None,
        "x": 0,
        "y": 0,
        **extra,
    }


def e(source: str, port: str, target: str, target_port: str = "in") -> dict[str, Any]:
    return {
        "source_id": source,
        "source_port": port,
        "target_id": target,
        "target_port": target_port,
    }


def names(chain: list[dict[str, Any]]) -> list[str]:
    return [entry["id"] for entry in chain]


def test_a_pipeline_without_a_trigger_has_no_chain() -> None:
    assert pipeline_chain([n("s", "stage")], []) == []


def test_a_trigger_that_is_not_connected_has_no_chain() -> None:
    assert pipeline_chain([n("t", "trigger"), n("s", "stage")], []) == []


def test_the_chain_follows_the_connections_not_the_position() -> None:
    nodes = [n("t", "trigger"), n("b", "stage", x=0), n("a", "stage", x=500), n("c", "complete")]
    edges = [e("t", "out", "a", "start"), e("a", "end", "b", "start"), e("b", "end", "c")]
    assert names(pipeline_chain(nodes, edges)) == [
        "a",
        "b",
    ]  # "b" lies left of "a" and comes second


def test_the_chain_stops_at_an_open_end_and_leaves_stages_off_the_path_out() -> None:
    nodes = [n("t", "trigger"), n("a", "stage"), n("b", "stage"), n("lonely", "stage")]
    edges = [e("t", "out", "a", "start")]
    assert names(pipeline_chain(nodes, edges)) == ["a"]
    edges.append(e("a", "end", "b", "start"))
    assert names(pipeline_chain(nodes, edges)) == ["a", "b"]  # "lonely" is never reached


def test_a_loop_between_stages_is_cut_where_it_closes() -> None:
    nodes = [n("t", "trigger"), n("a", "stage"), n("b", "stage")]
    edges = [e("t", "out", "a", "start"), e("a", "end", "b", "start"), e("b", "end", "a", "start")]
    assert names(pipeline_chain(nodes, edges)) == ["a", "b"]


def test_the_actions_of_a_stage_are_left_to_right_and_the_first_one_is_where_start_points() -> None:
    nodes = [
        n("t", "trigger"),
        n("s", "stage"),
        n("late", "action", stage_id="s", x=300),
        n("early", "action", stage_id="s", x=20),
        n("other", "stage"),
        n("foreign", "action", stage_id="other"),
    ]
    edges = [e("t", "out", "s", "start")]
    stage = pipeline_chain(nodes, edges)[0]
    assert [a["id"] for a in stage["actions"]] == ["early", "late"]
    assert stage["first_action_id"] == "early"  # no connection: the leftmost

    edges.append(e("s", "start", "late"))
    assert pipeline_chain(nodes, edges)[0]["first_action_id"] == "late"  # the connection decides

    edges[-1] = e("s", "start", "foreign")  # a start edge into another stage's action is ignored
    assert pipeline_chain(nodes, edges)[0]["first_action_id"] == "early"


def test_a_stage_without_actions_has_no_first_action() -> None:
    chain = pipeline_chain([n("t", "trigger"), n("s", "stage")], [e("t", "out", "s", "start")])
    assert chain[0]["actions"] == [] and chain[0]["first_action_id"] is None


def test_a_pipeline_node_is_an_entry_named_after_its_pipeline() -> None:
    nodes = [
        n("t", "trigger"),
        n("call", "pipeline", label="Deploy", definition_id="p2"),
        n("empty", "pipeline"),
        n("s", "stage"),
    ]
    edges = [e("t", "out", "call"), e("call", "out", "empty"), e("empty", "out", "s", "start")]
    chain = pipeline_chain(nodes, edges)
    assert [(c["kind"], c["name"], c.get("pipeline_id")) for c in chain] == [
        ("pipeline", "Deploy", "p2"),
        ("pipeline", "empty", None),
        ("stage", "s", None),
    ]
    assert chain[0]["first_action_id"] is None and chain[0]["actions"] == []


def test_edge_from_finds_the_connection_of_a_port() -> None:
    edges = [e("a", "pass", "b"), e("a", "error", "c")]
    assert edge_from(edges, "a", "error") == edges[1]
    assert edge_from(edges, "a", "other") is None
    assert edge_from(edges, "b", "pass") is None


# ── where a node of a run is ──────────────────────────────────────────


def snapshot(depth: int) -> dict[str, Any]:
    """P0 calls P1 calls ... P<depth>; every pipeline has a stage ``s<i>`` and the call node ``call<i>``."""
    pipelines: dict[str, dict[str, Any]] = {}
    for i in range(depth + 1):
        nodes = [n(f"t{i}", "trigger"), n(f"s{i}", "stage")]
        edges = [e(f"t{i}", "out", f"s{i}", "start")]
        if i < depth:
            nodes.append(n(f"call{i}", "pipeline", definition_id=f"P{i + 1}"))
            edges.append(e(f"s{i}", "end", f"call{i}"))
        pipelines[f"P{i}"] = {"name": f"Name {i}", "nodes": nodes, "edges": edges}
    root: dict[str, Any] = dict(pipelines["P0"])
    root["pipelines"] = {k: v for k, v in pipelines.items() if k != "P0"}
    return root


@pytest.mark.parametrize("node_id", [None, "s0", "call0"])
def test_a_node_of_the_outermost_pipeline_is_its_own_entry(node_id: str | None) -> None:
    where = locate(snapshot(2), node_id)
    assert where == {"pipeline_id": None, "pipeline_name": "Name 0", "entry_id": node_id}


@pytest.mark.parametrize(("depth", "node_id"), [(1, "s1"), (2, "s2"), (3, "s3")])
def test_a_node_in_a_called_pipeline_leads_back_to_the_calling_entry(
    depth: int, node_id: str
) -> None:
    """One, two and three levels down: the entry is always the call node of the outermost pipeline."""
    where = locate(snapshot(depth), node_id)
    assert where == {
        "pipeline_id": f"P{depth}",
        "pipeline_name": f"Name {depth}",
        "entry_id": "call0",
    }


def test_a_node_that_belongs_to_no_called_pipeline_has_no_entry() -> None:
    where = locate(snapshot(1), "ghost")
    assert where["pipeline_id"] is None and where["entry_id"] is None


def test_a_cycle_in_the_calls_does_not_loop_for_ever() -> None:
    snap = snapshot(2)  # P0 -> P1 -> P2, and P2 calls P1 again (only old data can do that)
    snap["pipelines"]["P2"]["nodes"].append(n("back", "pipeline", definition_id="P1"))
    snap["pipelines"]["P9"] = {"name": "Unused", "nodes": [n("x9", "stage")], "edges": []}
    assert locate(snap, "s2")["entry_id"] == "call0"
    # a pipeline nobody calls: the search walks the cycle, finds nothing and gives up
    assert locate(snap, "x9") == {"pipeline_id": "P9", "pipeline_name": "Unused", "entry_id": None}


# ── where a start may be ──────────────────────────────────────────────


def _chain() -> list[dict[str, Any]]:
    nodes = [
        n("t", "trigger"),
        n("s1", "stage"),
        n("a1", "action", stage_id="s1"),
        n("call", "pipeline", definition_id="p"),
    ]
    return pipeline_chain(
        nodes, [e("t", "out", "s1", "start"), e("s1", "end", "call"), e("s1", "start", "a1")]
    )


def test_the_default_start_is_the_first_entry_and_its_first_action() -> None:
    index, entry, action = pick_start(_chain(), None, None)
    assert (index, entry["id"], action) == (0, "s1", "a1")


def test_a_start_at_a_pipeline_node_has_no_action() -> None:
    assert pick_start(_chain(), "call", None)[2] is None


@pytest.mark.parametrize(
    ("stage", "action", "message"),
    [("nope", None, "not part of the pipeline"), ("s1", "nope", "not in the stage")],
)
def test_a_start_must_fit_the_pipeline(stage: str, action: str | None, message: str) -> None:
    with pytest.raises(TargetError, match=message):
        pick_start(_chain(), stage, action)


def test_an_empty_chain_cannot_be_started() -> None:
    with pytest.raises(TargetError, match="no stages"):
        pick_start([], None, None)
