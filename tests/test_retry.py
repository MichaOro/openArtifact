"""Retry on fail (ADR-073): the setting and its bounds, and runs through the engine that fail a few times first."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.graph.node_types import (
    NODE_TYPES,
    RETRY_MAX_TOTAL_WAIT_MS,
    SettingError,
    node_type,
    retry_error,
)
from openartifact.models import NodeKind
from tests.helpers import alembic_config
from tests.helpers import build_pipeline as _pipeline
from tests.helpers import graph_url as _url
from tests.helpers import make_task as _make_task
from tests.helpers import run_of as _run
from tests.helpers import wait_for_run as _wait
from tests.test_execution_nodes import _definition, _start, _use

ON = {"enabled": True, "max_tries": 3, "wait_ms": 0}


def _counting(path: Path, passes_on: int) -> str:
    """A shell script that counts its runs in ``path`` and succeeds from the ``passes_on``-th on."""
    return f"n=$(cat {path} 2>/dev/null || echo 0); n=$((n+1)); echo $n > {path}; echo try $n; [ $n -ge {passes_on} ]"


def _steps(run: dict[str, Any], kind: str = "code") -> list[dict[str, Any]]:
    return [s for s in run["node_results"] if s["kind"] == kind]


def _context(client: TestClient, task: dict[str, Any]) -> dict[str, Any]:
    execution = _run(client, task)["execution_id"]
    return client.get(f"/api/tasks/{task['id']}/executions/{execution}/context").json()  # type: ignore[no-any-return]


# ── the setting ───────────────────────────────────────────────────────


def test_the_kinds_that_run_something_offer_it_and_the_others_do_not() -> None:
    offering = {k.value for k, t in NODE_TYPES.items() if any(s.key == "retry" for s in t.settings)}
    assert offering == {
        "code",
        "http",
        "agent",
        "postgres",
        "sqlite",
        "github",
        "artifact",
        "action",
    }
    # a timer waits, If and Switch and Edit Fields only look at the context: trying them again gives the same answer
    for kind in ("timer", "if", "switch", "set", "trigger", "output", "stage"):
        with pytest.raises(SettingError, match="has no setting 'retry'"):
            node_type(NodeKind(kind)).merge_config({}, {"retry": ON})


def test_it_is_optional_and_stored_whole_with_the_defaults_filled_in() -> None:
    code = node_type(NodeKind.CODE)
    setting = next(s for s in code.settings if s.key == "retry")
    assert (setting.level, setting.section, setting.default) == ("optional", "behaviour", None)
    assert setting.describe()["limits"]["max_tries"] == [2, 10, 3]
    assert (
        code.effective_config({}).get("retry") is None
    )  # a node that never asked for it does not retry
    stored = code.merge_config({}, {"retry": {"enabled": True}})["retry"]
    assert stored == {"enabled": True, "max_tries": 3, "wait_ms": 1000}


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("yes", "must be an object"),
        ({"enabled": "yes"}, "enabled must be true or false"),
        ({"max_tries": 1}, "Max. tries must be a whole number from 2 to 10"),
        ({"max_tries": 11}, "Max. tries must be a whole number from 2 to 10"),
        ({"max_tries": 2.5}, "Max. tries must be a whole number"),
        ({"max_tries": True}, "Max. tries must be a whole number"),
        ({"wait_ms": -1}, "wait between tries must be from 0 to 10 minutes"),
        ({"wait_ms": 600001}, "wait between tries must be from 0 to 10 minutes"),
        ({"wait_ms": "5"}, "wait between tries must be from 0 to 10 minutes"),
        ({"foo": 1}, "has no 'foo'"),
        (
            {"max_tries": 10, "wait_ms": 300000},
            "wait 45 minutes in all, more than the 30 minutes allowed",
        ),
    ],
)
def test_a_value_that_does_not_fit_is_refused_in_plain_words(value: Any, message: str) -> None:
    assert retry_error(value) is not None
    with pytest.raises(SettingError, match=message):
        node_type(NodeKind.HTTP).merge_config({}, {"retry": value})


def test_the_bounds_themselves_are_allowed() -> None:
    http = node_type(NodeKind.HTTP)
    assert retry_error({"max_tries": 2, "wait_ms": 0}) is None
    assert retry_error({"max_tries": 10, "wait_ms": 0}) is None
    assert retry_error({"max_tries": 4, "wait_ms": RETRY_MAX_TOTAL_WAIT_MS // 3}) is None
    http.merge_config({}, {"retry": {"enabled": False, "max_tries": 10, "wait_ms": 600000 // 20}})


def test_the_api_refuses_a_bad_value_and_keeps_a_good_one(client: TestClient) -> None:
    action = _definition(client, "code", code="true")
    url = f"{_url(action)}/nodes/{action['node']['id']}"
    bad = client.patch(url, json={"config": {"retry": {"max_tries": 99}}})
    assert bad.status_code == 422 and "Max. tries must be a whole number from 2 to 10" in bad.text
    good = client.patch(
        url, json={"config": {"retry": {"enabled": True, "max_tries": 4, "wait_ms": 250}}}
    )
    assert good.status_code == 200 and good.json()["config"]["retry"] == {
        "enabled": True,
        "max_tries": 4,
        "wait_ms": 250,
    }
    assert (
        client.patch(url, json={"config": {"retry": None}}).json()["config"]["retry"] is None
    )  # the bin: not set


# ── runs ──────────────────────────────────────────────────────────────


def test_a_node_that_fails_twice_and_passes_on_the_third_try_passes(
    client: TestClient, tmp_path: Path
) -> None:
    counter = tmp_path / "count"
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code=_counting(counter, 3), retry=ON))
    _start(client, pipeline, task)
    run = _wait(client, task, "done")
    (step,) = _steps(run)
    assert (step["outcome"], step["attempts"], step["exit_code"], step["output"]) == (
        "pass",
        3,
        0,
        "try 3\n",
    )
    assert counter.read_text().strip() == "3"
    entry = _context(client, task)["nodes"]["Execute_Command"]
    assert (entry["success"], entry["attempts"]) == (True, 3)


def test_the_failed_tries_are_in_the_step_with_their_reasons(
    client: TestClient, tmp_path: Path
) -> None:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(client, pipeline, _definition(client, "code", code=_counting(tmp_path / "c", 3), retry=ON))
    _start(client, pipeline, task)
    run = _wait(client, task, "done")
    execution = _run(client, task)["execution_id"]
    step = client.get(
        f"/api/tasks/{task['id']}/executions/{execution}/steps/{_steps(run)[0]['id']}"
    ).json()
    assert [t["try"] for t in step["detail"]["tries"]] == [1, 2]
    assert [t["reason"] for t in step["detail"]["tries"]] == ["Exit code 1", "Exit code 1"]
    assert all(isinstance(t["duration_ms"], int) for t in step["detail"]["tries"])


def test_a_node_that_always_fails_stops_after_max_tries_and_leaves_by_on_fail(
    client: TestClient, tmp_path: Path
) -> None:
    counter = tmp_path / "count"
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(
        client,
        pipeline,
        _definition(client, "code", code=_counting(counter, 99), retry={**ON, "max_tries": 2}),
    )
    _start(client, pipeline, task)
    run = _wait(client, task, "failed")
    (step,) = _steps(run)
    assert (step["outcome"], step["port"], step["attempts"], step["reason"]) == (
        "fail",
        "fail",
        2,
        "Exit code 1",
    )
    assert counter.read_text().strip() == "2"  # tried exactly max_tries times, not one more
    assert _context(client, task)["nodes"]["Execute_Command"]["success"] is False


def test_a_node_without_the_setting_or_with_it_off_is_tried_once(
    client: TestClient, tmp_path: Path
) -> None:
    for name, config in (("plain", {}), ("off", {"retry": {**ON, "enabled": False}})):
        counter = tmp_path / name
        pipeline, task = _pipeline(client, stages=1), _make_task(client)
        _use(client, pipeline, _definition(client, "code", code=_counting(counter, 99), **config))
        _start(client, pipeline, task)
        run = _wait(client, task, "failed")
        assert (_steps(run)[0]["attempts"], counter.read_text().strip()) == (1, "1"), name


def test_continue_comes_after_the_last_try(client: TestClient, tmp_path: Path) -> None:
    counter = tmp_path / "count"
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(
        client,
        pipeline,
        _definition(client, "code", code=_counting(counter, 99), retry=ON, on_failure="continue"),
    )
    _start(client, pipeline, task)
    run = _wait(
        client, task, "done"
    )  # the failure was let through On Pass, but only after three tries
    step = _steps(run)[0]
    assert (step["outcome"], step["port"], step["attempts"]) == ("fail", "pass", 3)
    assert counter.read_text().strip() == "3"


def test_the_wait_between_tries_is_kept_and_a_stop_ends_it_at_once(
    client: TestClient, tmp_path: Path
) -> None:
    counter = tmp_path / "count"
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    _use(
        client,
        pipeline,
        _definition(
            client,
            "code",
            code=_counting(counter, 99),
            retry={"enabled": True, "max_tries": 3, "wait_ms": 120000},
        ),
    )
    _start(client, pipeline, task)
    deadline = time.monotonic() + 10
    while not counter.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.5)  # the first try failed and the node waits two minutes for the second
    started = time.monotonic()
    stopped = client.post(f"/api/tasks/{task['id']}/run/stop")
    assert stopped.status_code == 200 and stopped.json()["status"] == "stopped"
    assert time.monotonic() - started < 5  # not after the wait
    assert counter.read_text().strip() == "1"  # and no second try after a stop
    assert _steps(_run(client, task)) == []  # a stopped node records no step


def test_an_action_that_fails_is_run_again_with_all_its_nodes(
    client: TestClient, tmp_path: Path
) -> None:
    counter = tmp_path / "count"
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    shell = _use(client, pipeline, _definition(client, "code", code=_counting(counter, 2)))
    response = client.patch(f"{_url(pipeline)}/nodes/{shell['id']}", json={"config": {"retry": ON}})
    assert response.status_code == 200, response.text
    _start(client, pipeline, task)
    run = _wait(client, task, "done")
    assert [s["outcome"] for s in _steps(run)] == [
        "fail",
        "pass",
    ]  # the definition ran twice, each run has its steps
    assert counter.read_text().strip() == "2"


def test_an_action_that_fails_every_time_says_how_often_it_was_tried(
    client: TestClient, tmp_path: Path
) -> None:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    shell = _use(client, pipeline, _definition(client, "code", code=_counting(tmp_path / "c", 99)))
    client.patch(
        f"{_url(pipeline)}/nodes/{shell['id']}", json={"config": {"retry": {**ON, "max_tries": 2}}}
    )
    _start(client, pipeline, task)
    run = _wait(client, task, "failed")
    assert "(after 2 tries)" in run["note"]


# ── migration 0059 ────────────────────────────────────────────────────


def test_migration_0059_gives_every_step_one_attempt_and_goes_down_again(
    at_revision: Callable[[str], Path],
) -> None:
    path = at_revision("0058")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, status, position, number) VALUES ('t1', 'T', 'done', 0, 1)"
        )
        conn.execute(
            "INSERT INTO pipeline_runs (id, task_id, status, started_by, snapshot) VALUES ('r1', 't1', 'done', 'user', '{}')"
        )
        conn.execute(
            "INSERT INTO run_node_results (id, run_id, seq, node_id, kind, outcome, started_at, finished_at) "
            "VALUES ('s1', 'r1', 1, 'n1', 'code', 'pass', '2026-11-26 10:00:00', '2026-11-26 10:00:01')"
        )
    command.upgrade(alembic_config(), "0059")
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT attempts FROM run_node_results WHERE id = 's1'").fetchone() == (
            1,
        )
    command.downgrade(alembic_config(), "0058")
    with sqlite3.connect(path) as conn:
        assert "attempts" not in [r[1] for r in conn.execute("PRAGMA table_info(run_node_results)")]
        assert conn.execute("SELECT outcome FROM run_node_results WHERE id = 's1'").fetchone() == (
            "pass",
        )
