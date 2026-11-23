"""Code and HTTP nodes: registry, settings, connection rules and runs through the engine."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient

from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.graph.node_types import NODE_TYPES, node_type
from openartifact.models import GraphKind, NodeKind
from tests.helpers import build_pipeline as _pipeline
from tests.helpers import connect as _connect
from tests.helpers import graph_url as _url
from tests.helpers import make_task as _make_task
from tests.helpers import node as _node
from tests.helpers import post as _post
from tests.helpers import run_of as _run
from tests.helpers import wait_for_run as _wait
from tests.test_engine import _call

Make = Callable[..., "TestClient"]


@pytest.fixture
def make_client(migrated_settings: Settings) -> Generator[Make, None, None]:
    """A client whose settings can be changed (code nodes off, private networks on ...)."""
    stack: list[Any] = []

    def make(**overrides: Any) -> TestClient:
        settings = migrated_settings.model_copy(update=overrides)
        client = TestClient(_create_app(settings))
        client.__enter__()
        stack.append(client)
        return client

    yield make
    for client in stack:
        client.__exit__(None, None, None)


def _definition(client: TestClient, kind: str, **config: Any) -> dict[str, Any]:
    """An action definition: trigger -> node -> Output (On Pass and On Fail)."""
    action = _post(client, "/api/actions", name=f"Do {kind}")
    nodes = client.get(_url(action)).json()["nodes"]
    trigger = next(n for n in nodes if n["kind"] == "trigger")
    output = next(n for n in nodes if n["kind"] == "output")
    client.patch(f"{_url(action)}/nodes/{output['id']}", json={"fail_enabled": True})
    node = _node(client, action, kind, config=config)
    _connect(client, action, trigger, "out", node, "in")
    _connect(client, action, node, "pass", output, "pass")
    _connect(client, action, node, "fail", output, "fail")
    action["node"] = node
    action["output"] = output
    return action


def _use(client: TestClient, pipeline: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    """Link the first stage's action to the definition and return its node."""
    shell: dict[str, Any] = pipeline["stages"][0][1]
    response = client.patch(
        f"{_url(pipeline)}/nodes/{shell['id']}", json={"definition_id": action["id"]}
    )
    assert response.status_code == 200, response.text
    return shell


def _fail_to_error(client: TestClient, pipeline: dict[str, Any]) -> None:
    """Route the first action's Error output to the stage end, so a failed action does not fail the run."""
    stage, action = pipeline["stages"][0]
    _connect(client, pipeline, action, "error", stage, "end")


def _start(client: TestClient, pipeline: dict[str, Any], task: dict[str, Any]) -> None:
    _post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])


def _work(run: dict[str, Any]) -> list[dict[str, Any]]:
    """The steps of Code and HTTP nodes of a run read."""
    return [r for r in run["node_results"] if r["kind"] in ("code", "http")]


def _wait_for_file(path: Path) -> str:
    for _ in range(200):
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        time.sleep(0.05)
    raise AssertionError(f"{path} did not appear")


# ── registry and settings ────────────────────────────────────────────


def test_the_registry_describes_both_kinds_for_the_editor(client: TestClient) -> None:
    described = {t["kind"]: t for t in client.get("/api/node-types").json()}
    for kind in ("code", "http"):
        entry = described[kind]
        assert entry["scopes"] == ["action"]
        assert entry["chain"] is True and entry["fixed"] is False
        assert [(p["name"], p["label"]) for p in entry["inputs"]] == [("in", "Input")]
        assert [(p["name"], p["label"]) for p in entry["outputs"]] == [
            ("pass", "On Pass"),
            ("fail", "On Fail"),
        ]
    code = {s["key"]: s for s in described["code"]["settings"]}
    assert code["language"]["type"] == "select"
    assert code["language"]["options"] == ["sh", "python"]
    assert (code["language"]["default"], code["code"]["type"]) == ("sh", "code")
    assert code["code"]["max_length"] == 20000
    assert (code["timeout_seconds"]["minimum"], code["timeout_seconds"]["maximum"]) == (1, 600)
    http = {s["key"]: s for s in described["http"]["settings"]}
    assert http["method"]["options"] == ["GET", "POST", "PUT", "PATCH", "DELETE"]
    assert (http["headers"]["type"], http["body"]["type"], http["url"]["type"]) == (
        "lines",
        "lines",
        "text",
    )
    assert http["success_status"]["default"] == "200-299"
    assert all(s["stored_in"] == "config" for s in code.values())


