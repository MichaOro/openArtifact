"""The MCP tools that report on processing: results of a run, as an agent receives them."""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import build_pipeline, make_task, wait_for_run
from tests.test_execution_nodes import _definition, _start, _use

TOKEN = "mcp-token-" + "x" * 30
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json, text/event-stream",
}


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def _call(api: TestClient, name: str, **arguments: Any) -> tuple[bool, Any]:
    """Call a tool; returns (is_error, the decoded content)."""
    response = api.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    if result.get("isError"):
        return True, result["content"][0]["text"]
    if "structuredContent" in result:
        content = result["structuredContent"]
        return False, content.get("result", content) if set(content) == {"result"} else content
    return False, [json.loads(item["text"]) for item in result["content"]]


def test_results_of_an_artifact_that_never_ran_are_an_empty_list(api: TestClient) -> None:
    task = make_task(api)
    assert _call(api, "get_processing_results", artifact=task["id"]) == (False, [])
    assert _call(api, "get_processing_status", artifact=task["id"]) == (
        False,
        {"status": "never processed"},
    )


def test_results_of_an_unknown_artifact_are_an_error_with_a_message(api: TestClient) -> None:
    failed, text = _call(api, "get_processing_results", artifact="9999")
    assert failed is True
    assert text == "Error executing tool get_processing_results: Artifact not found"


def test_the_results_of_a_run_list_every_step_with_exit_code_and_output(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    code = _definition(api, "code", language="sh", code="echo hello; exit 3", timeout_seconds=5)
    _use(api, pipeline, code)
    _start(api, pipeline, task)
    wait_for_run(api, task, "failed")

    failed, results = _call(api, "get_processing_results", artifact=f"#{task['number']}")
    assert failed is False
    steps = [r for r in results if r["kind"] == "code"]
    assert len(steps) == 1
    step = steps[0]
    assert (step["outcome"], step["exit_code"], step["output"].strip()) == ("fail", 3, "hello")
    assert [r["seq"] for r in results] == list(range(1, len(results) + 1))
    assert json.loads(json.dumps(results)) == results  # plain JSON all the way down
    # the same steps the REST API reports
    assert results == api.get(f"/api/runs/{task['id']}/results").json()


def test_the_results_come_from_the_newest_execution_only(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    _use(api, pipeline, _definition(api, "code", language="sh", code="echo one", timeout_seconds=5))
    _start(api, pipeline, task)
    wait_for_run(api, task, "done")
    first = _call(api, "get_processing_results", artifact=task["id"])[1]
    _start(api, pipeline, task)
    wait_for_run(api, task, "done", where=lambda run: run["execution_number"] == 2)
    second = _call(api, "get_processing_results", artifact=task["id"])[1]
    assert len(second) == len(first)
    assert {s["id"] for s in first}.isdisjoint(s["id"] for s in second)
