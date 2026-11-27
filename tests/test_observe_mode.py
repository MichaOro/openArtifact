"""The observe mode of a pipeline (ADR-088): a published setting makes every run of the pipeline a dry run nobody asked for by hand."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.engine import guard_views
from openartifact.graph import observe_state
from openartifact.graph.observe import ObserveError, clean_observe
from openartifact.graph.repository import GraphRepository
from openartifact.models import Graph
from tests.helpers import (
    alembic_config,
    build_pipeline,
    connect,
    db_session_context,
    graph_url,
    kind_of,
    make_task,
    node,
    post,
    wait_for_run,
)
from tests.test_dry_run import _comment_then_read
from tests.test_execution_nodes import _definition, _use

TOKEN = "observe-token-" + "x" * 30
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


# ── helpers ──────────────────────────────────────────────────────────


def _db(api: TestClient, work: Callable[[Any, Graph], Any], graph_id: str) -> Any:
    """Run ``work(session, graph)`` on the application's database (the way the API would, from a test's own loop) and commit."""
    settings: Settings = api.app.state.settings  # type: ignore[attr-defined]

    async def go() -> Any:
        async with db_session_context(settings) as session:
            graph = await session.get(Graph, graph_id)
            assert graph is not None
            return await work(session, graph)

    return asyncio.run(go())


def _set_draft(api: TestClient, pipeline: dict[str, Any], setting: dict[str, Any] | None) -> None:
    async def work(session: Any, graph: Graph) -> None:
        await GraphRepository(session).set_observe(graph, setting)

    _db(api, work, pipeline["id"])


def _publish(api: TestClient, pipeline: dict[str, Any]) -> None:
    response = api.post(f"/api/pipelines/{pipeline['id']}/publish", json={"acknowledge": True})
    assert response.status_code in (200, 201), response.text


def _status(api: TestClient, pipeline: dict[str, Any]) -> dict[str, Any]:
    async def work(session: Any, graph: Graph) -> dict[str, Any]:
        return observe_state.status_of(graph, await observe_state.published_setting(session, graph))

    return dict(_db(api, work, pipeline["id"]))


def _start(api: TestClient, pipeline: dict[str, Any], task: dict[str, Any], **body: Any) -> Any:
    return api.post(f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"], **body})


def _commenting(api: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    """A one-stage pipeline whose only action adds a comment to the card (what a real run does and an observed one skips)."""
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    _use(api, pipeline, _definition(api, "artifact", operation="Add comment", text="Hello"))
    return pipeline, task


def _comments(api: TestClient, task: dict[str, Any]) -> list[Any]:
    return list(api.get(f"/api/tasks/{task['id']}/comments").json())


def _observe_and_publish(api: TestClient, pipeline: dict[str, Any], **setting: Any) -> None:
    _set_draft(api, pipeline, {"enabled": True, **setting})
    _publish(api, pipeline)


# ── the setting ──────────────────────────────────────────────────────


def test_the_setting_is_validated() -> None:
    assert clean_observe({"enabled": True, "days": 7}) == {"enabled": True, "days": 7, "runs": None}
    for bad, why in (
        ({"enabled": True, "weeks": 1}, "no field 'weeks'"),
        ({"enabled": "yes"}, "true or false"),
        ({"enabled": True, "days": 0}, "between 1 and 365"),
        ({"enabled": True, "runs": -3}, "between 1 and 100000"),
        ({"enabled": True, "days": 1.5}, "whole number"),
        ("on", "an object"),
    ):
        with pytest.raises(ObserveError, match=why):
            clean_observe(bad)


# ── what an observed run is ──────────────────────────────────────────


def test_a_pipeline_published_with_the_mode_on_runs_every_start_as_an_observed_dry_run(
    api: TestClient,
) -> None:
    pipeline, task = _commenting(api)
    _observe_and_publish(api, pipeline)
    response = _start(api, pipeline, task)
    assert response.status_code == 201, response.text
    started = response.json()
    assert started["observed"] is True and started["dry_run"] is True
    run = wait_for_run(api, task, "done")
    assert run["observed"] is True and run["dry_run"] is True
    assert _comments(api, task) == [], "an observed run changes no card"
    (execution,) = api.get(f"/api/tasks/{task['id']}/executions").json()["items"]
    assert execution["observed"] is True and execution["dry_run"] is True
    assert execution["started_by"] == "user"
    (step,) = [r for r in run["node_results"] if r["kind"] == "artifact"]
    assert step["data"]["dry_run"] is True and "would_have" in step["data"]


def test_the_counters_of_real_runs_leave_an_observed_run_out(api: TestClient) -> None:
    pipeline, task = _commenting(api)
    _observe_and_publish(api, pipeline)
    _start(api, pipeline, task).raise_for_status()
    wait_for_run(api, task, "done")
    everything = api.get("/api/executions").json()
    (item,) = everything["items"]
    assert item["dry_run"] is True and item["observed"] is True
    summary = everything["summary"]
    assert summary["done_24h"] == 0 and summary["failed_24h"] == 0
    assert summary["total"] == 1


def test_a_run_of_a_pipeline_that_is_not_observed_is_a_real_run(api: TestClient) -> None:
    pipeline, task = _commenting(api)
    _publish(api, pipeline)
    started = _start(api, pipeline, task).json()
    assert started["observed"] is False and started["dry_run"] is False
    wait_for_run(api, task, "done")
    assert len(_comments(api, task)) == 1


def test_the_mode_applies_only_after_a_publication(api: TestClient) -> None:
    pipeline, task = _commenting(api)
    _publish(api, pipeline)  # a version without the mode
    _set_draft(api, pipeline, {"enabled": True})  # the draft says it, nobody published it
    assert _start(api, pipeline, task).json()["observed"] is False
    wait_for_run(api, task, "done")
    assert len(_comments(api, task)) == 1, "the published version has no mode: the run is real"
    _publish(api, pipeline)
    other = make_task(api, "Second")
    assert _start(api, pipeline, other).json()["observed"] is True


def test_a_pipeline_that_was_never_published_is_not_observed(api: TestClient) -> None:
    pipeline, task = _commenting(api)
    _set_draft(api, pipeline, {"enabled": True})
    assert _start(api, pipeline, task).json()["observed"] is False


def test_the_mode_is_frozen_into_the_snapshot_of_the_run(api: TestClient) -> None:
    pipeline, task = _commenting(api)
    _observe_and_publish(api, pipeline)
    _start(api, pipeline, task).raise_for_status()
    wait_for_run(api, task, "done")
    (item,) = api.get(f"/api/tasks/{task['id']}/executions").json()["items"]
    settings: Settings = api.app.state.settings  # type: ignore[attr-defined]
    with sqlite3.connect(settings.data_dir / settings.database_filename) as conn:
        (text,) = conn.execute(
            "SELECT snapshot FROM executions WHERE id = ?", (item["id"],)
        ).fetchone()
    assert json.loads(text)["observed"] is True


def test_switching_the_mode_off_in_a_later_version_makes_runs_real_again(api: TestClient) -> None:
    pipeline, task = _commenting(api)
    _observe_and_publish(api, pipeline)
    _set_draft(api, pipeline, {"enabled": False})
    assert _start(api, pipeline, task).json()["observed"] is True, "still the published mode"
    wait_for_run(api, task, "done")
    _publish(api, pipeline)
    again = make_task(api, "Again")
    assert _start(api, pipeline, again).json()["observed"] is False


def test_a_dry_run_started_by_hand_is_not_counted_and_not_marked_observed(
    api: TestClient,
) -> None:
    pipeline, task = _commenting(api)
    _observe_and_publish(api, pipeline, runs=1)
    manual = _start(api, pipeline, task, dry_run=True).json()
    assert manual["dry_run"] is True and manual["observed"] is False
    wait_for_run(api, task, "done")
    assert _status(api, pipeline)["runs_done"] == 0


def test_mocks_do_not_apply_to_an_observed_run(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    definition = _definition(api, "set", fields="seen = real")
    _use(api, pipeline, definition)
    api.patch(
        f"{graph_url(definition)}/nodes/{definition['node']['id']}",
        json={
            "mock": {
                "enabled": True,
                "outcome": "pass",
                "output": "mocked",
                "data": {"seen": "mock"},
            }
        },
    ).raise_for_status()
    _observe_and_publish(api, pipeline)
    _start(api, pipeline, task).raise_for_status()
    run = wait_for_run(api, task, "done")
    (step,) = [r for r in run["node_results"] if r["kind"] == "set"]
    assert not (step["data"] or {}).get("mock"), "the published version carries no mock"


def test_the_emergency_stop_still_refuses_an_observed_start(api: TestClient) -> None:
    from tests.test_stop_switch import _offer, _stop

    pipeline, task = _commenting(api)
    _observe_and_publish(api, pipeline)
    _offer(api)
    _stop(api, True)
    response = _start(api, pipeline, task)
    assert response.status_code == 409 and response.json()["code"] == "stopped"
    _stop(api, False)


# ── nested pipelines follow the outer one ────────────────────────────


def _nested(api: TestClient) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    inner, task = _commenting(api)[0], make_task(api)
    outer = post(api, "/api/pipelines", name="Outer")
    caller = node(api, outer, "pipeline", name="Call")
    connect(api, outer, kind_of(api, outer, "trigger"), "out", caller, "in")
    connect(api, outer, caller, "out", kind_of(api, outer, "complete"), "in")
    api.patch(
        f"{graph_url(outer)}/nodes/{caller['id']}", json={"definition_id": inner["id"]}
    ).raise_for_status()
    return outer, inner, task


def test_a_pipeline_called_by_an_observed_one_follows_it(api: TestClient) -> None:
    outer, inner, task = _nested(api)
    _publish(api, inner)
    _observe_and_publish(api, outer)
    started = _start(api, outer, task).json()
    assert started["observed"] is True
    wait_for_run(api, task, "done")
    assert _comments(api, task) == [], "what the called pipeline writes is skipped too"
    assert _status(api, inner)["runs_done"] == 0, "the called pipeline is not counted"


def test_a_pipeline_called_by_a_real_run_does_not_read_its_own_mode(api: TestClient) -> None:
    outer, inner, task = _nested(api)
    _observe_and_publish(api, inner)
    _publish(api, outer)
    started = _start(api, outer, task).json()
    assert started["observed"] is False
    wait_for_run(api, task, "done")
    assert len(_comments(api, task)) == 1
    assert _status(api, inner)["runs_done"] == 0


def test_a_call_of_a_pipeline_whose_observation_has_ended_fails_with_the_reason(
    api: TestClient,
) -> None:
    outer, inner, task = _nested(api)
    _observe_and_publish(api, inner, runs=1)
    other = make_task(api, "Counts")
    _start(api, inner, other).raise_for_status()  # its one observed run
    wait_for_run(api, other, "done")
    _publish(api, outer)
    _start(api, outer, task).raise_for_status()
    run = wait_for_run(api, task, "failed")
    assert "Observation of the pipeline" in run["note"] and "has ended" in run["note"]


# ── the end of an observation and the owner's decision ───────────────


def test_after_the_limit_of_runs_a_start_is_refused_with_the_reason(api: TestClient) -> None:
    pipeline, task = _commenting(api)
    _observe_and_publish(api, pipeline, runs=2)
    for number in (1, 2):
        item = make_task(api, f"Run {number}")
        assert _start(api, pipeline, item).status_code == 201
        wait_for_run(api, item, "done")
    status = _status(api, pipeline)
    assert status["ended"] is True and status["runs_done"] == 2 and status["observing"] is False
    refused = _start(api, pipeline, task)
    assert refused.status_code == 409
    body = refused.json()
    assert "Observation of the pipeline" in body["detail"]
    assert "2 of 2 runs were observed" in body["detail"]
    assert "observe it again or release it" in body["detail"]
    assert body.get("code") == "observation_ended" or "observation_ended" in refused.text


def test_after_the_limit_of_days_a_start_is_refused(api: TestClient) -> None:
    pipeline, task = _commenting(api)
    _observe_and_publish(api, pipeline, days=3)

    # the pipeline went live four days ago
    async def work(session: Any, graph: Graph) -> None:
        state = dict(graph.observe_state or {})
        state["started_at"] = (datetime.now(UTC) - timedelta(days=4)).isoformat()
        graph.observe_state = state

    _db(api, work, pipeline["id"])
    refused = _start(api, pipeline, task)
    assert refused.status_code == 409 and "the 3 days are over" in refused.text
    status = _status(api, pipeline)
    assert status["ended"] is True and status["ends_at"] is not None


def test_release_lets_the_pipeline_run_for_real_and_is_recorded(api: TestClient) -> None:
    pipeline, task = _commenting(api)
    _observe_and_publish(api, pipeline, runs=1)
    first = make_task(api, "One")
    _start(api, pipeline, first).raise_for_status()
    wait_for_run(api, first, "done")
    assert _start(api, pipeline, task).status_code == 409

    async def work(session: Any, graph: Graph) -> dict[str, Any]:
        return await observe_state.release(session, graph, "test")

    released = _db(api, work, pipeline["id"])
    assert released["released"] is True and released["observing"] is False
    started = _start(api, pipeline, task).json()
    assert started["observed"] is False and started["dry_run"] is False
    wait_for_run(api, task, "done")
    assert len(_comments(api, task)) == 1
    events = _status(api, pipeline)["events"]
    assert [e["action"] for e in events] == ["on", "release"]
    assert events[-1]["by"] == "test"


def test_observe_again_counts_from_zero_with_a_new_limit(api: TestClient) -> None:
    pipeline, task = _commenting(api)
    _observe_and_publish(api, pipeline, runs=1)
    first = make_task(api, "One")
    _start(api, pipeline, first).raise_for_status()
    wait_for_run(api, first, "done")
    assert _start(api, pipeline, task).status_code == 409

    async def work(session: Any, graph: Graph) -> dict[str, Any]:
        return await observe_state.observe_again(session, graph, "test", None, 2)

    status = _db(api, work, pipeline["id"])
    assert status["observing"] is True and status["runs"] == 2 and status["runs_done"] == 0
    for number in (1, 2):
        item = make_task(api, f"Again {number}")
        assert _start(api, pipeline, item).json()["observed"] is True
        wait_for_run(api, item, "done")
    assert _start(api, pipeline, task).status_code == 409
    assert [e["action"] for e in _status(api, pipeline)["events"]] == ["on", "again"]


def test_a_publication_that_changes_the_mode_starts_a_new_observation(api: TestClient) -> None:
    pipeline, _ = _commenting(api)
    _observe_and_publish(api, pipeline, runs=5)
    first = make_task(api, "One")
    _start(api, pipeline, first).raise_for_status()
    wait_for_run(api, first, "done")
    assert _status(api, pipeline)["runs_done"] == 1
    _set_draft(api, pipeline, {"enabled": True, "runs": 9})
    _publish(api, pipeline)
    assert _status(api, pipeline)["runs_done"] == 0, "another mode: a new observation"
    _set_draft(api, pipeline, {"enabled": True, "runs": 9})
    node(api, pipeline, "stage", name="Edited")  # an edit that does not touch the mode
    _publish(api, pipeline)
    second = make_task(api, "Two")
    _start(api, pipeline, second).raise_for_status()
    wait_for_run(api, second, "done")
    _publish_again = api.post(
        f"/api/pipelines/{pipeline['id']}/publish", json={"acknowledge": True}
    )
    assert _publish_again.status_code == 409  # nothing changed: the counters stay
    assert _status(api, pipeline)["runs_done"] == 1


def test_release_and_again_say_why_they_are_refused(api: TestClient) -> None:
    pipeline, _ = _commenting(api)
    _publish(api, pipeline)

    async def release(session: Any, graph: Graph) -> None:
        await observe_state.release(session, graph, "test")

    async def again(session: Any, graph: Graph) -> None:
        await observe_state.observe_again(session, graph, "test", None, None)

    from openartifact.exceptions import ArtifactError

    with pytest.raises(ArtifactError, match="not observed"):
        _db(api, release, pipeline["id"])
    with pytest.raises(ArtifactError, match="no observe mode"):
        _db(api, again, pipeline["id"])


# ── what cannot be observed ──────────────────────────────────────────


def test_a_node_that_needs_a_skipped_write_ends_the_observed_run_as_done_without_on_fail(
    api: TestClient,
) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    _use(api, pipeline, _comment_then_read(api, "${(Comment).output}"))
    _observe_and_publish(api, pipeline)
    _start(api, pipeline, task).raise_for_status()
    run = wait_for_run(api, task, "done")
    assert run["observed"] is True
    assert "Observed up to 'Say'" in run["note"]
    assert "cannot be observed any further" in run["note"]
    (say,) = [r for r in run["node_results"] if r["kind"] == "set"]
    assert say["outcome"] == "pass" and say["data"]["not_observable"] is True
    assert "Not observable from here" in say["reason"] and "Comment" in say["reason"]
    assert not any(r["kind"] == "output" for r in run["node_results"]), "the run stopped there"


def test_a_manual_dry_run_keeps_failing_with_the_mock_hint(api: TestClient) -> None:
    pipeline, task = build_pipeline(api, stages=1), make_task(api)
    _use(api, pipeline, _comment_then_read(api, "${(Comment).output}"))
    api.post(
        f"/api/tasks/{task['id']}/run",
        json={"pipeline_id": pipeline["id"], "dry_run": True},
    ).raise_for_status()
    run = wait_for_run(api, task, "failed")
    (say,) = [r for r in run["node_results"] if r["kind"] == "set"]
    assert say["outcome"] == "fail" and "use mock data for it" in say["reason"]


# ── the publish check ────────────────────────────────────────────────


def test_the_publish_check_names_a_change_of_the_mode(api: TestClient) -> None:
    pipeline, _ = _commenting(api)
    _publish(api, pipeline)

    def codes() -> dict[str, str]:
        found = api.get(f"/api/pipelines/{pipeline['id']}/check").json()["findings"]
        return {f["code"]: f["message"] for f in found}

    assert not {"observe_on", "observe_off", "observe_changed"} & set(codes())
    _set_draft(api, pipeline, {"enabled": True, "days": 7})
    assert "switched on with this publication (on for 7 days)" in codes()["observe_on"]
    _publish(api, pipeline)
    _set_draft(api, pipeline, {"enabled": True, "runs": 3})
    assert "from on for 7 days to on for 3 runs" in codes()["observe_changed"]
    _set_draft(api, pipeline, {"enabled": False})
    assert "switched off" in codes()["observe_off"]


def test_publishing_without_acknowledging_a_new_mode_is_asked_for_confirmation(
    api: TestClient,
) -> None:
    pipeline, _ = _commenting(api)
    _publish(api, pipeline)
    _set_draft(api, pipeline, {"enabled": True})
    refused = api.post(f"/api/pipelines/{pipeline['id']}/publish")
    assert refused.status_code == 409
    assert any(f["code"] == "observe_on" for f in refused.json()["findings"])


def test_discarding_the_draft_brings_back_the_published_mode(api: TestClient) -> None:
    pipeline, _ = _commenting(api)
    _observe_and_publish(api, pipeline, days=2)
    _set_draft(api, pipeline, {"enabled": False})
    assert api.post(f"/api/pipelines/{pipeline['id']}/draft/discard").status_code == 200
    codes = {
        f["code"] for f in api.get(f"/api/pipelines/{pipeline['id']}/check").json()["findings"]
    }
    assert "observe_off" not in codes, "the draft is the published version again, observe mode on"


# ── the migration ────────────────────────────────────────────────────


def test_migration_0067_adds_the_columns_without_losing_a_row_with_the_guard_views_installed(
    at_revision: Callable[[str], Any],
) -> None:
    path = at_revision("0066")
    guard_views.install(path)
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
        conn.execute(
            "INSERT INTO graphs (id, name, status, kind, slug, purpose, description, tags, created_at, updated_at) "
            "VALUES ('g1', 'G', 'draft', 'pipeline', 'g', 'pipeline', '', '[]', '2026-11-26', '2026-11-26')"
        )
        conn.execute(
            "INSERT INTO graph_nodes (id, graph_id, kind, name, x, y, fail_enabled, config, created_at, updated_at) "
            "VALUES ('n1', 'g1', 'trigger', 'Trigger', 0, 0, 0, '{}', '2026-11-26', '2026-11-26')"
        )
    command.upgrade(alembic_config(), "0067")
    guard_views.install(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT observed FROM executions").fetchall() == [(0,)]
        assert conn.execute("SELECT observed FROM pipeline_runs").fetchall() == [(0,)]
        assert conn.execute("SELECT observe_state FROM graphs").fetchall() == [(None,)]
        assert conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchall() == [(1,)], (
            "no cascade took the nodes of the graph with it"
        )
        assert conn.execute("SELECT dry_run FROM v_guard_runs").fetchall() == [(0,)]
    command.downgrade(alembic_config(), "0066")
    with sqlite3.connect(path) as conn:
        assert "observed" not in [r[1] for r in conn.execute("PRAGMA table_info(executions)")]
        assert "observe_state" not in [r[1] for r in conn.execute("PRAGMA table_info(graphs)")]
        assert conn.execute("SELECT id FROM executions").fetchall() == [("e1",)]
        assert conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchall() == [(1,)]
    command.upgrade(alembic_config(), "head")


def test_migration_0067_survives_the_empty_copy_a_failed_start_left_behind(
    at_revision: Callable[[str], Any],
) -> None:
    path = at_revision("0066")
    guard_views.install(path)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE _alembic_tmp_executions (id VARCHAR(36) NOT NULL PRIMARY KEY)")
    command.upgrade(alembic_config(), "0067")
    with sqlite3.connect(path) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert "_alembic_tmp_executions" not in names
        assert "observed" in [r[1] for r in conn.execute("PRAGMA table_info(executions)")]
    command.upgrade(alembic_config(), "head")
