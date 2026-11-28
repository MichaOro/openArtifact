"""The lanes can be put in a new order (``POST /api/lanes/order``, ADR-092): the order is each lane's ``position``, every interface shows it,
the first lane is where a card goes when none is given, and a wrong list is a readable 422 that changes nothing."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from tests.test_integration import HEADERS, TOKEN
from tests.test_lane_names import _board  # the owner's lanes
from tests.test_mcp import _call


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def _titles(api: TestClient) -> list[str]:
    return [lane["title"] for lane in api.get("/api/lanes").json()]


def _bus(api: TestClient) -> Any:
    return api.app.state.event_bus  # type: ignore[attr-defined]


def test_the_route_writes_the_positions_and_every_interface_shows_the_new_order(
    api: TestClient,
) -> None:
    _board(api)
    assert _titles(api) == ["Optional", "Must have", "MVP", "DONE"]
    response = api.post(
        "/api/lanes/order", json={"lanes": ["DONE", "MVP", "Optional", "Must have"]}
    )
    assert response.status_code == 200, response.text
    assert [lane["title"] for lane in response.json()] == ["DONE", "MVP", "Optional", "Must have"]
    assert [lane["position"] for lane in response.json()] == [0, 1, 2, 3]
    assert _titles(api) == ["DONE", "MVP", "Optional", "Must have"]
    assert [lane["title"] for lane in api.get("/api/v1/lanes").json()] == _titles(api)
    failed, mcp = _call(api, "list_lanes")
    assert not failed and [lane["name"] for lane in mcp] == _titles(api)
    assert [lane["hue"] for lane in api.get("/api/lanes").json()] == [1, 2, 3, 4], (
        "the colour follows the place"
    )
    page = api.get("/").text
    assert page.index(">DONE<") < page.index(">MVP<") < page.index(">Optional<"), (
        "the page draws them in the new order"
    )


def test_it_takes_names_ids_and_old_keys_and_changes_no_card(api: TestClient) -> None:
    _board(api)
    lanes = {lane["title"]: lane for lane in api.get("/api/lanes").json()}
    before = {t["title"]: t["status"] for t in api.get("/api/tasks").json()}
    order = [lanes["MVP"]["id"], "done_2", "must have", "backlog"]
    assert api.post("/api/lanes/order", json={"lanes": order}).status_code == 200
    assert _titles(api) == ["MVP", "DONE", "Must have", "Optional"]
    after = {t["title"]: t["status"] for t in api.get("/api/tasks").json()}
    assert after == before, "a card keeps its lane"
    assert {lane["title"]: lane["id"] for lane in api.get("/api/lanes").json()} == {
        title: lane["id"] for title, lane in lanes.items()
    }, "the ids stay"


@pytest.mark.parametrize(
    ("lanes", "message"),
    [
        (["Optional", "Must have", "MVP"], "missing: DONE"),
        (["Optional", "Must have", "MVP", "DONE", "Optional"], "named twice"),
        (["Optional", "Must have", "MVP", "Later"], "Unknown lane 'Later'"),
        ([], None),
    ],
)
def test_a_wrong_list_is_a_readable_422_and_changes_nothing(
    api: TestClient, lanes: list[str], message: str | None
) -> None:
    _board(api)
    before = _titles(api)
    response = api.post("/api/lanes/order", json={"lanes": lanes})
    assert response.status_code == 422, response.text
    if message:
        assert message in response.text
    assert _titles(api) == before


def test_the_first_lane_is_where_a_card_goes_and_follows_the_order(api: TestClient) -> None:
    _board(api)
    assert api.post("/api/tasks", json={"title": "A"}).json()["lane_name"] == "Optional"
    api.post("/api/lanes/order", json={"lanes": ["MVP", "Optional", "Must have", "DONE"]})
    assert api.post("/api/tasks", json={"title": "B"}).json()["lane_name"] == "MVP"


def test_a_reorder_publishes_board_lanes_with_the_new_order(api: TestClient) -> None:
    _board(api)
    queue = _bus(api).subscribe()
    api.post("/api/lanes/order", json={"lanes": ["DONE", "MVP", "Must have", "Optional"]})
    event = queue.get_nowait()
    assert event.type == "board.lanes"
    assert [lane["title"] for lane in event.data["lanes"]] == [
        "DONE",
        "MVP",
        "Must have",
        "Optional",
    ]


def test_a_lane_that_is_called_order_still_has_its_own_routes(api: TestClient) -> None:
    """The route is a POST: a lane titled *Order* (key ``order``) is still renamed and deleted by ``PUT``/``DELETE /api/lanes/order``."""
    assert api.post("/api/lanes", json={"title": "Order"}).status_code == 201
    assert api.put("/api/lanes/order", json={"title": "Orders"}).status_code == 200
    assert api.delete("/api/lanes/order").status_code == 200


def test_mcp_has_no_tool_that_reorders(api: TestClient) -> None:
    tools = api.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()[
        "result"
    ]["tools"]
    assert not [t["name"] for t in tools if "lane" in t["name"] and t["name"] != "list_lanes"]