def test_the_old_settings_keep_their_shape(client: TestClient) -> None:
    described = {t["kind"]: t for t in client.get("/api/node-types").json()}
    assert described["timer"]["settings"] == [
        {
            "key": "seconds",
            "label": "Seconds",
            "type": "integer",
            "minimum": 1,
            "maximum": 86400,
            "default": 5,
            "stored_in": "column",
        }
    ]
    assert described["output"]["settings"][0]["type"] == "switch"


def test_the_menu_offers_the_execution_kinds_the_editor_can_draw() -> None:
    assert NODE_TYPES[NodeKind.CODE].addable is True
    assert NODE_TYPES[NodeKind.HTTP].addable is True
    assert NODE_TYPES[NodeKind.TIMER].addable is True


def test_a_new_node_has_the_defaults_and_stores_what_was_set(client: TestClient) -> None:
    action = _post(client, "/api/actions", name="A")
    plain = _node(client, action, "code")
    assert plain["config"] == {
        "language": "sh",
        "code": "",
        "secrets": "",
        "sets_variables": "",
        "timeout_seconds": 30,
        "on_failure": "fail",
    }
    node = _node(client, action, "http", config={"url": "https://example.org", "method": "POST"})
    assert node["config"]["method"] == "POST"
    assert node["config"]["success_status"] == "200-299"
    timer = _node(client, action, "timer")
    assert timer["config"] == {} and timer["seconds"] == 5


def test_config_is_merged_per_key_and_null_resets_a_key(client: TestClient) -> None:
    action = _post(client, "/api/actions", name="A")
    node = _node(client, action, "code", config={"code": "echo 1", "timeout_seconds": 5})
    url = f"{_url(action)}/nodes/{node['id']}"
    config = client.patch(url, json={"config": {"language": "python"}}).json()["config"]
    assert config == {
        "language": "python",
        "code": "echo 1",
        "secrets": "",
        "sets_variables": "",
        "timeout_seconds": 5,
        "on_failure": "fail",
    }
    config = client.patch(url, json={"config": {"timeout_seconds": None}}).json()["config"]
    assert config["timeout_seconds"] == 30 and config["code"] == "echo 1"
    assert client.patch(url, json={"name": "Renamed"}).json()["config"]["code"] == "echo 1"


@pytest.mark.parametrize(
    "bad",
    [
        {"nope": 1},
        {"language": "ruby"},
        {"timeout_seconds": 0},
        {"timeout_seconds": 601},
        {"timeout_seconds": "30"},
        {"timeout_seconds": True},
        {"code": 5},
        {"code": "x" * 20001},
        {"code": "a\x00b"},
    ],
)
def test_invalid_settings_are_refused_without_echoing_the_code(
    client: TestClient, bad: dict[str, Any]
) -> None:
    action = _post(client, "/api/actions", name="A")
    node = _node(client, action, "code")
    response = client.patch(f"{_url(action)}/nodes/{node['id']}", json={"config": bad})
    assert response.status_code == 422
    assert "x" * 50 not in response.text
    created = client.post(f"{_url(action)}/nodes", json={"kind": "code", "config": bad})
    assert created.status_code == 422


