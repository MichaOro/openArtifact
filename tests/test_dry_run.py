"""The dry run (ADR-086): a run under real conditions that skips everything that writes, and says what it would have done."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Callable, Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.agents.tools import Tool, Toolbox
from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.engine import guard_views
from tests.helpers import (
    alembic_config,
    build_pipeline,
    connect,
    graph_url,
    kind_of,
    link,
    make_task,
    node,
    post,
    slow_pipeline,
    wait_for_run,
)
from tests.test_action_contract import _declare, _greeting_action
from tests.test_execution_nodes import _definition, _start, _use
from tests.test_mcp import _call as mcp_call
from tests.test_stop_switch import _offer, _stop

TOKEN = "dry-token-" + "x" * 30
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(
        update={"api_token": TOKEN, "secret_key": "k" * 40, "http_allow_private_networks": True}
    )
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def _dry(
    client: TestClient, pipeline: dict[str, Any], task: dict[str, Any], **body: Any
) -> dict[str, Any]:
    response = client.post(
        f"/api/tasks/{task['id']}/run",
        json={"pipeline_id": pipeline["id"], "dry_run": True, **body},
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def _steps(run: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [r for r in run["node_results"] if r["kind"] == kind]


class _Counting(BaseHTTPRequestHandler):
    seen: ClassVar[list[str]] = []

    def _answer(self) -> None:
        type(self).seen.append(self.command)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    do_GET = do_POST = _answer  # noqa: N815

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def server() -> Generator[tuple[str, list[str]], None, None]:
    """A local server that counts the requests it gets; returns (its address, the methods it saw)."""
    seen: list[str] = []
    handler = type("Handler", (_Counting,), {"seen": seen})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}/x", seen
    httpd.shutdown()
    httpd.server_close()


# ── what writes is skipped, and the step says so ─────────────────────


def test_a_dry_run_adds_no_comment_and_says_what_it_would_have_added(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    _use(
        api,
        pipeline,
        _definition(api, "artifact", operation="Add comment", text="Hello from the run"),
    )
    started = _dry(api, pipeline, task)
    assert started["dry_run"] is True
    run = wait_for_run(api, task, "done")
    (step,) = _steps(run, "artifact")
    assert step["outcome"] == "pass"
    assert (
        step["reason"]
        == "Dry run: would have added this comment to the artifact: Hello from the run"
    )
    assert step["data"] == {
        "dry_run": True,
        "would_have": "added this comment to the artifact: Hello from the run",
    }
    assert api.get(f"/api/tasks/{task['id']}/comments").json() == [], "nothing was written"
    assert run["dry_run"] is True


def test_a_real_run_of_the_same_action_does_add_the_comment(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    _use(api, pipeline, _definition(api, "artifact", operation="Add comment", text="Hello"))
    _start(api, pipeline, task)
    run = wait_for_run(api, task, "done")
    assert run["dry_run"] is False
    assert [c["body"] for c in api.get(f"/api/tasks/{task['id']}/comments").json()] == ["Hello"]


def test_an_http_post_is_skipped_and_a_get_is_sent(
    api: TestClient, server: tuple[str, list[str]]
) -> None:
    address, seen = server
    for method in ("POST", "GET"):
        pipeline, task = build_pipeline(api, stages=1), make_task(api)
        _use(api, pipeline, _definition(api, "http", method=method, url=address))
        _dry(api, pipeline, task)
        run = wait_for_run(api, task, "done")
        (step,) = _steps(run, "http")
        if method == "POST":
            assert step["reason"] == f"Dry run: would have sent POST {address}"
            assert step["data"]["dry_run"] is True
        else:
            assert step["data"].get("dry_run") is None, "a read runs for real"
    assert seen == ["GET"], "the server got the read and nothing of the write"


def test_execute_command_is_skipped_unless_it_is_marked_read_only(
    api: TestClient, tmp_path: Path
) -> None:
    skipped, ran = tmp_path / "skipped.txt", tmp_path / "ran.txt"
    for target, extra in ((skipped, {}), (ran, {"read_only": True})):
        pipeline, task = build_pipeline(api, stages=1), make_task(api)
        _use(
            api,
            pipeline,
            _definition(api, "code", language="sh", code=f"echo hi > {target}", **extra),
        )
        _dry(api, pipeline, task)
        run = wait_for_run(api, task, "done")
        (step,) = _steps(run, "code")
        if extra:
            assert step["data"] is None or step["data"].get("dry_run") is None
        else:
            assert step["reason"] == "Dry run: would have run the sh script of 1 line(s)"
    assert not skipped.exists(), "a script counts as a change: it was not run"
    assert ran.read_text().strip() == "hi", "marked read only, it ran"


def test_a_timer_does_not_wait_and_the_step_says_how_long_it_would_have(api: TestClient) -> None:
    pipeline, task = slow_pipeline(api, seconds=30), make_task(api)
    began = time.monotonic()
    _dry(api, pipeline, task)
    run = wait_for_run(api, task, "done", timeout=8)
    assert time.monotonic() - began < 8, "30 seconds of waiting were skipped"
    (step,) = _steps(run, "timer")
    assert step["data"]["skipped_seconds"] == 30
    assert step["reason"] == "Dry run: would have waited 30 s"


# ── what a skipped node leaves, and what asks for it ─────────────────


def _comment_then_read(api: TestClient, read: str) -> dict[str, Any]:
    """trigger -> Artifact 'Comment' (Add comment) -> Edit Fields 'Say' (reads the comment's result) -> output."""
    action = post(api, "/api/actions", name="Comment then read")
    trigger, output = kind_of(api, action, "trigger"), kind_of(api, action, "output")
    for edge in api.get(graph_url(action)).json()["edges"]:
        api.delete(f"{graph_url(action)}/edges/{edge['id']}")
    comment = node(
        api, action, "artifact", name="Comment", config={"operation": "Add comment", "text": "hi"}
    )
    say = node(api, action, "set", name="Say", config={"fields": f"seen = {read}"})
    connect(api, action, trigger, "out", comment, "in")
    connect(api, action, comment, "pass", say, "in")
    connect(api, action, say, "pass", output, "pass")
    return action


def test_a_node_that_needs_the_result_of_a_skipped_one_fails_and_names_it(
    api: TestClient,
) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    _use(api, pipeline, _comment_then_read(api, "${(Comment).output}"))
    _dry(api, pipeline, task)
    run = wait_for_run(api, task, "failed")
    (say,) = _steps(run, "set")
    assert say["outcome"] == "fail"
    assert 'node "Comment" was skipped in the dry run, so it has no result' in say["reason"]
    assert "use mock data for it" in say["reason"]


def test_what_a_skipped_node_does_leave_can_still_be_read(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    _use(api, pipeline, _comment_then_read(api, "${(Comment).success}"))
    _dry(api, pipeline, task)
    run = wait_for_run(api, task, "done")
    assert _steps(run, "set")[0]["outcome"] == "pass"


def test_the_inputs_of_a_skipped_node_are_checked_before_it_is_skipped(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    _use(
        api,
        pipeline,
        _definition(api, "artifact", operation="Add comment", text="${var.never_set}"),
    )
    _dry(api, pipeline, task)
    run = wait_for_run(api, task, "failed")
    (step,) = _steps(run, "artifact")
    assert step["outcome"] == "fail" and "never_set" in step["reason"]


# ── what a dry run is given ──────────────────────────────────────────


def test_inputs_for_the_entry_action_are_checked_like_a_mapping(api: TestClient) -> None:
    from tests.test_action_contract import INPUTS

    definition = _greeting_action(api, inputs=INPUTS)
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    link(api, pipeline, pipeline["stages"][0][1], definition)
    action_id = pipeline["stages"][0][1]["id"]
    stage_id = pipeline["stages"][0][0]["id"]

    def attempt(inputs: dict[str, Any]) -> Any:
        return api.post(
            f"/api/tasks/{task['id']}/run",
            json={
                "pipeline_id": pipeline["id"],
                "stage_id": stage_id,
                "action_id": action_id,
                "dry_run": True,
                "inputs": inputs,
            },
        )

    refused = attempt({})
    assert refused.status_code == 422 and "input 'who' is required" in refused.json()["detail"]
    refused = attempt({"who": "Ann", "oops": 1})
    assert refused.status_code == 422 and "there is no input 'oops'" in refused.json()["detail"]
    refused = attempt({"who": "Ann", "times": "many"})
    assert refused.status_code == 422 and "'times' must be a number" in refused.json()["detail"]
    assert api.get("/api/runs").json() == [], "a refused start leaves nothing behind"
    assert attempt({"who": "Ann", "times": 3}).status_code == 201
    run = wait_for_run(api, task, "done")
    execution = api.get(f"/api/tasks/{task['id']}/executions/{run['execution_id']}").json()
    context = json.loads(json.dumps(execution["context"]))
    assert "Hello Ann x3" in json.dumps(context), "the given values reached the action"


def test_a_value_is_never_read_for_references(api: TestClient) -> None:
    from tests.test_action_contract import INPUTS

    definition = _greeting_action(api, inputs=INPUTS)
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    link(api, pipeline, pipeline["stages"][0][1], definition)
    response = api.post(
        f"/api/tasks/{task['id']}/run",
        json={
            "pipeline_id": pipeline["id"],
            "action_id": pipeline["stages"][0][1]["id"],
            "stage_id": pipeline["stages"][0][0]["id"],
            "dry_run": True,
            "inputs": {"who": "${secret:TOKEN}"},
        },
    )
    assert response.status_code == 201, response.text
    run = wait_for_run(api, task, "done")
    execution = api.get(f"/api/tasks/{task['id']}/executions/{run['execution_id']}").json()
    assert "${secret:TOKEN}" in json.dumps(execution["context"]), "taken as text, not resolved"


def test_inputs_for_the_pipeline_become_the_inputs_of_the_run(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    _declare(api, pipeline, [{"name": "who", "type": "text", "required": True}], None)
    definition = post(api, "/api/actions", name="Plain")
    trigger, output = kind_of(api, definition, "trigger"), kind_of(api, definition, "output")
    for edge in api.get(graph_url(definition)).json()["edges"]:
        api.delete(f"{graph_url(definition)}/edges/{edge['id']}")
    say = node(api, definition, "set", name="Say", config={"fields": "hi = Hi ${input.who}"})
    connect(api, definition, trigger, "out", say, "in")
    connect(api, definition, say, "pass", output, "pass")
    link(api, pipeline, pipeline["stages"][0][1], definition)
    refused = api.post(
        f"/api/tasks/{task['id']}/run",
        json={"pipeline_id": pipeline["id"], "dry_run": True, "inputs": {}},
    )
    assert refused.status_code == 422 and "input 'who' is required" in refused.json()["detail"]
    _dry(api, pipeline, task, inputs={"who": "Bo"})
    run = wait_for_run(api, task, "done")
    execution = api.get(f"/api/tasks/{task['id']}/executions/{run['execution_id']}").json()
    assert "Hi Bo" in json.dumps(execution["context"])


def test_inputs_and_version_are_for_a_dry_run_only(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    bodies: tuple[dict[str, Any], ...] = ({"inputs": {}}, {"version": "draft"})
    for body in bodies:
        response = api.post(
            f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"], **body}
        )
        assert response.status_code == 422
        assert "inputs and version are for a dry run" in response.json()["detail"]


# ── the version a dry run tests ──────────────────────────────────────


def test_a_dry_run_tests_the_draft_unless_it_asks_for_the_published_version(
    api: TestClient,
) -> None:
    definition = _definition(api, "code", language="sh", code="echo one", read_only=True)
    pipeline = build_pipeline(api, stages=1)
    _use(api, pipeline, definition)
    assert api.post(f"{graph_url(definition)}/publish").status_code in (200, 201)
    code_node = definition["node"]
    api.patch(
        f"{graph_url(definition)}/nodes/{code_node['id']}", json={"config": {"code": "echo two"}}
    )
    outputs: dict[str, str] = {}
    for label, body in (("draft", {}), ("published", {"version": "published"})):
        task = make_task(api)
        _dry(api, pipeline, task, **body)
        run = wait_for_run(api, task, "done")
        outputs[label] = _steps(run, "code")[0]["output"].strip()
    assert outputs == {"draft": "two", "published": "one"}


def test_through_the_integration_api_a_dry_run_defaults_to_the_published_version(
    api: TestClient,
) -> None:
    definition = _definition(api, "code", language="sh", code="echo one", read_only=True)
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    _use(api, pipeline, definition)
    api.post(f"{graph_url(definition)}/publish")
    api.patch(
        f"{graph_url(definition)}/nodes/{definition['node']['id']}",
        json={"config": {"code": "echo two"}},
    )
    response = api.post(
        f"/api/v1/artifacts/{task['number']}/run",
        json={"pipeline_id": pipeline["id"], "dry_run": True},
    )
    assert response.status_code == 201, response.text
    run = wait_for_run(api, task, "done")
    assert _steps(run, "code")[0]["output"].strip() == "one"


# ── the artifact stays as it is ──────────────────────────────────────


def test_a_dry_run_leaves_the_target_of_the_artifact_as_it_was(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    assert api.get(f"/api/tasks/{task['id']}").json()["pipeline_id"] is None
    _dry(api, pipeline, task)
    wait_for_run(api, task, "done")
    after = api.get(f"/api/tasks/{task['id']}").json()
    assert (after["pipeline_id"], after["stage_id"], after["action_id"]) == (None, None, None)
    _start(api, pipeline, task)
    wait_for_run(api, task, "done")
    assert api.get(f"/api/tasks/{task['id']}").json()["pipeline_id"] == pipeline["id"]


# ── the emergency stop, the history and the counters ─────────────────


def test_the_emergency_stop_refuses_a_dry_run_like_any_start(api: TestClient) -> None:
    _offer(api)
    _stop(api, True)
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    response = api.post(
        f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"], "dry_run": True}
    )
    assert response.status_code == 409 and response.json()["code"] == "stopped"


def test_the_list_flags_a_dry_run_filters_it_and_leaves_it_out_of_the_real_counters(
    api: TestClient,
) -> None:
    pipeline = build_pipeline(api, stages=1)
    _use(api, pipeline, _comment_then_read(api, "${(Comment).output}"))
    failing = make_task(api, "Dry and failing")
    _dry(api, pipeline, failing)
    wait_for_run(api, failing, "failed")
    plain = make_task(api, "Real and done")
    pipeline_ok = build_pipeline(api, stages=1)
    _use(api, pipeline_ok, _comment_then_read(api, "${(Comment).success}"))
    _start(api, pipeline_ok, plain)
    wait_for_run(api, plain, "done")

    everything = api.get("/api/executions").json()
    flags = {i["task"]["title"]: i["dry_run"] for i in everything["items"]}
    assert flags == {"Dry and failing": True, "Real and done": False}
    only = api.get("/api/executions", params={"dry_run": "only"}).json()
    assert [i["task"]["title"] for i in only["items"]] == ["Dry and failing"]
    real = api.get("/api/executions", params={"dry_run": "exclude"}).json()
    assert [i["task"]["title"] for i in real["items"]] == ["Real and done"]
    summary = everything["summary"]
    assert summary["failed_24h"] == 0, "a dry run is no failure of a pipeline"
    assert summary["done_24h"] == 1 and summary["total"] == 2
    assert api.get("/api/executions", params={"dry_run": "maybe"}).status_code == 422


def test_the_guard_views_say_which_executions_are_dry_runs(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    _dry(api, pipeline, task)
    wait_for_run(api, task, "done")
    from openartifact.engine.guard_views import VIEWS

    assert "dry_run" in VIEWS["v_guard_runs"]
    settings = api.app.state.settings  # type: ignore[attr-defined]
    db = Path(settings.data_dir) / settings.database_filename
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT dry_run FROM v_guard_runs").fetchall() == [(1,)]


# ── the tools of an agent ────────────────────────────────────────────


def _toolbox(*tools: Tool, dry_run: bool) -> Toolbox:
    return Toolbox(list(tools), dry_run=dry_run)


async def test_a_tool_that_changes_something_is_not_run_in_a_dry_run_and_the_model_is_told() -> (
    None
):
    ran: list[str] = []

    async def read(arguments: dict[str, Any]) -> str:
        ran.append("read")
        return "rows"

    async def write(arguments: dict[str, Any]) -> str:
        ran.append("write")
        return "changed"

    box = _toolbox(
        Tool("look", "reads", {"type": "object"}, read, writes=False),
        Tool("change", "changes", {"type": "object"}, write, writes=True),
        dry_run=True,
    )
    looked = await box.call("1", "look", "{}")
    changed = await box.call("2", "change", "{}")
    assert (looked.result, looked.error) == ("rows", False)
    assert changed.result.startswith("Dry run: change was not executed, it changes something")
    assert changed.error is False, "the model goes on, it is not a failure"
    assert ran == ["read"]


async def test_the_same_tool_runs_in_a_real_run() -> None:
    async def write(arguments: dict[str, Any]) -> str:
        return "changed"

    box = _toolbox(Tool("change", "changes", {"type": "object"}, write, writes=True), dry_run=False)
    assert (await box.call("1", "change", "{}")).result == "changed"


def test_the_tools_of_an_agent_are_classified_by_their_settings() -> None:
    from openartifact.agents.local_tools import build_http_tool, build_postgres_tool
    from openartifact.agents.tools import ToolContext

    context = ToolContext({"DB": "postgresql://u@h/d"}, False)

    def http(method: str) -> Tool:
        return build_http_tool(
            {"tool_name": "t", "config": {"method": method, "url": "https://example.org/x"}},
            context,
        )

    assert http("GET").writes is False and http("POST").writes is True
    pg: dict[str, Any] = {"tool_name": "t", "config": {"secret": "DB", "query": "select 1"}}
    assert build_postgres_tool(pg, context).writes is False
    pg["config"]["allow_write"] = True
    assert build_postgres_tool(pg, context).writes is True


def test_the_writing_tools_of_the_openartifact_tool_are_marked_as_changing() -> None:
    from openartifact.agents.board_toolbox import board_tools
    from openartifact.api.board_tool_names import BOARD_TOOLS, WRITE_TOOLS

    class Board:
        def __getattr__(self, name: str) -> Callable[..., Any]:
            async def call(*args: Any, **kwargs: Any) -> Any:
                return None

            call.__name__ = name
            return call

    found, _ = board_tools(
        {"config": {"allow_write": True}, "node_id": "n"},
        Board(),
        prefix="p",
        label="Board",
    )
    marked = {t.name: t.writes for t in found}
    assert set(marked) == set(BOARD_TOOLS)
    assert {name for name, writes in marked.items() if writes} == set(WRITE_TOOLS)


# ── the MCP tool and the migration ───────────────────────────────────


def test_the_mcp_tool_starts_a_dry_run(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    _use(api, pipeline, _definition(api, "artifact", operation="Add comment", text="Hello"))
    failed, result = mcp_call(
        api,
        "start_processing",
        artifact=str(task["number"]),
        pipeline=pipeline["id"],
        dry_run=True,
    )
    assert not failed, result
    assert result["dry_run"] is True
    wait_for_run(api, task, "done")
    assert api.get(f"/api/tasks/{task['id']}/comments").json() == []


def test_migration_0066_survives_the_empty_copy_a_failed_start_left_behind(
    at_revision: Callable[[str], Path],
) -> None:
    path = at_revision("0065")
    guard_views.install(path)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE _alembic_tmp_executions (id VARCHAR(36) NOT NULL PRIMARY KEY)")
    command.upgrade(alembic_config(), "0066")
    with sqlite3.connect(path) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert "_alembic_tmp_executions" not in names
        assert "dry_run" in [r[1] for r in conn.execute("PRAGMA table_info(executions)")]
    command.upgrade(alembic_config(), "head")


def test_migration_0066_marks_every_row_that_exists_as_a_real_run_and_goes_down_again(
    at_revision: Callable[[str], Path],
) -> None:
    path = at_revision("0065")
    guard_views.install(
        path
    )  # a running installation has them: they stand on the table the migration rebuilds
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, status, position, number) VALUES ('t1', 'T', 'done', 1, 1)"
        )
        conn.execute(
            "INSERT INTO pipeline_runs (id, task_id, status, started_by, snapshot) "
            "VALUES ('r1', 't1', 'done', 'user', '{}')"
        )
        conn.execute(
            "INSERT INTO executions (id, task_id, number, pipeline_name, status, started_by, step_count, created_at, started_at) "
            "VALUES ('e1', 't1', 1, 'P', 'done', 'user', 0, '2026-11-26 10:00:00', '2026-11-26 10:00:00')"
        )
    command.upgrade(alembic_config(), "0066")
    guard_views.install(path)  # the next start makes the views again, now with the new column
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT dry_run FROM v_guard_runs").fetchall() == [(0,)]
        assert conn.execute("SELECT dry_run FROM pipeline_runs").fetchall() == [(0,)]
        assert conn.execute("SELECT dry_run FROM executions").fetchall() == [(0,)]
        conn.execute("UPDATE executions SET dry_run = 1")
    command.downgrade(alembic_config(), "0065")
    with sqlite3.connect(path) as conn:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(executions)")]
        assert "dry_run" not in columns
        assert conn.execute("SELECT id FROM executions").fetchall() == [("e1",)]
    command.upgrade(alembic_config(), "head")
