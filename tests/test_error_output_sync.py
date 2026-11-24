"""The error output of an action is one state shared by the definition and its uses (ADR-061 addendum).

The definition's Output has the switch *On Fail* (``fail_enabled``); a use of the definition (an action node in a stage)
has *If the action fails: Error output* (``on_failure: error_output``). The server keeps the two in step, both ways, in one
transaction, and where a change takes a connector away it disconnects instead of refusing, saying what it disconnected.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.database import new_session
from openartifact.graph.repository import GraphRepository
from openartifact.models import GraphNode
from tests.helpers import build_definition, build_pipeline, graph_url, kind_of, link, node


def _patch(client: TestClient, graph: dict[str, Any], node_: dict[str, Any], **body: Any) -> Any:
    response = client.patch(f"{graph_url(graph)}/nodes/{node_['id']}", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _mode(client: TestClient, graph: dict[str, Any], node_: dict[str, Any]) -> str:
    nodes = client.get(graph_url(graph)).json()["nodes"]
    return next(n for n in nodes if n["id"] == node_["id"])["config"]["on_failure"]


def _flag(client: TestClient, definition: dict[str, Any]) -> bool:
    return bool(kind_of(client, definition, "output")["fail_enabled"])


def _edges(client: TestClient, graph: dict[str, Any], port: str) -> list[dict[str, Any]]:
    return [e for e in client.get(graph_url(graph)).json()["edges"] if e["source_port"] == port]


def _raw_edge(
    client: TestClient,
    graph: dict[str, Any],
    a: dict[str, Any],
    ap: str,
    b: dict[str, Any],
    bp: str,
) -> Any:
    return client.post(
        f"{graph_url(graph)}/edges",
        json={"source_id": a["id"], "source_port": ap, "target_id": b["id"], "target_port": bp},
    )


def _uses(
    client: TestClient, definition: dict[str, Any], count: int
) -> tuple[dict[str, Any], list[Any]]:
    """A pipeline with ``count`` stages, each action running ``definition``."""
    pipeline = build_pipeline(client, stages=count)
    for _stage, action in pipeline["stages"]:
        link(client, pipeline, action, definition)
    return pipeline, [action for _stage, action in pipeline["stages"]]


def test_switching_on_fail_on_gives_every_use_in_stop_mode_the_error_output(
    client: TestClient,
) -> None:
    definition = build_definition(client, "Work")
    pipeline, uses = _uses(client, definition, 3)
    _patch(client, pipeline, uses[2], config={"on_failure": "continue"})
    assert [_mode(client, pipeline, u) for u in uses] == ["fail", "fail", "continue"]

    answer = _patch(client, definition, kind_of(client, definition, "output"), fail_enabled=True)

    assert answer["notices"] == []  # switching on says nothing: no behaviour changes
    assert [_mode(client, pipeline, u) for u in uses] == [
        "error_output",
        "error_output",
        "continue",
    ]


def test_a_use_set_to_the_error_output_switches_the_definition_on_without_a_notice_when_alone(
    client: TestClient,
) -> None:
    definition = build_definition(client, "Work")
    pipeline, uses = _uses(client, definition, 1)
    assert _flag(client, definition) is False

    answer = _patch(client, pipeline, uses[0], config={"on_failure": "error_output"})

    assert _flag(client, definition) is True
    assert answer["notices"] == []  # no other use: nothing to warn about


def test_with_other_uses_the_notice_says_so_and_the_others_get_the_error_output(
    client: TestClient,
) -> None:
    definition = build_definition(client, "Work")
    pipeline, uses = _uses(client, definition, 3)
    _patch(client, pipeline, uses[2], config={"on_failure": "continue"})

    answer = _patch(client, pipeline, uses[0], config={"on_failure": "error_output"})

    assert answer["notices"] == [{"kind": "definition_on", "definition": "Work", "uses": 2}]
    assert answer["reload"] is True  # another use of this very pipeline changed
    assert [_mode(client, pipeline, u) for u in uses] == [
        "error_output",
        "error_output",
        "continue",
    ]
    # nothing to say when it was on already
    again = _patch(client, pipeline, uses[2], config={"on_failure": "error_output"})
    assert again["notices"] == []


def test_switching_the_definition_off_disconnects_the_uses_and_the_inner_connection(
    client: TestClient,
) -> None:
    definition = build_definition(client, "Work", fail_enabled=True)
    pipeline, uses = _uses(client, definition, 2)
    assert [_mode(client, pipeline, u) for u in uses] == ["error_output", "error_output"]
    stages = [stage for stage, _action in pipeline["stages"]]
    for use, stage in zip(
        uses, stages, strict=True
    ):  # On Error of each use goes to its stage's end
        _raw_edge(client, pipeline, use, "error", stage, "end").raise_for_status()
    trigger, output = kind_of(client, definition, "trigger"), kind_of(client, definition, "output")
    _raw_edge(client, definition, trigger, "out", output, "fail").raise_for_status()

    answer = _patch(client, definition, output, fail_enabled=False)

    assert _edges(client, pipeline, "error") == []
    assert [_mode(client, pipeline, u) for u in uses] == ["fail", "fail"]
    assert [
        e for e in client.get(graph_url(definition)).json()["edges"] if e["target_port"] == "fail"
    ] == []
    (notice,) = answer["notices"]
    assert notice["kind"] == "disconnected" and notice["count"] == 3 and notice["inner"] == 1
    in_pipeline = [p for p in notice["places"] if p["graph"] == pipeline["name"]]
    assert sorted(p["node"] for p in in_pipeline) == sorted(u["name"] for u in uses)
    assert all(p["count"] == 1 for p in in_pipeline)
    assert {"graph": "Work", "stage": None, "node": "Output", "count": 1} in notice["places"]


def test_switching_the_definition_off_says_nothing_when_nothing_was_connected(
    client: TestClient,
) -> None:
    definition = build_definition(client, "Work", fail_enabled=True)
    pipeline, uses = _uses(client, definition, 1)

    answer = _patch(client, definition, kind_of(client, definition, "output"), fail_enabled=False)

    assert answer["notices"] == []
    assert _mode(client, pipeline, uses[0]) == "fail"


def test_a_use_leaving_the_error_output_disconnects_it_and_keeps_the_definition_on_for_another(
    client: TestClient,
) -> None:
    definition = build_definition(client, "Work", fail_enabled=True)
    pipeline, uses = _uses(client, definition, 2)
    stage = pipeline["stages"][0][0]
    _raw_edge(client, pipeline, uses[0], "error", stage, "end").raise_for_status()

    answer = _patch(client, pipeline, uses[0], config={"on_failure": "continue"})

    assert _edges(client, pipeline, "error") == []  # the connection went, no refusal
    assert _flag(client, definition) is True  # the other use still has the error output
    kinds = [n["kind"] for n in answer["notices"]]
    assert kinds == ["disconnected", "definition_stays_on"]
    assert answer["notices"][1] == {"kind": "definition_stays_on", "definition": "Work", "uses": 1}


def test_the_last_use_leaving_the_error_output_switches_the_definition_off(
    client: TestClient,
) -> None:
    definition = build_definition(client, "Work", fail_enabled=True)
    pipeline, uses = _uses(client, definition, 1)

    answer = _patch(client, pipeline, uses[0], config={"on_failure": "fail"})

    assert _flag(client, definition) is False
    assert answer["notices"] == []  # nothing was connected, nothing to report


def test_the_inner_connection_is_reported_when_the_last_use_switches_the_definition_off(
    client: TestClient,
) -> None:
    definition = build_definition(client, "Work", fail_enabled=True)
    pipeline, uses = _uses(client, definition, 1)
    trigger, output = kind_of(client, definition, "trigger"), kind_of(client, definition, "output")
    _raw_edge(client, definition, trigger, "out", output, "fail").raise_for_status()

    answer = _patch(client, pipeline, uses[0], config={"on_failure": "continue"})

    assert _flag(client, definition) is False
    (notice,) = answer["notices"]
    assert notice["kind"] == "disconnected" and notice["inner"] == 1
    assert notice["places"] == [{"graph": "Work", "stage": None, "node": "Output", "count": 1}]


def test_a_node_leaving_the_error_output_loses_its_connection_instead_of_being_refused(
    client: TestClient,
) -> None:
    action = build_definition(client, "Do code", output=None)
    trigger, output = kind_of(client, action, "trigger"), kind_of(client, action, "output")
    step = node(client, action, "code", config={"code": "true", "on_failure": "error_output"})
    _raw_edge(client, action, trigger, "out", step, "in").raise_for_status()
    _raw_edge(client, action, step, "pass", output, "pass").raise_for_status()
    _patch(client, action, output, fail_enabled=True)
    _raw_edge(client, action, step, "fail", output, "fail").raise_for_status()

    answer = _patch(client, action, step, config={"on_failure": "continue"})

    assert _edges(client, action, "fail") == []
    (notice,) = answer["notices"]
    assert notice["kind"] == "disconnected" and notice["count"] == 1
    assert notice["places"][0]["node"] == step["name"]
    assert answer["config"]["on_failure"] == "continue"


def test_a_connection_to_a_port_that_is_not_there_is_still_refused(client: TestClient) -> None:
    definition = build_definition(client, "Work")
    pipeline, uses = _uses(client, definition, 1)
    stage = pipeline["stages"][0][0]
    refused = _raw_edge(client, pipeline, uses[0], "error", stage, "end")
    assert refused.status_code == 422 and "error output" in refused.json()["detail"]


def test_linking_a_use_to_a_definition_with_the_error_output_gives_it_the_error_output(
    client: TestClient,
) -> None:
    definition = build_definition(client, "Work", fail_enabled=True)
    pipeline = build_pipeline(client, stages=2)
    first, second = (action for _stage, action in pipeline["stages"])
    _patch(client, pipeline, second, config={"on_failure": "continue"})

    link(client, pipeline, first, definition)
    link(client, pipeline, second, definition)

    assert _mode(client, pipeline, first) == "error_output"
    assert _mode(client, pipeline, second) == "continue"


def test_linking_a_use_in_the_error_output_mode_to_a_definition_without_it_switches_it_on(
    client: TestClient,
) -> None:
    definition = build_definition(client, "Work")
    pipeline = build_pipeline(client, stages=1)
    action = pipeline["stages"][0][1]
    _patch(client, pipeline, action, config={"on_failure": "error_output"})

    answer = client.patch(
        f"{graph_url(pipeline)}/nodes/{action['id']}", json={"definition_id": definition["id"]}
    ).json()

    assert _flag(client, definition) is True
    assert answer["notices"] == []  # alone


def test_several_output_nodes_of_a_definition_agree(client: TestClient) -> None:
    """Older definitions may hold several Output nodes: the switch of one is the switch of all."""
    definition = build_definition(client, "Work")
    first = kind_of(client, definition, "output")

    async def second_output() -> None:  # the API refuses a second Output; old data had it
        async with new_session() as session:
            session.add(
                GraphNode(
                    id="00000000-0000-4000-8000-0000000000aa",
                    graph_id=definition["id"],
                    kind="output",
                    name="Output 2",
                    x=0.0,
                    y=0.0,
                    fail_enabled=False,
                    config={},
                )
            )
            await session.commit()

    client.portal.call(second_output)  # type: ignore[union-attr]
    _patch(client, definition, first, fail_enabled=True)
    outputs = [
        n for n in client.get(graph_url(definition)).json()["nodes"] if n["kind"] == "output"
    ]
    assert len(outputs) == 2 and all(o["fail_enabled"] for o in outputs)
    _patch(client, definition, first, fail_enabled=False)
    outputs = [
        n for n in client.get(graph_url(definition)).json()["nodes"] if n["kind"] == "output"
    ]
    assert not any(o["fail_enabled"] for o in outputs)


def test_a_failure_in_the_middle_changes_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One transaction: when the sync fails after it switched the uses, nothing is kept."""
    definition = build_definition(client, "Work")
    pipeline, uses = _uses(client, definition, 2)
    original = GraphRepository._promote_uses

    async def broken(self: GraphRepository, uses_: Any, report: Any) -> None:
        await original(self, uses_, report)
        raise RuntimeError("boom")

    monkeypatch.setattr(GraphRepository, "_promote_uses", broken)
    output = kind_of(client, definition, "output")
    with pytest.raises(RuntimeError, match="boom"):
        client.patch(f"{graph_url(definition)}/nodes/{output['id']}", json={"fail_enabled": True})
    monkeypatch.undo()

    assert _flag(client, definition) is False
    assert [_mode(client, pipeline, u) for u in uses] == ["fail", "fail"]