@pytest.mark.parametrize(
    "bad",
    [
        {"url": "a\nb"},
        {"url": "u" * 2001},
        {"method": "TRACE"},
        {"timeout_seconds": 121},
        {"success_status": "2xx"},
        {"success_status": "299-200"},
        {"success_status": "99"},
    ],
)
def test_invalid_http_settings_are_refused(client: TestClient, bad: dict[str, Any]) -> None:
    action = _post(client, "/api/actions", name="A")
    node = _node(client, action, "http")
    response = client.patch(f"{_url(action)}/nodes/{node['id']}", json={"config": bad})
    assert response.status_code == 422


def test_other_kinds_take_no_config_and_the_kinds_stay_in_their_scope(client: TestClient) -> None:
    action = _post(client, "/api/actions", name="A")
    timer = _node(client, action, "timer")
    response = client.patch(f"{_url(action)}/nodes/{timer['id']}", json={"config": {"code": "x"}})
    assert response.status_code == 422
    pipeline = _post(client, "/api/pipelines", name="P")
    assert client.post(f"{_url(pipeline)}/nodes", json={"kind": "code"}).status_code == 422
    assert client.post(f"{_url(pipeline)}/nodes", json={"kind": "http"}).status_code == 422


def test_the_settings_of_a_kind_are_never_mixed_with_columns() -> None:
    for kind in (NodeKind.CODE, NodeKind.HTTP):
        assert node_type(kind).scopes == {GraphKind.ACTION}
        assert {s.stored_in for s in node_type(kind).settings} == {"config"}


# ── connection rules ─────────────────────────────────────────────────


def test_connection_rules_follow_the_timer_and_the_output(client: TestClient) -> None:
    action = _definition(client, "code", code="echo")
    nodes = {n["id"]: n for n in client.get(_url(action)).json()["nodes"]}
    code, output = action["node"], action["output"]
    timer = _node(client, action, "timer")
    http = _node(client, action, "http")

    def edge(a: dict[str, Any], ap: str, b: dict[str, Any], bp: str) -> int:
        return client.post(
            f"{_url(action)}/edges",
            json={"source_id": a["id"], "source_port": ap, "target_id": b["id"], "target_port": bp},
        ).status_code

    assert edge(code, "pass", http, "in") == 201
    assert edge(http, "fail", timer, "in") == 201
    assert edge(timer, "out", code, "in") == 201
    assert edge(code, "out", output, "pass") == 422  # no such output
    assert edge(code, "pass", code, "in") == 422  # not to itself
    assert edge(output, "pass", code, "in") == 422
    assert nodes  # sanity


def test_the_fail_input_needs_the_fail_switch_on_the_output(client: TestClient) -> None:
    action = _post(client, "/api/actions", name="A")
    output = next(n for n in client.get(_url(action)).json()["nodes"] if n["kind"] == "output")
    node = _node(client, action, "http")
    response = client.post(
        f"{_url(action)}/edges",
        json={
            "source_id": node["id"],
            "source_port": "fail",
            "target_id": output["id"],
            "target_port": "fail",
        },
    )
    assert response.status_code == 422


# ── runs ─────────────────────────────────────────────────────────────


def test_an_action_runs_code_and_leaves_by_on_pass_and_the_result_is_stored(
    client: TestClient,
) -> None:
    pipeline, task = _pipeline(client, stages=1), None
    task = _make_task(client)
    _use(client, pipeline, _definition(client, "code", code="echo hello; echo warn >&2"))
    _start(client, pipeline, task)
    run = _wait(client, task, "done")
    (result,) = _work(run)
    assert (result["kind"], result["outcome"], result["exit_code"]) == ("code", "pass", 0)
    assert result["output"] == "hello\n[stderr]\nwarn\n"
    assert result["output_truncated"] is False and result["reason"] is None
    assert result["started_at"].endswith("Z") and result["finished_at"].endswith("Z")
    assert result["stage_id"] == pipeline["stages"][0][0]["id"]
    assert result["action_id"] == pipeline["stages"][0][1]["id"]
    full = client.get(f"/api/runs/{task['id']}/results").json()
    assert result["id"] in [f["id"] for f in full]
    assert client.get("/api/runs/unknown/results").status_code == 404


