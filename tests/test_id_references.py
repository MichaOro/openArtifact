"""References by the id of a node (ADR-082): ``${node:ID.output}`` next to the name forms.

The resolver and the context are plain objects (no engine needed): the id names one node whatever its label is, two nodes of the
same name keep both results, a rename changes no reference, a context stored before ids answers by name.
"""

from __future__ import annotations

from typing import Any

import pytest

from openartifact.engine.context import (
    ContextError,
    NodeIndex,
    RunContext,
    RunView,
    parse,
    problems,
    references_in,
    resolve,
)
from openartifact.engine.results import NodeResult

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
GONE = "33333333-3333-4333-8333-333333333333"
PLACE_1 = "44444444-4444-4444-8444-444444444444"
PLACE_2 = "55555555-5555-4555-8555-555555555555"


def _node(node_id: str, name: str, kind: str = "code") -> dict[str, Any]:
    return {"id": node_id, "name": name, "kind": kind}


def _ran(context: RunContext, node_id: str, name: str, kind: str = "code", **fields: Any) -> None:
    context.record(_node(node_id, name, kind), NodeResult(**{"outcome": "pass", **fields}), "pass")


def _index() -> NodeIndex:
    """Two actions that both have a node called "Fetch", and a pipeline that places an action twice."""
    return NodeIndex.of_graphs(
        [
            {"name": "Load", "nodes": [_node(A, "Fetch")]},
            {"name": "Save", "nodes": [_node(B, "Fetch")]},
        ],
        [
            {
                "name": "Flow",
                "nodes": [_node(PLACE_1, "Check", "action"), _node(PLACE_2, "Check", "action")],
            }
        ],
    )


def test_an_id_reference_is_parsed_with_its_field_and_path() -> None:
    ref = parse(f"node:{A}.data.items.0")
    assert (ref.kind, ref.node_id, ref.field, ref.path, ref.name) == (
        "node",
        A,
        "data",
        ("items", "0"),
        "",
    )
    assert parse(f"node:{A}.success").field == "success"


def test_a_malformed_id_reference_says_what_to_use() -> None:
    for body in (f"node:{A}.output.x", "node:not-a-uuid.output", f"node:{A}.nothing"):
        with pytest.raises(ContextError, match=r"malformed reference .*\$\{node:ID\.output\}"):
            parse(body)


def test_the_candidate_scan_sees_an_id_reference_inside_a_text() -> None:
    found = references_in(f"a ${{node:{A}.output}} b ${{(Fetch).output}}")
    assert [(shown, ref.node_id if ref else None) for shown, ref, _ in found] == [
        (f"${{node:{A}.output}}", A),
        ("${(Fetch).output}", ""),
    ]


def test_two_nodes_of_one_name_keep_both_results_and_the_id_tells_them_apart() -> None:
    context = RunContext()
    _ran(context, A, "Fetch", output="from load")
    _ran(context, B, "Fetch", output="from save")
    index = _index()
    assert resolve(parse(f"node:{A}.output"), context, index) == "from load"
    assert resolve(parse(f"node:{B}.output"), context, index) == "from save"
    assert len(context.nodes) == 2  # nothing was overwritten


def test_a_name_reference_to_those_two_nodes_is_still_ambiguous() -> None:
    context = RunContext()
    _ran(context, A, "Fetch")
    _ran(context, B, "Fetch")
    with pytest.raises(ContextError, match='ambiguous node name "Fetch"'):
        resolve(parse("(Fetch).output"), context, _index())


def test_the_latest_run_of_one_node_wins() -> None:
    context = RunContext()
    _ran(context, A, "Fetch", output="first")
    _ran(context, A, "Fetch", output="second")
    assert resolve(parse(f"node:{A}.output"), context, _index()) == "second"
    assert len(context.nodes) == 1


def test_a_rename_changes_no_reference() -> None:
    context = RunContext()
    _ran(context, A, "Fetch", output="x")
    renamed = NodeIndex.of_graphs([{"name": "Load", "nodes": [_node(A, "Download")]}])
    assert resolve(parse(f"node:{A}.output"), context, renamed) == "x"


def test_an_id_that_no_node_has_says_it_does_not_exist_any_more() -> None:
    with pytest.raises(ContextError, match="does not exist any more in the pipeline"):
        resolve(parse(f"node:{GONE}.output"), RunContext(), _index())


def test_a_node_that_has_not_run_is_told_by_its_current_name() -> None:
    with pytest.raises(ContextError, match='node "Fetch" has not run yet'):
        resolve(parse(f"node:{A}.output"), RunContext(), _index())


def test_a_placement_is_found_by_its_id_and_two_placements_of_one_name_are_apart() -> None:
    context = RunContext()
    _ran(context, PLACE_1, "Check", kind="action", output="one")
    _ran(context, PLACE_2, "Check", kind="action", output="two")
    index = _index()
    assert resolve(parse(f"node:{PLACE_1}.output"), context, index) == "one"
    assert resolve(parse(f"node:{PLACE_2}.output"), context, index) == "two"


def test_a_context_stored_before_ids_answers_by_the_name_of_the_node() -> None:
    legacy = RunContext(
        {"nodes": {"Fetch": {"name": "Fetch", "kind": "code", "outcome": "pass", "output": "old"}}}
    )
    index = NodeIndex.of_graphs([{"name": "Load", "nodes": [_node(A, "Fetch")]}])
    assert resolve(parse(f"node:{A}.output"), legacy, index) == "old"


def test_the_entry_keeps_the_id_it_was_recorded_with() -> None:
    context = RunContext()
    _ran(context, A, "Fetch")
    assert context.nodes["Fetch"]["id"] == A
    assert RunContext.loads(context.dumps()).entry_of(A, "Fetch") is not None


def test_render_replaces_an_id_reference_in_a_text() -> None:
    context = RunContext()
    _ran(context, B, "Fetch", output="done")
    view = RunView(context, _index())
    assert view.render(f"result: ${{node:{B}.output}}") == "result: done"


def test_the_save_hint_names_an_id_nothing_has_and_stays_quiet_for_a_known_one() -> None:
    local = NodeIndex.of_graphs([{"name": "Load", "nodes": [_node(A, "Fetch")]}])
    text = f"${{node:{A}.output}} ${{node:{GONE}.output}}"
    hints = problems(text, local, lambda key: False, None, lambda node_id: node_id == B)
    assert hints == [f"${{node:{GONE}.output}}: no node has this id (it was deleted?)"]
    assert problems(f"${{node:{B}.output}}", local, lambda key: False, None, lambda i: i == B) == []
