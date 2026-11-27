"""A dry run needs no card and an action runs by itself (ADR-089): from its Trigger to its Output, on the hidden card of the graph when
none is chosen; that card is in no list of the board."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import build_pipeline, graph_url, make_task, wait_for_run
from tests.test_execution_nodes import _definition, _use
from tests.test_mcp import _call as mcp_call

TOKEN = "standalone-token-" + "x" * 30
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def _echo(api: TestClient, text: str = "first") -> dict[str, Any]:
    return _definition(api, "code", language="sh", code=f"echo {text}", read_only=True)


def _by_itself(api: TestClient, action: dict[str, Any], **body: Any) -> dict[str, Any]:
    response = api.post(f"/api/graphs/{action['id']}/dry-run", json=body)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def _steps(run: dict[str, Any]) -> list[dict[str, Any]]:
    return list(run["node_results"])


def test_an_action_dry_runs_by_itself_without_a_card_and_ends_at_its_output(
    api: TestClient,
) -> None:
    action = _echo(api)
    started = _by_itself(api, action)
    assert started["dry_run"] is True
    run = wait_for_run(api, {"id": started["task_id"]}, "done")
    steps = _steps(run)
    assert [s["kind"] for s in steps] == ["trigger", "code", "output"], (
        "the action's own nodes, nothing around them"
    )
    assert steps[-1]["outcome"] == "pass"
    assert steps[1]["output"].strip() == "first"
    execution = api.get(f"/api/tasks/{started['task_id']}/executions").json()["items"][0]
    assert execution["dry_run"] is True
    assert execution["pipeline_name"] == action["name"]


def test_the_hidden_card_is_made_once_per_graph_and_reached_by_its_own_route(
    api: TestClient,
) -> None:
    action = _echo(api)
    assert api.get(f"/api/graphs/{action['id']}/dry-run-card").json() == {
        "task_id": None,
        "number": None,
    }
    first = _by_itself(api, action)
    wait_for_run(api, {"id": first["task_id"]}, "done")
    card = api.get(f"/api/graphs/{action['id']}/dry-run-card").json()
    assert card["task_id"] == first["task_id"]
    second = _by_itself(api, action)
    assert second["task_id"] == first["task_id"], "the same hidden card is used again"
    wait_for_run(api, {"id": second["task_id"]}, "done")
    assert len(api.get(f"/api/tasks/{card['task_id']}/executions").json()["items"]) == 2
    assert api.get(f"/api/tasks/{card['number']}").status_code == 200, (
        "its address works like any card's"
    )


def test_the_hidden_card_is_in_no_list_count_or_rule_of_the_board(api: TestClient) -> None:
    visible = make_task(api, "Visible")
    lanes_before = {lane["status"]: lane["artifact_count"] for lane in api.get("/api/lanes").json()}
    action = _echo(api)
    started = _by_itself(api, action)
    wait_for_run(api, {"id": started["task_id"]}, "done")
    for archived in ("exclude", "include", "only"):
        ids = [c["id"] for c in api.get("/api/tasks", params={"archived": archived}).json()]
        assert started["task_id"] not in ids, archived
    assert [c["id"] for c in api.get("/api/tasks").json()] == [visible["id"]]
    now = {lane["status"]: lane["artifact_count"] for lane in api.get("/api/lanes").json()}
    assert now == lanes_before
    ids_v1 = [
        c["id"] for c in api.get("/api/v1/artifacts", params={"archived": "include"}).json()
    ]
    assert ids_v1 and started["task_id"] not in ids_v1
    failed, listed = mcp_call(api, "list_artifacts", include_archived=True)
    assert not failed
    assert all(a["title"] != f"Dry runs of {action['name']}" for a in listed)
    failed, count = mcp_call(api, "count_artifacts", archived="include")
    assert not failed
    assert count["total"] == 1


def test_a_lane_is_deletable_although_a_hidden_card_sits_in_it_and_the_card_moves(
    api: TestClient,
) -> None:
    first = api.get("/api/lanes").json()[0]["status"]
    action = _echo(api)
    started = _by_itself(api, action)
    wait_for_run(api, {"id": started["task_id"]}, "done")
    assert api.get(f"/api/tasks/{started['task_id']}").json()["status"] == first
    for card in api.get("/api/tasks").json():
        if card["status"] == first:
            api.delete(f"/api/tasks/{card['id']}")
    deleted = api.delete(f"/api/lanes/{first}")
    assert deleted.status_code in (200, 204), deleted.text
    assert api.get(f"/api/tasks/{started['task_id']}").json()["status"] != first


def test_a_dry_run_of_the_action_never_enters_a_pipeline_or_its_published_placement(
    api: TestClient,
) -> None:
    """The owner's case: a pipeline published a placement of the action, the action's draft was edited afterwards. Run from the action it
    runs its own nodes and ends at its Output; the pipeline's stages are not in the run, and the draft is what the draft shows."""
    action = _echo(api, "first")
    pipeline = build_pipeline(api, stages=1)
    _use(api, pipeline, action)
    for graph in (action, pipeline):
        assert api.post(f"{graph_url(graph)}/publish").status_code in (200, 201)
    api.patch(
        f"{graph_url(action)}/nodes/{action['node']['id']}",
        json={"config": {"code": "echo edited"}},
    )
    outputs = {}
    for version in ("draft", "published"):
        started = _by_itself(api, action, version=version)
        steps = _steps(wait_for_run(api, {"id": started["task_id"]}, "done"))
        assert [s["kind"] for s in steps] == ["trigger", "code", "output"], version
        outputs[version] = steps[1]["output"].strip()
    assert outputs == {"draft": "edited", "published": "first"}


