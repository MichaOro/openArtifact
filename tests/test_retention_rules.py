"""Global retention rules (ADR-052): which finished executions are deleted, checked whenever an execution is added or
finishes (and when the rules are saved)."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import build_definition, build_pipeline, link, make_task, post, wait_for_run
from tests.test_history import HEADERS, TOKEN
from tests.test_history_global import Seed, _ids, _list

RULES = "/api/settings/retention"


def _group(*items: dict[str, Any], mode: str = "all") -> dict[str, Any]:
    return {"type": "group", "mode": mode, "items": list(items)}


def _cond(field: str, op: str, value: Any) -> dict[str, Any]:
    return {"type": "condition", "field": field, "op": op, "value": value}


def _put(client: TestClient, rules: dict[str, Any], **query: Any) -> Any:
    return client.put(RULES, json={"rules": rules}, params=query)


@pytest.fixture
def seed(client: TestClient) -> Seed:
    return Seed(client)


@pytest.fixture
def secured(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


@pytest.fixture
def old(client: TestClient, seed: Seed) -> dict[str, str]:
    """Four finished executions of one artifact that started days ago, one running, and one fresh."""
    task = make_task(client, "Alpha")
    now = datetime.now(UTC)
    return {
        "done_old": seed.add(task, at=now - timedelta(days=10), status="done", pipeline="Build"),
        "failed_old": seed.add(task, at=now - timedelta(days=9), status="failed", pipeline="Build"),
        "done_api": seed.add(
            task, at=now - timedelta(days=8), status="done", by="api", pipeline="Deploy"
        ),
        "stopped_old": seed.add(
            task, at=now - timedelta(days=7), status="stopped", pipeline="Deploy"
        ),
        "running": seed.add(task, at=now - timedelta(days=6), status="running", pipeline="Build"),
        "fresh": seed.add(task, at=now - timedelta(minutes=5), status="done", pipeline="Build"),
    }


# ── the rules as stored ──────────────────────────────────────────────


def test_no_rules_are_stored_until_some_are_saved_and_an_empty_rule_deletes_nothing(
    client: TestClient, old: dict[str, str]
) -> None:
    assert client.get(RULES).json()["rules"] == _group()
    assert _put(client, _group()).json()["deleted"] == 0
    assert _put(client, _group(_group())).json()["deleted"] == 0  # an empty group matches nothing
    assert len(_list(client)["items"]) == 6


def test_invalid_rules_are_refused_with_the_reason(client: TestClient) -> None:
    bad = [
        (_group(_cond("status", "is", ["running"])), "running"),
        (_group(_cond("status", "is", [])), "at least one"),
        (_group(_cond("status", "older_than", 60)), "older_than"),
        (_group(_cond("age", "older_than", 5)), "60"),
        (_group(_cond("age", "is", 600)), "is"),
        (_group(_cond("started_by", "is", ["robot"])), "robot"),
        (_group(_cond("pipeline", "contains", "")), "pipeline"),
        (_group(_cond("colour", "is", ["red"])), "colour"),
    ]
    for rules, reason in bad:
        response = _put(client, rules)
        assert response.status_code == 422, rules
        assert reason in response.text, (rules, response.text)
    deep: dict[str, Any] = _group(_cond("age", "older_than", 3600))
    for _ in range(6):
        deep = _group(deep)
    assert _put(client, deep).status_code == 422  # nested too deep
    assert _put(client, _group(*[_cond("age", "older_than", 3600)] * 51)).status_code == 422
    assert client.get(RULES).json()["rules"] == _group()  # nothing was stored


# ── what a rule deletes ──────────────────────────────────────────────


def test_saving_applies_the_rules_to_what_exists_never_to_a_running_execution(
    client: TestClient, old: dict[str, str]
) -> None:
    done = _cond("status", "is", ["done", "failed"])
    older = _cond("age", "older_than", 86400)
    result = _put(client, _group(done, older)).json()
    assert (
        result["deleted"] == 3
    )  # done_old, failed_old, done_api: finished, done or failed, older than a day
    left = set(_ids(_list(client)))
    assert left == {old["stopped_old"], old["running"], old["fresh"]}


def test_all_and_any_and_inner_groups_decide_together(
    client: TestClient, old: dict[str, str]
) -> None:
    # (pipeline Deploy AND started by api) OR status stopped: done_api and stopped_old
    rules = _group(
        _group(_cond("pipeline", "is", "deploy"), _cond("started_by", "is", ["api"])),
        _cond("status", "is", ["stopped"]),
        mode="any",
    )
    assert _put(client, rules).json()["deleted"] == 2
    assert set(_ids(_list(client))) == {
        old["done_old"],
        old["failed_old"],
        old["running"],
        old["fresh"],
    }


def test_is_not_and_contains_on_the_pipeline_and_the_user_of_the_run(
    client: TestClient, old: dict[str, str]
) -> None:
    rules = _group(_cond("pipeline", "contains", "uil"), _cond("status", "is_not", ["failed"]))
    assert (
        _put(client, rules).json()["deleted"] == 2
    )  # done_old and fresh (a Build that did not fail, not running)
    assert set(_ids(_list(client))) == {
        old["failed_old"],
        old["done_api"],
        old["stopped_old"],
        old["running"],
    }


def test_a_wildcard_in_a_pipeline_name_is_text_not_a_pattern(
    client: TestClient, old: dict[str, str]
) -> None:
    assert _put(client, _group(_cond("pipeline", "contains", "%"))).json()["deleted"] == 0
    assert _put(client, _group(_cond("pipeline", "contains", "_"))).json()["deleted"] == 0
    assert len(_list(client)["items"]) == 6


def test_a_preview_counts_what_saving_would_delete_and_deletes_nothing(
    client: TestClient, old: dict[str, str]
) -> None:
    rules = _group(_cond("status", "is", ["done"]))
    preview = client.post(f"{RULES}/preview", json={"rules": rules}).json()
    assert preview == {"matching": 3}  # done_old, done_api, fresh
    assert len(_list(client)["items"]) == 6
    assert client.get(RULES).json()["rules"] == _group()


# ── push driven: when something is added or finishes ─────────────────


def test_a_finished_execution_that_a_rule_matches_is_gone_at_once_and_others_stay(
    client: TestClient,
) -> None:
    pipeline = build_pipeline(client, stages=1)
    link(client, pipeline, pipeline["stages"][0][1], build_definition(client, "Pass"))
    task = make_task(client)
    assert _put(client, _group(_cond("status", "is", ["done"]))).json()["deleted"] == 0
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(client, task, "done")
    assert (
        client.get(f"/api/tasks/{task['id']}/executions").json()["total"] == 0
    )  # not archived: weg ist weg


def test_old_executions_go_when_a_new_one_starts_without_any_save(
    client: TestClient, seed: Seed
) -> None:
    task = make_task(client)
    stale = seed.add(task, at=datetime.now(UTC) - timedelta(days=3), status="done")
    # the rule is stored while nothing matches yet; the old execution is not touched by anything else
    assert _put(client, _group(_cond("age", "older_than", 7 * 86400))).json()["deleted"] == 0
    with sqlite3.connect(
        Path(client.app.state.settings.data_dir / client.app.state.settings.database_filename)
    ) as c:  # type: ignore[attr-defined]
        c.execute(
            "UPDATE executions SET started_at = ? WHERE id = ?",
            ("2020-01-01 00:00:00.000000", stale),
        )
        c.execute(
            "UPDATE tasks SET execution_seq = 1 WHERE id = ?", (task["id"],)
        )  # the seeded one is number 1
    pipeline = build_pipeline(client, stages=1)
    link(client, pipeline, pipeline["stages"][0][1], build_definition(client, "Pass"))
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_for_run(client, task, "done")
    ids = [e["id"] for e in client.get(f"/api/tasks/{task['id']}/executions").json()["items"]]
    assert (
        stale not in ids and len(ids) == 1
    )  # the new execution stays; the stale one went with its start


def test_the_rules_need_the_access_token_like_everything_else(secured: TestClient) -> None:
    open_client = TestClient(secured.app)
    assert open_client.get(RULES).status_code == 401
    assert open_client.put(RULES, json={"rules": _group()}).status_code == 401


def test_an_empty_inner_group_is_ignored_it_neither_blocks_nor_matches_everything(
    client: TestClient, old: dict[str, str]
) -> None:
    rules = _group(_cond("status", "is", ["failed"]), _group(), _group(mode="any"))
    assert _put(client, rules).json()["deleted"] == 1  # only the failed one, as the rule reads
    only_empty = _group(_group(), _group())
    assert _put(client, only_empty).json()["deleted"] == 0


def test_keeping_only_the_newest_n_of_each_artifact_is_a_rule_too(
    client: TestClient, seed: Seed
) -> None:
    """The same as the per-artifact "keep the last N": the position among an artifact's executions, newest first."""
    a, b = make_task(client, "Alpha"), make_task(client, "Beta")
    now = datetime.now(UTC)
    a_ids = [
        seed.add(a, at=now - timedelta(hours=10 - i), status="done") for i in range(5)
    ]  # a1 oldest ... a5 newest
    b_ids = [seed.add(b, at=now - timedelta(hours=5 - i), status="done") for i in range(2)]
    running = seed.add(a, at=now - timedelta(minutes=1), status="running")
    # beyond the newest 2: counted per artifact, the running one is in the count but never deleted
    result = _put(client, _group(_cond("position", "beyond", 2))).json()
    assert (
        result["deleted"] == 4
    )  # a1..a4: the running one and a5 are the two newest of Alpha, Beta has only two
    assert set(_ids(_list(client))) == {a_ids[4], running, *b_ids}
    assert _put(client, _group(_cond("position", "beyond", 0))).status_code == 422
    assert _put(client, _group(_cond("position", "is", 3))).status_code == 422


def test_position_and_other_conditions_combine(client: TestClient, seed: Seed) -> None:
    task = make_task(client, "Alpha")
    now = datetime.now(UTC)
    ids = [
        seed.add(task, at=now - timedelta(hours=9 - i), status="failed" if i % 2 else "done")
        for i in range(6)
    ]
    # beyond the newest 3 AND failed: of ids[0..2] the failed one (index 1)
    rules = _group(_cond("position", "beyond", 3), _cond("status", "is", ["failed"]))
    assert _put(client, rules).json()["deleted"] == 1
    assert ids[1] not in set(_ids(_list(client))) and len(_ids(_list(client))) == 5