def test_failing_code_leaves_by_on_fail_and_the_run_fails_without_an_error_route(
    client: TestClient,
) -> None:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code="echo broken; exit 4"))
    _start(client, pipeline, task)
    run = _wait(client, task, "failed")
    assert _work(run)[0]["exit_code"] == 4
    assert _work(run)[0]["reason"] == "Exit code 4"


def test_on_fail_can_be_routed_on_and_the_run_continues(client: TestClient) -> None:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code="exit 1"))
    _fail_to_error(client, pipeline)
    _start(client, pipeline, task)
    assert _work(_wait(client, task, "done"))[0]["outcome"] == "fail"


def test_a_node_set_to_continue_fails_open_and_its_step_still_shows_the_failure(
    client: TestClient,
) -> None:
    """`on_failure: continue` leaves by On Pass although the code failed; nothing else changes."""
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(
        client,
        pipeline,
        _definition(client, "code", code="echo broken; exit 4", on_failure="continue"),
    )
    _start(client, pipeline, task)
    run = _wait(client, task, "done")  # no error route is needed: the action passed
    step = _work(run)[0]
    assert (step["outcome"], step["port"], step["exit_code"]) == ("fail", "pass", 4)
    assert step["reason"] == "Exit code 4 (continued through On Pass)"
    assert [r["kind"] for r in run["node_results"]][-1] == "output"
    assert run["node_results"][-1]["outcome"] == "pass"  # the definition reached its On Pass output


def test_a_node_that_passes_is_not_changed_by_the_fail_open_setting(client: TestClient) -> None:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code="echo fine", on_failure="continue"))
    _start(client, pipeline, task)
    step = _work(_wait(client, task, "done"))[0]
    assert (step["outcome"], step["port"], step["reason"]) == ("pass", "pass", None)


def test_the_default_is_to_fail_and_only_two_values_are_accepted(client: TestClient) -> None:
    action = _post(client, "/api/actions", name="Defaults")
    node = _node(client, action, "code")
    assert node["config"]["on_failure"] == "fail"
    patch = f"{_url(action)}/nodes/{node['id']}"
    assert client.patch(patch, json={"config": {"on_failure": "continue"}}).status_code == 200
    assert client.patch(patch, json={"config": {"on_failure": "ignore"}}).status_code == 422
    kinds = {t["kind"]: t for t in client.get("/api/node-types").json()}
    for kind in ("code", "http"):
        setting = next(x for x in kinds[kind]["settings"] if x["key"] == "on_failure")
        assert (setting["type"], setting["default"], setting["options"]) == (
            "select",
            "fail",
            ["fail", "continue"],
        )


def test_a_code_node_on_a_dead_end_counts_as_fail(client: TestClient) -> None:
    action = _post(client, "/api/actions", name="Dead end")
    nodes = client.get(_url(action)).json()["nodes"]
    trigger = next(n for n in nodes if n["kind"] == "trigger")
    node = _node(client, action, "code", config={"code": "echo hi"})
    _connect(client, action, trigger, "out", node, "in")  # no output connected
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, action)
    _start(client, pipeline, task)
    _wait(client, task, "failed")


def test_an_empty_code_node_fails_with_a_clear_reason(client: TestClient) -> None:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code"))
    _start(client, pipeline, task)
    run = _wait(client, task, "failed")
    assert _work(run)[0]["reason"] == "The code is empty"


def test_the_protocol_fails_a_zero_exit_and_keeps_data(client: TestClient) -> None:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    code = 'echo \'{"ok": false, "reason": "not today", "data": {"n": 1}}\''
    _use(client, pipeline, _definition(client, "code", code=code))
    _start(client, pipeline, task)
    result = _work(_wait(client, task, "failed"))[0]
    assert (result["exit_code"], result["reason"], result["data"]) == (0, "not today", {"n": 1})