def test_a_pipeline_dry_run_without_a_card_runs_its_own_graph_and_a_chosen_card_is_used(
    api: TestClient,
) -> None:
    pipeline, card = build_pipeline(api, stages=1), make_task(api)
    started = _by_itself(api, pipeline)
    wait_for_run(api, {"id": started["task_id"]}, "done")
    assert started["task_id"] != card["id"]
    chosen = _by_itself(api, pipeline, task_id=card["id"])
    assert chosen["task_id"] == card["id"], "a card chosen with +Add is used and not the hidden one"
    wait_for_run(api, card, "done")


def test_the_check_before_a_card_less_start_reads_only_and_names_a_wrong_input(
    api: TestClient,
) -> None:
    action = _echo(api)
    response = api.post(
        f"/api/graphs/{action['id']}/dry-run/check", json={"inputs": {"nothing": "x"}}
    )
    assert response.status_code == 200, response.text
    assert any("declares no inputs" in p for p in response.json()["problems"])
    assert api.get(f"/api/graphs/{action['id']}/dry-run-card").json()["task_id"] is None, (
        "checking made no card"
    )


def test_the_integration_api_and_mcp_take_the_card_as_optional(api: TestClient) -> None:
    action = _echo(api, "one")
    assert api.post(f"{graph_url(action)}/publish").status_code in (200, 201)
    api.patch(
        f"{graph_url(action)}/nodes/{action['node']['id']}", json={"config": {"code": "echo two"}}
    )
    response = api.post(f"/api/v1/graphs/{action['name']}/dry-run", json={})
    assert response.status_code == 201, response.text
    run = wait_for_run(api, {"id": response.json()["task_id"]}, "done")
    assert _steps(run)[1]["output"].strip() == "one", "the integration API runs the published version"
    failed, answer = mcp_call(api, "dry_run_graph", graph=action["name"], version="draft")
    assert not failed, answer
    run = wait_for_run(api, {"id": answer["task_id"]}, "done")
    assert _steps(run)[1]["output"].strip() == "two"


def test_a_real_start_cannot_name_an_action_to_run_by_itself(api: TestClient) -> None:
    action, task = _echo(api), make_task(api)
    response = api.post(f"/api/tasks/{task['id']}/run", json={"definition_id": action["id"]})
    assert response.status_code == 422
    assert "dry run" in response.text
