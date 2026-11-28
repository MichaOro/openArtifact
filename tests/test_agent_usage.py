"""Where an agent is used: the agent nodes of the drafts and of the published versions of the graphs (``GET /api/agents/{id}/uses``)."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from tests.agent_support import HEADERS, SECURE, make_agent
from tests.helpers import graph_url as _url
from tests.helpers import node as _node
from tests.helpers import post as _post


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    with TestClient(_create_app(migrated_settings.model_copy(update=SECURE))) as client:
        client.headers.update(HEADERS)
        yield client


def _uses(api: TestClient, agent: dict[str, Any]) -> list[dict[str, Any]]:
    response = api.get(f"/api/agents/{agent['id']}/uses")
    assert response.status_code == 200, response.text
    return list(response.json())


def _action_with_node(
    api: TestClient, agent: dict[str, Any], action_name: str, node_name: str, **config: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    action = _post(api, "/api/actions", name=action_name)
    node = _node(api, action, "agent", name=node_name, config={"agent_id": agent["id"], **config})
    return action, node


def _publish(api: TestClient, graph: dict[str, Any]) -> None:
    response = api.post(f"{_url(graph)}/publish", json={"acknowledge": True})
    assert response.status_code in (200, 201), response.text


def test_an_unused_agent_has_no_uses(api: TestClient) -> None:
    assert _uses(api, make_agent(api)) == []


def test_a_node_of_a_draft_that_was_never_published_is_marked_as_not_published(
    api: TestClient,
) -> None:
    agent = make_agent(api)
    action, node = _action_with_node(api, agent, "Planner", "Plan", retries=0)
    (use,) = _uses(api, agent)
    assert (use["node_id"], use["node_name"], use["graph_name"]) == (node["id"], "Plan", "Planner")
    assert use["graph_id"] == action["id"] and use["graph_slug"] == action["slug"]
    assert use["graph_kind"] == "action"
    assert (use["in_draft"], use["published"], use["published_number"]) == (True, False, None)
    assert use["overrides"] == ["retries"]


def test_publishing_the_action_marks_its_node_as_published_with_the_version_number(
    api: TestClient,
) -> None:
    agent = make_agent(api)
    action, _ = _action_with_node(api, agent, "Planner", "Plan")
    _publish(api, action)
    (use,) = _uses(api, agent)
    assert (use["in_draft"], use["published"]) == (True, True)
    assert use["published_number"] == 1
    # a node added to the draft afterwards is not in the published version
    _node(api, action, "agent", name="Second", config={"agent_id": agent["id"]})
    rows = {u["node_name"]: u for u in _uses(api, agent)}
    assert rows["Plan"]["published"] is True
    assert rows["Second"]["published"] is False and rows["Second"]["published_number"] is None


def test_a_node_taken_out_of_the_draft_is_listed_while_the_published_version_still_has_it(
    api: TestClient,
) -> None:
    agent = make_agent(api)
    action, node = _action_with_node(api, agent, "Planner", "Plan")
    _publish(api, action)
    assert api.delete(f"{_url(action)}/nodes/{node['id']}").status_code in (200, 204)
    (use,) = _uses(api, agent)
    assert use["node_id"] == node["id"]
    assert (use["in_draft"], use["published"], use["published_number"]) == (False, True, 1)
    # deleting the agent still looks at the drafts only (as before): nothing refers to it there
    assert api.delete(f"/api/agents/{agent['id']}").status_code in (200, 204)


def test_the_uses_are_sorted_by_graph_and_node_and_follow_a_renamed_graph(
    api: TestClient,
) -> None:
    agent = make_agent(api)
    zeta, _ = _action_with_node(api, agent, "Zeta", "B")
    _node(api, zeta, "agent", name="A", config={"agent_id": agent["id"]})
    alpha, _ = _action_with_node(api, agent, "Alpha", "C")
    assert [(u["graph_name"], u["node_name"]) for u in _uses(api, agent)] == [
        ("Alpha", "C"),
        ("Zeta", "A"),
        ("Zeta", "B"),
    ]
    assert api.patch(_url(alpha), json={"name": "Omega"}).status_code == 200
    assert [u["graph_name"] for u in _uses(api, agent)] == ["Omega", "Zeta", "Zeta"]


def test_another_agent_does_not_show_up(api: TestClient) -> None:
    mine, other = make_agent(api), make_agent(api, name="Other")
    _action_with_node(api, mine, "Planner", "Plan")
    assert _uses(api, other) == []
    assert api.get(f"/api/v1/agents/{other['id']}/uses").json() == []
    assert len(api.get(f"/api/v1/agents/{mine['id']}/uses").json()) == 1


def test_a_missing_agent_is_a_404(api: TestClient) -> None:
    assert api.get("/api/agents/nope/uses").status_code == 404