def test_code_nodes_can_be_switched_off(make_client: Make) -> None:
    client = make_client(code_nodes_enabled=False)
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code="echo hi"))
    _start(client, pipeline, task)
    run = _wait(client, task, "failed")
    assert _work(run)[0]["reason"] == "Code nodes are disabled"


def test_code_nodes_fail_in_open_mode_by_default(make_client: Make) -> None:
    client = make_client(code_nodes_without_token=False)
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code="echo hi"))
    _start(client, pipeline, task)
    step = _work(_wait(client, task, "failed"))[0]
    assert step["reason"] == (
        "Code nodes need OPENARTIFACT_API_TOKEN: the application is open without it"
    )


def test_the_output_limit_is_a_setting(make_client: Make) -> None:
    client = make_client(code_output_limit_bytes=50)
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code="echo " + "z" * 500))
    _start(client, pipeline, task)
    output = _work(_wait(client, task, "done"))[0]["output"]
    assert output.endswith("[output truncated]") and len(output) < 100


def test_stopping_the_run_kills_the_process_of_the_node(client: TestClient, tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(
        client,
        pipeline,
        _definition(client, "code", code=f"sleep 300 &\necho $! > {pidfile}\nwait"),
    )
    _start(client, pipeline, task)
    pid = int(_wait_for_file(pidfile))
    stopped = _post(client, f"/api/tasks/{task['id']}/run/stop")
    assert stopped["status"] == "stopped"
    for _ in range(100):
        try:
            os.kill(pid, 0)
            if "Z" in Path(f"/proc/{pid}/stat").read_text().split()[2]:
                break
        except (ProcessLookupError, FileNotFoundError):
            break
        time.sleep(0.05)
    else:
        raise AssertionError("the child of the stopped run is still alive")
    assert _work(_run(client, task)) == []


def test_a_timeout_ends_the_run_with_the_reason(client: TestClient) -> None:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code="sleep 60", timeout_seconds=1))
    _start(client, pipeline, task)
    run = _wait(client, task, "failed")
    assert _work(run)[0]["reason"] == "Timeout after 1 s"


def test_a_running_pipeline_is_not_changed_by_later_edits(
    client: TestClient, tmp_path: Path
) -> None:
    started = tmp_path / "started"
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    action = _definition(
        client, "code", code=f"echo go > {started}\nsleep 1\necho old", timeout_seconds=20
    )
    _use(client, pipeline, action)
    _start(client, pipeline, task)
    _wait_for_file(started)
    node_url = f"{_url(action)}/nodes/{action['node']['id']}"
    assert client.patch(node_url, json={"config": {"code": "echo new"}}).status_code == 200
    run = _wait(client, task, "done")
    assert _work(run)[0]["output"].strip() == "old"
    row = (
        sqlite3.connect(  # the frozen snapshot holds the config of the node
            str(
                Path(os.environ["OPENARTIFACT_DATA_DIR"])
                / os.environ["OPENARTIFACT_DATABASE_FILENAME"]
            )
        )
        .execute("SELECT snapshot FROM pipeline_runs")
        .fetchone()
    )
    frozen = json.loads(row[0])["definitions"][action["id"]]["nodes"]
    assert any(n["config"].get("code", "").endswith("echo old") for n in frozen)


def test_starting_again_replaces_the_results(client: TestClient) -> None:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code="echo again"))
    _start(client, pipeline, task)
    first = _work(_wait(client, task, "done"))[0]["id"]
    _start(client, pipeline, task)
    run = _wait(client, task, "done")
    for _ in range(100):
        run = _run(client, task)
        if run["status"] == "done" and _work(run):
            break
        time.sleep(0.05)
    assert [r["id"] for r in _work(run)] != [first]
    assert len(_work(run)) == 1


