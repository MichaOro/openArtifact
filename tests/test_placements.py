"""The number of a placement (ADR-082): "Check #1", "#2", "#3" when one definition is placed more than once in a pipeline."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.graph.placements import lowest_free, numbers_of
from tests.helpers import connect, graph_url, kind_of, node, post


@pytest.fixture
def client(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    with TestClient(_create_app(migrated_settings)) as made:
        yield made


def _place(
    client: TestClient, pipeline: dict[str, Any], stage: dict[str, Any], definition: dict[str, Any]
) -> dict[str, Any]:
    action = node(client, pipeline, "action", stage_id=stage["id"], x=24, y=48)
    response = client.patch(
        f"{graph_url(pipeline)}/nodes/{action['id']}", json={"definition_id": definition["id"]}
    )
    assert response.status_code == 200, response.text
    return action


def _numbers(client: TestClient, pipeline: dict[str, Any]) -> dict[str, int | None]:
    nodes = client.get(graph_url(pipeline)).json()["nodes"]
    return {n["id"]: n["placement_number"] for n in nodes if n["kind"] == "action"}


def _pipeline(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    pipeline = post(client, "/api/pipelines", name="Flow")
    stage = node(client, pipeline, "stage", name="Stage")
    connect(client, pipeline, kind_of(client, pipeline, "trigger"), "out", stage, "start")
    return pipeline, stage


def test_the_lowest_free_number_fills_a_gap() -> None:
    assert lowest_free([]) == 1
    assert lowest_free([1, 3]) == 2
    assert lowest_free([1, 2, 3]) == 4
    assert lowest_free([True, "x", 0, -1]) == 1  # no number: not a whole number from 1


def test_only_a_definition_placed_more_than_once_has_numbers_and_kept_numbers_stay() -> None:
    nodes = [
        {"id": "a", "kind": "action", "definition_id": "d", "number": 1},
        {"id": "b", "kind": "action", "definition_id": "d", "number": 3},
        {"id": "c", "kind": "action", "definition_id": "other"},
        {"id": "s", "kind": "stage"},
    ]
    assert numbers_of(nodes) == {"a": 1, "b": 3}  # "c" is the only one of its definition: none


def test_a_node_without_a_number_or_with_a_taken_one_gets_the_lowest_free_in_the_order_of_the_nodes() -> (
    None
):
    nodes = [
        {"id": "a", "kind": "action", "definition_id": "d"},
        {"id": "b", "kind": "action", "definition_id": "d", "number": 1},
        {"id": "c", "kind": "action", "definition_id": "d", "number": 1},
    ]
    assert numbers_of(nodes) == {"b": 1, "a": 2, "c": 3}


def test_three_placements_are_numbered_a_gap_is_filled_and_a_single_one_has_no_number(
    client: TestClient,
) -> None:
    pipeline, stage = _pipeline(client)
    definition = post(client, "/api/actions", name="Check")
    first = _place(client, pipeline, stage, definition)
    assert _numbers(client, pipeline) == {first["id"]: None}  # alone: no number
    second = _place(client, pipeline, stage, definition)
    third = _place(client, pipeline, stage, definition)
    assert _numbers(client, pipeline) == {first["id"]: 1, second["id"]: 2, third["id"]: 3}
    client.delete(f"{graph_url(pipeline)}/nodes/{second['id']}")
    assert _numbers(client, pipeline) == {first["id"]: 1, third["id"]: 3}  # the others keep theirs
    refilled = _place(client, pipeline, stage, definition)
    assert _numbers(client, pipeline) == {first["id"]: 1, third["id"]: 3, refilled["id"]: 2}
    client.delete(f"{graph_url(pipeline)}/nodes/{first['id']}")
    client.delete(f"{graph_url(pipeline)}/nodes/{third['id']}")
    assert _numbers(client, pipeline) == {
        refilled["id"]: None
    }  # alone again: the number is not shown


def test_two_different_definitions_are_numbered_apart_and_the_number_shows_in_the_neighbours(
    client: TestClient,
) -> None:
    pipeline, stage = _pipeline(client)
    check, other = (
        post(client, "/api/actions", name="Check"),
        post(client, "/api/actions", name="Other"),
    )
    a1, a2 = _place(client, pipeline, stage, check), _place(client, pipeline, stage, check)
    b = _place(client, pipeline, stage, other)
    assert _numbers(client, pipeline) == {a1["id"]: 1, a2["id"]: 2, b["id"]: None}
    connect(client, pipeline, stage, "start", a1, "in")
    connect(client, pipeline, a1, "pass", a2, "in")
    neighbours = client.get(f"/api/pipelines/{pipeline['id']}/neighbours?version=draft").json()
    by_id = {n["id"]: n for n in neighbours["nodes"]}
    assert by_id[a1["id"]]["name"] == "Check #1"
    assert [link["name"] for link in by_id[a1["id"]]["successors"]] == ["Check #2"]


def test_a_published_pipeline_keeps_the_numbers_it_was_published_with(client: TestClient) -> None:
    pipeline, stage = _pipeline(client)
    definition = post(client, "/api/actions", name="Check")
    a1, a2, a3 = (_place(client, pipeline, stage, definition) for _ in range(3))
    client.delete(f"{graph_url(pipeline)}/nodes/{a2['id']}")
    published = client.post(f"/api/pipelines/{pipeline['id']}/publish", json={"acknowledge": True})
    assert published.status_code == 200, published.text
    version = client.get(f"/api/pipelines/{pipeline['id']}/versions/1").json()
    kept = {n["id"]: n["number"] for n in version["nodes"] if n["kind"] == "action"}
    assert kept == {a1["id"]: 1, a3["id"]: 3}  # the gap stays: #3 is still #3 in what runs
