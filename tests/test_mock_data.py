"""Mock data for the dry run (ADR-087): a node hands over a stored result instead of running, in the draft and in a dry run only."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Generator
from http.server import ThreadingHTTPServer
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import build_pipeline, graph_url, make_task, wait_for_run
from tests.test_dry_run import TOKEN, _comment_then_read, _Counting, _dry, _steps
from tests.test_execution_nodes import _definition, _start, _use

HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(
        update={"api_token": TOKEN, "secret_key": "k" * 40, "http_allow_private_networks": True}
    )
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


@pytest.fixture
def server() -> Generator[tuple[str, list[str]], None, None]:
    """A local server that counts the requests it gets; returns (its address, the methods it saw)."""
    seen: list[str] = []
    handler = type("Handler", (_Counting,), {"seen": seen})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/x", seen
    httpd.shutdown()
    httpd.server_close()


MOCK = {"enabled": True, "outcome": "pass", "output": "created #77", "data": {"id": 77}}


def _set_mock(api: TestClient, action: dict[str, Any], node: dict[str, Any], mock: Any) -> Any:
    return api.patch(f"{graph_url(action)}/nodes/{node['id']}", json={"mock": mock})


def _comment_node(api: TestClient, action: dict[str, Any]) -> dict[str, Any]:
    nodes = api.get(graph_url(action)).json()["nodes"]
    return next(n for n in nodes if n["name"] == "Comment")


def test_a_mock_stands_in_for_a_node_that_writes_and_a_later_node_can_read_it(
    api: TestClient,
) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    action = _comment_then_read(api, "${(Comment).output} / ${(Comment).data.id}")
    _use(api, pipeline, action)
    assert _set_mock(api, action, _comment_node(api, action), MOCK).status_code == 200
    _dry(api, pipeline, task)
    run = wait_for_run(api, task, "done")
    (comment,) = _steps(run, "artifact")
    assert comment["output"] == "created #77"
    assert comment["data"] == {"id": 77, "mock": True}
    assert "dry_run" not in comment["data"], "it is a mock, not a skip"
    assert api.get(f"/api/tasks/{task['id']}/comments").json() == []
    (say,) = _steps(run, "set")
    assert say["outcome"] == "pass"


def test_a_mock_that_fails_leaves_by_on_fail_and_stops_the_run(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    action = _comment_then_read(api, "${(Comment).output}")
    _use(api, pipeline, action)
    failing = {**MOCK, "outcome": "fail", "reason": "the service said no"}
    _set_mock(api, action, _comment_node(api, action), failing)
    _dry(api, pipeline, task)
    run = wait_for_run(api, task, "failed")
    (comment,) = _steps(run, "artifact")
    assert comment["outcome"] == "fail"
    assert "the service said no" in comment["reason"]
    assert comment["data"]["mock"] is True


def test_a_switched_off_mock_changes_nothing(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    action = _comment_then_read(api, "${(Comment).success}")
    _use(api, pipeline, action)
    _set_mock(api, action, _comment_node(api, action), {**MOCK, "enabled": False})
    _dry(api, pipeline, task)
    (comment,) = _steps(wait_for_run(api, task, "done"), "artifact")
    assert comment["data"]["dry_run"] is True, "skipped as before"
    assert "mock" not in comment["data"]


def test_a_mocked_http_node_sends_nothing(api: TestClient, server: tuple[str, list[str]]) -> None:
    address, seen = server
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    action = _definition(api, "http", method="GET", url=address)  # a read: it would run for real
    _use(api, pipeline, action)
    assert _set_mock(api, action, action["node"], MOCK).status_code == 200
    _dry(api, pipeline, task)
    (step,) = _steps(wait_for_run(api, task, "done"), "http")
    assert step["output"] == "created #77"
    assert seen == [], "the mock ran instead of the call"


def test_a_real_run_ignores_the_mock(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    action = _definition(api, "artifact", operation="Add comment", text="Hello")
    _use(api, pipeline, action)
    _set_mock(api, action, action["node"], MOCK)
    _start(api, pipeline, task)
    run = wait_for_run(api, task, "done")
    (step,) = _steps(run, "artifact")
    assert "mock" not in (step["data"] or {})
    assert [c["body"] for c in api.get(f"/api/tasks/{task['id']}/comments").json()] == ["Hello"]


def test_a_dry_run_of_the_published_version_has_no_mocks(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    action = _definition(api, "code", language="sh", code="echo real", read_only=True)
    _use(api, pipeline, action)
    assert api.post(f"{graph_url(action)}/publish").status_code in (200, 201)
    _set_mock(api, action, action["node"], MOCK)
    _dry(api, pipeline, task, version="published")
    (published,) = _steps(wait_for_run(api, task, "done"), "code")
    assert published["output"].strip() == "real"
    other = make_task(api)
    _dry(api, pipeline, other)  # the draft
    (draft,) = _steps(wait_for_run(api, other, "done"), "code")
    assert draft["output"] == "created #77"


def test_a_mock_is_not_published_and_does_not_make_the_draft_changed(api: TestClient) -> None:
    action = _definition(api, "code", language="sh", code="echo hi", read_only=True)
    published = api.post(f"{graph_url(action)}/publish")
    assert published.status_code in (200, 201), published.text
    _set_mock(api, action, action["node"], MOCK)
    listed = next(g for g in api.get("/api/actions").json() if g["id"] == action["id"])
    assert listed["draft_changed"] is False
    version = api.get(f"{graph_url(action)}/versions/1").json()
    assert "created #77" not in json.dumps(version)
    assert "mock" not in json.dumps(version).replace("mocks", "")


def test_the_check_before_publishing_says_that_mocks_stay_behind(api: TestClient) -> None:
    action = _definition(api, "code", language="sh", code="echo hi", read_only=True)
    _set_mock(api, action, action["node"], MOCK)
    check = api.get(f"{graph_url(action)}/check").json()
    (finding,) = [f for f in check["findings"] if f["code"] == "mocks_not_published"]
    assert finding["level"] == "warning"
    assert "1 mock(s) are set in this draft" in finding["message"]


def test_the_mock_is_in_the_node_and_can_be_removed(api: TestClient) -> None:
    action = _definition(api, "code", language="sh", code="echo hi", read_only=True)
    shown = _set_mock(api, action, action["node"], MOCK).json()
    assert shown["mock"] == {**MOCK, "reason": ""}
    gone = _set_mock(api, action, action["node"], None).json()
    assert gone["mock"] is None


def test_what_a_mock_may_not_hold(api: TestClient) -> None:
    action = _definition(api, "code", language="sh", code="echo hi", read_only=True)
    node = action["node"]
    assert api.put("/api/secrets/MOCK_KEY", json={"value": "s3cr3t-value-123"}).status_code < 300
    cases = [
        ({**MOCK, "output": "key ${secret:MOCK_KEY}"}, "must not name a secret"),
        ({**MOCK, "output": "see s3cr3t-value-123"}, "must not hold the value of a secret"),
        ({**MOCK, "data": {"k": "s3cr3t-value-123"}}, "must not hold the value of a secret"),
        ({**MOCK, "outcome": "maybe"}, "'pass' or 'fail'"),
        ({**MOCK, "data": [1]}, "JSON object"),
        ({**MOCK, "other": 1}, "has no field 'other'"),
        ({**MOCK, "output": "x" * 70000}, "at most 64 KiB"),
    ]
    for mock, message in cases:
        response = _set_mock(api, action, node, mock)
        assert response.status_code == 422, mock
        assert message in response.text


def test_a_trigger_and_an_if_take_no_mock(api: TestClient) -> None:
    action = _definition(api, "code", language="sh", code="echo hi", read_only=True)
    trigger = next(n for n in api.get(graph_url(action)).json()["nodes"] if n["kind"] == "trigger")
    response = _set_mock(api, action, trigger, MOCK)
    assert response.status_code == 422
    assert "takes no mock" in response.text


def test_the_text_of_a_mock_is_never_read_for_references(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    action = _comment_then_read(api, "${(Comment).output}")
    _use(api, pipeline, action)
    _set_mock(api, action, _comment_node(api, action), {**MOCK, "output": "${(Missing).output}"})
    _dry(api, pipeline, task)
    run = wait_for_run(api, task, "done")
    assert _steps(run, "artifact")[0]["output"] == "${(Missing).output}"


def test_the_test_cases_of_a_trigger(api: TestClient) -> None:
    action = _definition(api, "code", language="sh", code="echo hi", read_only=True)
    trigger = next(n for n in api.get(graph_url(action)).json()["nodes"] if n["kind"] == "trigger")
    url = f"{graph_url(action)}/nodes/{trigger['id']}"
    good = [{"name": "Big order", "inputs": {"amount": "5000"}}]
    assert api.patch(url, json={"cases": good}).json()["cases"] == good
    for bad, message in (
        ([{"name": "A"}, {"name": "A"}], "two test cases named 'A'"),
        ([{"name": ""}], "needs a name"),
        ([{"name": "A", "inputs": {"x": 1}}], "text values"),
        ([{"name": "A", "inputs": {"x": "${secret:K}"}}], "must not name a secret"),
        ([{"name": f"c{i}"} for i in range(21)], "At most 20"),
    ):
        response = api.patch(url, json={"cases": bad})
        assert response.status_code == 422, bad
        assert message in response.text
    other = api.patch(f"{graph_url(action)}/nodes/{action['node']['id']}", json={"cases": good})
    assert other.status_code == 422
    assert "Only a Trigger holds test cases" in other.text
    assert api.patch(url, json={"cases": None}).json()["cases"] is None


def test_the_last_result_is_the_newest_real_one_and_never_a_dry_step(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    action = _definition(api, "code", language="sh", code="echo first", read_only=True)
    _use(api, pipeline, action)
    url = f"{graph_url(action)}/nodes/{action['node']['id']}/last-result"
    assert api.get(url).json() == {
        "found": False,
        "outcome": "pass",
        "output": "",
        "reason": "",
        "data": {},
    }
    _start(api, pipeline, task)
    wait_for_run(api, task, "done")
    again = make_task(api)
    _dry(api, pipeline, again)
    wait_for_run(api, again, "done")
    found = api.get(url).json()
    assert found["found"] is True
    assert found["output"].strip() == "first"
    assert "mock" not in found["data"] and "dry_run" not in found["data"]


def test_the_database_holds_the_mock_in_the_config_of_the_node(
    api: TestClient, migrated_settings: Any
) -> None:
    """No migration: the mock is a key of the node's JSON config."""
    action = _definition(api, "code", language="sh", code="echo hi", read_only=True)
    _set_mock(api, action, action["node"], MOCK)
    path = str(migrated_settings.database_url).split("///")[-1]
    row = (
        sqlite3.connect(path)
        .execute("select config from graph_nodes where id = ?", (action["node"]["id"],))
        .fetchone()
    )
    assert json.loads(row[0])["_mock"]["output"] == "created #77"


def test_a_mock_saved_while_the_secret_store_fails_is_checked_for_references_and_says_so_in_the_log(
    api: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The check for secret values in a mock needs the secret store; when it fails, the mock is still saved after the
    weaker check of the reference form, and the log says that the values were not checked (instead of hiding it)."""
    action = _definition(api, "code", language="sh", code="echo hi", read_only=True)

    async def broken() -> list[Any]:
        raise RuntimeError("store unreadable")

    monkeypatch.setattr(api.app.state.secret_store, "names", broken)  # type: ignore[attr-defined]
    with caplog.at_level("WARNING", logger="openartifact.api.graphs"):
        assert _set_mock(api, action, action["node"], MOCK).status_code == 200
        refused = _set_mock(api, action, action["node"], {**MOCK, "output": "${secret:K}"})
    assert refused.status_code == 422 and "must not name a secret" in refused.text
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any(
        "store unreadable" in m and "secret references only, not for secret values" in m
        for m in warnings
    ), warnings