def test_the_results_are_part_of_the_published_run_and_of_the_integration_api(
    make_client: Make,
) -> None:
    client = make_client(api_token="t" * 40, secret_key="s" * 40)
    headers = {"Authorization": "Bearer " + "t" * 40}
    client.headers.update(headers)
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code="echo via-api"))
    _start(client, pipeline, task)
    _wait(client, task, "done")
    run = client.get(f"/api/v1/artifacts/{task['id']}/run").json()
    assert _work(run)[0]["output"] == "via-api\n"


def test_long_outputs_are_previewed_in_the_run_and_complete_in_the_list(
    client: TestClient,
) -> None:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code="python3 -c \"print('q' * 30000)\""))
    _start(client, pipeline, task)
    run = _wait(client, task, "done")
    shown = _work(run)[0]
    assert shown["output_truncated"] is True and len(shown["output"]) == 4096
    full = client.get(f"/api/runs/{task['id']}/results").json()[1]
    assert len(full["output"]) > 30000


def test_the_outputs_of_one_run_are_bounded_oldest_first(client: TestClient) -> None:
    from openartifact.engine import runner

    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    action = _definition(client, "code", code="python3 -c \"print('q' * 100)\"")
    _use(client, pipeline, action)
    original = runner.RUN_OUTPUT_LIMIT_CHARS
    runner.RUN_OUTPUT_LIMIT_CHARS = 250
    try:
        # three outputs of ~100 characters do not fit in 250: the two oldest are replaced by a note
        second = _node(client, action, "code", config={"code": "python3 -c \"print('r' * 100)\""})
        third = _node(client, action, "code", config={"code": "python3 -c \"print('s' * 100)\""})
        _connect(client, action, action["node"], "pass", second, "in")
        _connect(client, action, second, "pass", third, "in")
        _connect(client, action, third, "pass", action["output"], "pass")
        _start(client, pipeline, task)
        results = _work(_wait(client, task, "done"))
    finally:
        runner.RUN_OUTPUT_LIMIT_CHARS = original
    assert [r["output"][:1] for r in results] == ["[", "[", "s"]


def test_a_run_removed_with_its_artifact_takes_its_results(
    client: TestClient, tmp_path: Path
) -> None:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code="echo x"))
    _start(client, pipeline, task)
    _wait(client, task, "done")
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert client.get("/api/runs").json() == []


# ── the steps of a run ───────────────────────────────────────────────


def _steps(client: TestClient, task: dict[str, Any]) -> list[dict[str, Any]]:
    return client.get(f"/api/runs/{task['id']}/results").json()  # type: ignore[no-any-return]


def test_every_node_of_the_definition_is_a_step_in_order_with_its_position(
    client: TestClient,
) -> None:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    action = _definition(client, "code", code="echo hi")
    shell = _use(client, pipeline, action)
    _start(client, pipeline, task)
    _wait(client, task, "done")
    steps = _steps(client, task)
    assert [s["seq"] for s in steps] == [1, 2, 3]
    assert [(s["kind"], s["outcome"], s["port"]) for s in steps] == [
        ("trigger", "pass", "out"),
        ("code", "pass", "pass"),
        ("output", "pass", None),
    ]
    stage = pipeline["stages"][0][0]
    for step in steps:
        assert (step["pipeline_id"], step["depth"], step["top_stage_id"]) == (
            pipeline["id"],
            0,
            stage["id"],
        )
        assert (step["stage_id"], step["action_id"]) == (stage["id"], shell["id"])
        assert step["definition_id"] == action["id"]
        assert step["started_at"].endswith("Z") and step["finished_at"].endswith("Z")
    assert steps[0]["output"] == "" and steps[0]["exit_code"] is None
    assert steps[1]["output"] == "hi\n" and steps[1]["exit_code"] == 0
    assert steps[1]["node_id"] == action["node"]["id"]


def test_the_fail_path_is_recorded_with_its_ports(client: TestClient) -> None:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code="exit 1"))
    _fail_to_error(client, pipeline)
    _start(client, pipeline, task)
    _wait(client, task, "done")
    assert [(s["kind"], s["outcome"], s["port"]) for s in _steps(client, task)] == [
        ("trigger", "pass", "out"),
        ("code", "fail", "fail"),
        ("output", "fail", None),
    ]


def test_a_branch_is_visible_in_the_steps(client: TestClient) -> None:
    """code fails -> a second node on the fail branch; the pass branch is never visited."""
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    action = _definition(client, "code", code="exit 1")
    fallback = _node(client, action, "code", config={"code": "echo fallback"})
    _connect(client, action, action["node"], "fail", fallback, "in")
    _connect(client, action, fallback, "pass", action["output"], "pass")
    _use(client, pipeline, action)
    _start(client, pipeline, task)
    _wait(client, task, "done")
    steps = _steps(client, task)
    assert [s["node_id"] for s in steps] == [
        steps[0]["node_id"],
        action["node"]["id"],
        fallback["id"],
        action["output"]["id"],
    ]
    assert [s["port"] for s in steps] == ["out", "fail", "pass", None]
    assert [s["seq"] for s in steps] == [1, 2, 3, 4]


def test_a_timer_is_a_step_and_leaves_by_out(client: TestClient) -> None:
    action = _post(client, "/api/actions", name="Timed")
    nodes = client.get(_url(action)).json()["nodes"]
    trigger = next(n for n in nodes if n["kind"] == "trigger")
    output = next(n for n in nodes if n["kind"] == "output")
    timer = _node(client, action, "timer", seconds=1)
    _connect(client, action, trigger, "out", timer, "in")
    _connect(client, action, timer, "out", output, "pass")
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, action)
    _start(client, pipeline, task)
    _wait(client, task, "done")
    steps = _steps(client, task)
    assert [(s["kind"], s["port"]) for s in steps] == [
        ("trigger", "out"),
        ("timer", "out"),
        ("output", None),
    ]
    assert steps[1]["output"] == "" and steps[1]["exit_code"] is None


def test_steps_in_a_called_pipeline_say_which_pipeline_they_belong_to(client: TestClient) -> None:
    outer, inner = _pipeline(client, stages=1), _pipeline(client, stages=1)
    _call(client, outer, inner)
    action = _definition(client, "code", code="echo inner")
    _use(client, inner, action)
    task = _make_task(client)
    _post(client, f"/api/tasks/{task['id']}/run", pipeline_id=outer["id"])
    _wait(client, task, "done")
    steps = _steps(client, task)
    assert {s["pipeline_id"] for s in steps} == {inner["id"]}
    assert {s["depth"] for s in steps} == {1}
    call_entry = client.get(f"{_url(outer)}/stages").json()[1]["id"]
    assert {s["top_stage_id"] for s in steps} == {call_entry}
    assert {s["stage_id"] for s in steps} == {inner["stages"][0][0]["id"]}


def test_a_run_read_carries_only_the_newest_steps_and_the_list_has_all(
    make_client: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openartifact.engine import runner

    monkeypatch.setattr(runner, "RUN_READ_RESULTS", 2)
    client = make_client(api_token="t" * 40, secret_key="s" * 40)
    client.headers.update({"Authorization": "Bearer " + "t" * 40})
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code="echo hi"))
    _start(client, pipeline, task)
    run = _wait(client, task, "done")
    assert [r["kind"] for r in run["node_results"]] == ["code", "output"]
    assert run["node_results_truncated"] is True
    assert len(_steps(client, task)) == 3
    assert len(client.get(f"/api/v1/artifacts/{task['id']}/run/results").json()) == 3
    assert client.get("/api/v1/artifacts/nope/run/results").status_code == 404


def test_the_steps_start_again_with_the_next_start(client: TestClient) -> None:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code="echo hi"))
    _start(client, pipeline, task)
    _wait(client, task, "done")
    _start(client, pipeline, task)
    for _ in range(100):
        steps = _steps(client, task)
        if len(steps) == 3 and _run(client, task)["status"] == "done":
            break
        time.sleep(0.05)
    assert [s["seq"] for s in steps] == [1, 2, 3]


# ── HTTP through the engine ──────────────────────────────────────────


@contextmanager
def _local_server() -> Generator[int, None, None]:
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200 if self.path == "/ok" else 500)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"hi")

        def log_message(self, *args: Any) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_an_http_node_passes_on_an_accepted_status(make_client: Make) -> None:
    client = make_client(http_allow_private_networks=True)
    with _local_server() as port:
        pipeline, task = _pipeline(client, stages=1), _make_task(client)
        _use(client, pipeline, _definition(client, "http", url=f"http://127.0.0.1:{port}/ok"))
        _start(client, pipeline, task)
        run = _wait(client, task, "done")
    result = _work(run)[0]
    assert (result["kind"], result["outcome"], result["output"]) == ("http", "pass", "hi")
    assert result["data"]["status"] == 200


def test_an_http_node_refuses_the_local_network_by_default(client: TestClient) -> None:
    with _local_server() as port:
        pipeline, task = _pipeline(client, stages=1), _make_task(client)
        _use(client, pipeline, _definition(client, "http", url=f"http://127.0.0.1:{port}/ok"))
        _start(client, pipeline, task)
        run = _wait(client, task, "failed")
    assert "not allowed" in _work(run)[0]["reason"]


def test_an_http_node_without_url_fails_clearly(client: TestClient) -> None:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "http"))
    _start(client, pipeline, task)
    assert _work(_wait(client, task, "failed"))[0]["reason"] == "The URL is empty"


# ── migration ────────────────────────────────────────────────────────


def _config(settings: Settings) -> Config:
    from tests.helpers import alembic_config

    return alembic_config()


def test_migration_0021_goes_up_down_and_up_with_the_data_kept(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    path = settings.data_dir / settings.database_filename
    cfg = _config(settings)
    command.upgrade(cfg, "0020")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO graphs (id, name, status, kind, slug, created_at, updated_at) "
            "VALUES ('g1', 'A', 'draft', 'action', 'a', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO graph_nodes (id, graph_id, kind, name, x, y, fail_enabled, seconds, "
            "created_at, updated_at) VALUES ('n1', 'g1', 'timer', 'T', 1, 2, 0, 7, "
            "'2026-01-01', '2026-01-01')"
        )
    command.upgrade(cfg, "head")
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT seconds, config FROM graph_nodes WHERE id='n1'").fetchone() == (
            7,
            "{}",
        )
        conn.execute(
            "INSERT INTO graph_nodes (id, graph_id, kind, name, x, y, config, created_at, "
            "updated_at) VALUES ('n2', 'g1', 'code', 'C', 0, 0, '{\"code\": \"echo\"}', "
            "'2026-01-01', '2026-01-01')"
        )
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "run_node_results" in tables
    command.downgrade(cfg, "0020")
    with sqlite3.connect(path) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(graph_nodes)")}
        assert "config" not in columns
        assert conn.execute("SELECT id, seconds FROM graph_nodes").fetchall() == [("n1", 7)]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "run_node_results" not in tables
        with pytest.raises(
            sqlite3.IntegrityError, match=r"CHECK constraint failed: ck_graph_nodes_kind"
        ):
            conn.execute(
                "INSERT INTO graph_nodes (id, graph_id, kind, name, x, y, created_at, updated_at) "
                "VALUES ('n3', 'g1', 'code', 'C', 0, 0, '2026-01-01', '2026-01-01')"
            )
    command.upgrade(cfg, "head")
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT id, seconds, config FROM graph_nodes").fetchall() == [
            ("n1", 7, "{}")
        ]
    command.check(cfg)
