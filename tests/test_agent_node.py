"""The agent node in a run: the snapshot an execution keeps, overrides, the history of a step, stopping."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Generator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.agents import runtime
from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.engine import runner
from openartifact.engine.executors import Limits, _agent, _masked
from openartifact.engine.results import NodeResult
from tests.agent_support import (
    API_KEY,
    HEADERS,
    SECURE,
    FakeLlm,
    completion,
    fake_llm,
    make_agent,
    make_provider,
)
from tests.helpers import build_pipeline as _pipeline
from tests.helpers import connect as _connect
from tests.helpers import graph_url as _url
from tests.helpers import make_task as _make_task
from tests.helpers import node as _node
from tests.helpers import post as _post
from tests.helpers import wait_for_run as _wait
from tests.helpers import wait_until


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    with TestClient(_create_app(migrated_settings.model_copy(update=SECURE))) as client:
        client.headers.update(HEADERS)
        yield client


@pytest.fixture
def llm() -> Iterator[FakeLlm]:
    with fake_llm() as server:
        yield server


@pytest.fixture
def quick_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "BACKOFF_SECONDS", (0.01, 0.01, 0.01, 0.01))


def _flow(
    client: TestClient,
    agent: dict[str, Any],
    *,
    before: str | None = "printf 'Login is broken'",
    **config: Any,
) -> dict[str, Any]:
    """A pipeline whose action is: trigger -> [Code "Fetch"] -> agent node "Ask" -> Output."""
    action = _post(client, "/api/actions", name="Answer")
    nodes = client.get(_url(action)).json()["nodes"]
    trigger = next(n for n in nodes if n["kind"] == "trigger")
    output = next(n for n in nodes if n["kind"] == "output")
    for edge in client.get(_url(action)).json()["edges"]:
        client.delete(f"{_url(action)}/edges/{edge['id']}")
    client.patch(f"{_url(action)}/nodes/{output['id']}", json={"fail_enabled": True})
    source, port = trigger, "out"
    if before is not None:
        fetch = _node(
            client, action, "code", name="Fetch", config={"language": "sh", "code": before}
        )
        _connect(client, action, trigger, "out", fetch, "in")
        source, port = fetch, "pass"
    settings = {"agent_id": agent["id"], "inputs": "ticket = ${node.Fetch.output}", **config}
    ask = _node(client, action, "agent", name="Ask", config=settings)
    _connect(client, action, source, port, ask, "in")
    _connect(client, action, ask, "pass", output, "pass")
    _connect(client, action, ask, "fail", output, "fail")
    pipeline = _pipeline(client, stages=1)
    shell = pipeline["stages"][0][1]
    client.patch(f"{_url(pipeline)}/nodes/{shell['id']}", json={"definition_id": action["id"]})
    pipeline["action"], pipeline["ask"] = action, ask
    return pipeline


def _run(client: TestClient, pipeline: dict[str, Any], status: str = "done") -> dict[str, Any]:
    task = _make_task(client)
    _post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = _wait(client, task, status, timeout=30)
    run["task"] = task
    return run


def _ask(run: dict[str, Any]) -> dict[str, Any]:
    return next(r for r in run["node_results"] if r["kind"] == "agent")


def _step(client: TestClient, run: dict[str, Any]) -> dict[str, Any]:
    """The agent step of the run, read alone (with its detail)."""
    task, step = run["task"], _ask(run)
    url = f"/api/tasks/{task['id']}/executions/{run['execution_id']}/steps/{step['id']}"
    response = client.get(url)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


# ── a run ────────────────────────────────────────────────────────────


def test_an_agent_node_asks_the_model_and_its_answer_is_the_output(
    api: TestClient, llm: FakeLlm
) -> None:
    provider = make_provider(api, llm)
    agent = make_agent(
        api, system_prompt_enabled=True, system_prompt="Be brief.", temperature=0.3, max_tokens=200
    )
    llm.hits.clear()
    run = _run(api, _flow(api, agent))
    (request,) = llm.completions()
    assert request["json"] == {
        "model": "small",
        "messages": [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Analyse: Login is broken\nContext: none"},
        ],
        "stream": False,
        "temperature": 0.3,
        "max_tokens": 200,
    }
    assert request["headers"]["authorization"] == f"Bearer {API_KEY}"
    step = _ask(run)
    assert (step["outcome"], step["port"]) == ("pass", "pass")
    assert step["output"] == "Answer to: Analyse: Login is broken\nContext: none"
    assert step["data"] == {
        "agent_id": agent["id"],
        "agent_version": 1,
        "provider": "Local",
        "model": "small",
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        "finish_reason": "stop",
        "attempts": 1,
        "iterations": 1,
    }
    assert step["detail"] is None  # a list never carries the detail
    detail = _step(api, run)["detail"]
    assert detail["agent"] == {"id": agent["id"], "name": "Triage", "version": 1}
    assert detail["provider"] == {
        "id": provider["id"],
        "name": "Local",
        "kind": "openai_compatible",
    }
    assert detail["system_prompt"] == "Be brief."
    assert detail["user_prompt"] == "Analyse: Login is broken\nContext: none"
    assert [(i["name"], i["state"], i["source"], i["value"]) for i in detail["inputs"]] == [
        ("ticket", "mapped", "${node.Fetch.output}", "Login is broken"),
        ("context", "default", None, "none"),
    ]
    assert detail["usage"]["total_tokens"] == 18 and detail["finish_reason"] == "stop"
    assert len(detail["attempts"]) == 1 and detail["attempts"][0]["http_status"] == 200
    assert detail["duration_ms"] >= 0


def test_the_prompts_stay_out_of_the_run_context(api: TestClient, llm: FakeLlm) -> None:
    make_provider(api, llm)
    agent = make_agent(
        api, system_prompt_enabled=True, system_prompt="A very particular system prompt."
    )
    run = _run(api, _flow(api, agent))
    task = run["task"]
    execution = api.get(f"/api/tasks/{task['id']}/executions/{run['execution_id']}").json()
    context = execution["context"]
    assert context["nodes"]["Ask"]["output"].startswith("Answer to:")
    assert context["nodes"]["Ask"]["data"]["usage"]["total_tokens"] == 18
    dumped = json.dumps(context)
    assert "A very particular system prompt." not in dumped and "user_prompt" not in dumped
    assert all(s["detail"] is None for s in execution["steps"])
    assert "A very particular system prompt." not in json.dumps(api.get("/api/runs").json())


def test_a_later_node_reads_the_answer_and_its_data(api: TestClient, llm: FakeLlm) -> None:
    make_provider(api, llm)
    agent = make_agent(api)
    pipeline = _flow(api, agent)
    action = pipeline["action"]
    nodes = api.get(_url(action)).json()
    output = next(n for n in nodes["nodes"] if n["kind"] == "output")
    edge = next(
        e
        for e in nodes["edges"]
        if e["source_id"] == pipeline["ask"]["id"] and e["source_port"] == "pass"
    )
    api.delete(f"{_url(action)}/edges/{edge['id']}")
    check = _node(
        api,
        action,
        "if",
        name="Check",
        config={"left_1": "${node.Ask.data.model}", "operator_1": "equals", "right_1": "small"},
    )
    _connect(api, action, pipeline["ask"], "pass", check, "in")
    _connect(api, action, check, "yes", output, "pass")
    run = _run(api, pipeline)
    assert next(r for r in run["node_results"] if r["kind"] == "if")["port"] == "yes"


def test_overrides_of_the_node_win_and_are_recorded(api: TestClient, llm: FakeLlm) -> None:
    provider = make_provider(api, llm)
    large = next(m for m in provider["models"] if m["model_id"] == "large")
    api.patch(f"/api/providers/{provider['id']}/models/{large['id']}", json={"enabled": True})
    agent = make_agent(api, system_prompt_enabled=True, system_prompt="Central.", temperature=0.3)
    llm.hits.clear()
    pipeline = _flow(
        api,
        agent,
        model="large",
        temperature=1.2,
        max_tokens=33,
        system_prompt_enabled=False,
        user_prompt="Only: ${input.ticket}",
        inputs="ticket = ${node.Fetch.output}\ncontext = ${card.unknown}",
    )
    run = _run(
        api, pipeline, "failed"
    )  # the artifact has no such parameter: the mapping cannot be resolved
    assert _ask(run)["reason"] == '${card.unknown}: the artifact has no parameter "unknown"'
    assert llm.completions() == []
    api.patch(
        f"{_url(pipeline['action'])}/nodes/{pipeline['ask']['id']}",
        json={"config": {"inputs": "ticket = ${node.Fetch.output}"}},
    )
    run = _run(api, pipeline)
    assert llm.completions()[0]["json"] == {
        "model": "large",
        "messages": [{"role": "user", "content": "Only: Login is broken"}],
        "stream": False,
        "temperature": 1.2,
        "max_tokens": 33,
    }
    detail = _step(api, run)["detail"]
    assert detail["overrides"] == {
        "system_prompt_enabled": False,
        "user_prompt": "Only: ${input.ticket}",
        "model": "large",
        "temperature": 1.2,
        "max_tokens": 33,
    }
    assert detail["system_prompt"] is None and detail["model"] == "large"


# ── the snapshot ─────────────────────────────────────────────────────


def _snapshot_node(api: TestClient, run: dict[str, Any]) -> dict[str, Any]:
    settings = api.app.state.settings  # type: ignore[attr-defined]
    with sqlite3.connect(settings.data_dir / settings.database_filename) as db:
        (text,) = db.execute(
            "SELECT snapshot FROM executions WHERE id = ?", (run["execution_id"],)
        ).fetchone()
    snapshot = json.loads(text)
    (definition,) = snapshot["definitions"].values()
    found: dict[str, Any] = next(n for n in definition["nodes"] if n["kind"] == "agent")
    return found


def test_the_snapshot_keeps_the_resolved_agent_and_never_the_key(
    api: TestClient, llm: FakeLlm
) -> None:
    provider = make_provider(api, llm)
    agent = make_agent(api, temperature=0.3)
    run = _run(api, _flow(api, agent, retries=0))
    node = _snapshot_node(api, run)
    frozen = node["agent"]
    assert (
        frozen["agent_id"],
        frozen["name"],
        frozen["version"],
        frozen["active"],
        frozen["error"],
    ) == (
        agent["id"],
        "Triage",
        1,
        True,
        None,
    )
    assert frozen["config"] == agent["published"]
    assert frozen["inputs"] == agent["published"]["inputs"]
    assert frozen["overrides"] == {"retries": 0}
    assert frozen["settings"]["retries"] == 0 and frozen["settings"]["temperature"] == 0.3
    assert frozen["provider"] == {
        "id": provider["id"],
        "kind": "openai_compatible",
        "name": "Local",
        "base_url": llm.url(),
        "secret_name": "LLM_KEY",
        "allow_http": True,
    }
    assert frozen["model"] == "small"
    assert (
        node["config"]["retries"] == 0 and node["config"]["temperature"] is None
    )  # the overrides themselves
    assert API_KEY not in json.dumps(node)


def test_a_running_execution_keeps_the_version_it_started_with(
    api: TestClient, llm: FakeLlm
) -> None:
    provider = make_provider(api, llm)
    agent = make_agent(api, user_prompt="Version one: ${input.ticket}")
    marker = api.app.state.settings.data_dir / "go"  # type: ignore[attr-defined]
    wait = f"while [ ! -f {marker} ]; do sleep 0.05; done; printf ticket"
    pipeline = _flow(api, agent, before=wait)
    task = _make_task(api)
    _post(api, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    _wait(api, task, "running")
    # while the run waits in the node before the agent: publish, deactivate, repoint the provider
    api.put(
        f"/api/agents/{agent['id']}/draft",
        json={**agent["draft"], "user_prompt": "Version two: ${input.ticket}"},
    )
    assert api.post(f"/api/agents/{agent['id']}/publish").json()["version"]["number"] == 2
    api.patch(f"/api/agents/{agent['id']}", json={"active": False})
    small = next(m for m in provider["models"] if m["model_id"] == "small")
    api.patch(f"/api/providers/{provider['id']}", json={"default_model": None, "name": "Renamed"})
    api.patch(f"/api/providers/{provider['id']}/models/{small['id']}", json={"enabled": False})
    api.patch(
        f"{_url(pipeline['action'])}/nodes/{pipeline['ask']['id']}",
        json={"config": {"max_tokens": 5}},
    )
    llm.hits.clear()
    marker.write_text("go")
    run = _wait(api, task, "done", timeout=30)
    run["task"] = task
    request = llm.completions()[0]["json"]
    assert request["messages"] == [{"role": "user", "content": "Version one: ticket"}]
    assert "max_tokens" not in request
    step = _ask(run)
    assert step["data"]["agent_version"] == 1 and step["data"]["provider"] == "Local"
    # the next execution sees all of it: the agent is inactive now
    again = _run(api, pipeline, "failed")
    assert _ask(again)["reason"] == 'Agent "Triage" is inactive'
    assert _ask(again)["data"] == {"agent_id": agent["id"], "agent_version": 2}


def test_new_executions_use_the_newly_published_version_and_keep_overrides(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    agent = make_agent(api, user_prompt="One: ${input.ticket}", max_tokens=100, temperature=0.1)
    pipeline = _flow(api, agent, max_tokens=7)
    _run(api, pipeline)
    api.put(
        f"/api/agents/{agent['id']}/draft",
        json={
            **agent["draft"],
            "user_prompt": "Two: ${input.ticket}",
            "max_tokens": 900,
            "temperature": 0.9,
        },
    )
    api.post(f"/api/agents/{agent['id']}/publish")
    llm.hits.clear()
    run = _run(api, pipeline)
    request = llm.completions()[0]["json"]
    assert request["messages"][0]["content"] == "Two: Login is broken"
    assert request["temperature"] == 0.9  # not overridden: follows the agent
    assert request["max_tokens"] == 7  # overridden: stays
    assert _ask(run)["data"]["agent_version"] == 2
    api.post(f"/api/agents/{agent['id']}/versions/1/republish")
    llm.hits.clear()
    run = _run(api, pipeline)
    assert llm.completions()[0]["json"]["messages"][0]["content"] == "One: Login is broken"
    assert _ask(run)["data"]["agent_version"] == 3


def test_a_draft_alone_changes_no_execution(api: TestClient, llm: FakeLlm) -> None:
    make_provider(api, llm)
    agent = make_agent(api, user_prompt="Published: ${input.ticket}")
    api.put(
        f"/api/agents/{agent['id']}/draft",
        json={**agent["draft"], "user_prompt": "Draft: ${input.ticket}"},
    )
    llm.hits.clear()
    _run(api, _flow(api, agent))
    assert llm.completions()[0]["json"]["messages"][0]["content"] == "Published: Login is broken"


@pytest.mark.parametrize(
    ("prepare", "reason"),
    [
        ("inactive", 'Agent "Triage" is inactive'),
        ("unpublished", 'Agent "Triage" has no published version'),
        ("no agent", "No agent is chosen"),
        ("model off", 'Model "small" is not enabled for provider "Local"'),
        ("no provider", "No provider is set and there is no default provider"),
        ("deleted", "The agent of this node no longer exists"),
    ],
)
def test_a_node_that_cannot_run_fails_with_its_reason_and_does_not_stop_the_start(
    api: TestClient, llm: FakeLlm, prepare: str, reason: str
) -> None:
    provider = make_provider(api, llm)
    agent = make_agent(api, publish=prepare != "unpublished")
    pipeline = _flow(api, agent)
    node_url = f"{_url(pipeline['action'])}/nodes/{pipeline['ask']['id']}"
    if prepare == "inactive":
        api.patch(f"/api/agents/{agent['id']}", json={"active": False})
    elif prepare == "no agent":
        api.patch(node_url, json={"config": {"agent_id": None}})
    elif prepare == "model off":
        small = next(m for m in provider["models"] if m["model_id"] == "small")
        api.patch(f"/api/providers/{provider['id']}/models/{small['id']}", json={"enabled": False})
    elif prepare == "no provider":
        api.patch(f"/api/providers/{provider['id']}", json={"is_default": False})
    elif prepare == "deleted":
        settings = api.app.state.settings  # type: ignore[attr-defined]
        with sqlite3.connect(settings.data_dir / settings.database_filename) as db:
            db.execute(
                "UPDATE graph_nodes SET config = json_set(config, '$.agent_id', 'gone') WHERE id = ?",
                (pipeline["ask"]["id"],),
            )
    llm.hits.clear()
    run = _run(api, pipeline, "failed")
    step = _ask(run)
    assert (step["outcome"], step["port"], step["reason"]) == ("fail", "fail", reason)
    assert llm.completions() == []  # no fallback: nothing was asked


def test_a_snapshot_of_before_agents_existed_fails_the_node_with_a_reason(
    api: TestClient, llm: FakeLlm
) -> None:
    node = {"id": "n", "name": "Ask", "kind": "agent", "config": {"agent_id": "x"}}
    result = api.portal.call(_agent, node, Limits())  # type: ignore[union-attr]
    assert (result.outcome, result.reason) == ("fail", "This execution has no agent for the node")


def test_on_failure_continue_lets_the_action_go_on(api: TestClient, llm: FakeLlm) -> None:
    make_provider(api, llm)
    agent = make_agent(api)
    llm.script = [(400, {"error": {"message": "context too long"}})]
    run = _run(api, _flow(api, agent, on_failure="continue"))
    step = _ask(run)
    assert (step["outcome"], step["port"]) == ("fail", "pass")
    assert step["reason"] == (
        "HTTP 400: the provider rejected the request: context too long (continued through On Pass)"
    )


# ── retries, time and stopping ───────────────────────────────────────


def test_every_attempt_is_in_the_history(
    api: TestClient, llm: FakeLlm, quick_retries: None
) -> None:
    make_provider(api, llm)
    agent = make_agent(api)
    llm.script = [
        (503, {"error": {"message": "overloaded"}}),
        (429, {"error": {"message": "slow down"}}, {"Retry-After": "0"}),
    ]
    run = _run(api, _flow(api, agent))
    step = _step(api, run)
    assert step["outcome"] == "pass" and step["data"]["attempts"] == 3
    attempts = step["detail"]["attempts"]
    assert [(a["number"], a["http_status"]) for a in attempts] == [(1, 503), (2, 429), (3, 200)]
    assert attempts[0]["error"] == "HTTP 503: the provider failed: overloaded"
    assert (
        attempts[0]["wait_seconds"],
        attempts[1]["wait_seconds"],
        attempts[1]["retry_after"],
    ) == (0.01, 0.0, 0.0)
    assert attempts[2]["error"] is None and attempts[2]["wait_seconds"] is None
    assert all(a["started_at"].endswith("Z") and a["duration_ms"] >= 0 for a in attempts)


def test_a_permanent_error_fails_at_once_with_status_and_no_usage(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    agent = make_agent(api)
    llm.script = [(401, {"error": {"message": "bad key"}})]
    run = _run(api, _flow(api, agent), "failed")
    step = _step(api, run)
    assert step["reason"] == "HTTP 401: the provider did not accept the API key: bad key"
    assert (
        step["data"]["status"] == 401
        and step["data"]["attempts"] == 1
        and step["data"]["usage"] is None
    )
    assert len(llm.completions()) == 1
    assert step["detail"]["user_prompt"].startswith(
        "Analyse:"
    )  # what was sent is kept for a failure too


def test_the_time_limit_of_the_node_ends_slow_attempts(api: TestClient, llm: FakeLlm) -> None:
    make_provider(api, llm)
    agent = make_agent(api)
    llm.script = [(200, completion(), None, 3.0)]
    started = time.monotonic()
    run = _run(
        api, _flow(api, agent, request_timeout_seconds=30, total_timeout_seconds=1), "failed"
    )
    assert time.monotonic() - started < 8
    step = _step(api, run)
    assert step["reason"].startswith(
        "Timeout after 1 s; not tried again: the wait of 3 s does not fit"
    )
    assert len(step["detail"]["attempts"]) == 1


def test_stopping_the_run_ends_the_wait_between_attempts(api: TestClient, llm: FakeLlm) -> None:
    make_provider(api, llm)
    agent = make_agent(api)
    llm.script = [(503, {"error": {"message": "down"}})] * 3
    pipeline = _flow(api, agent)
    task = _make_task(api)
    _post(api, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    wait_until(
        lambda: len(llm.completions()), lambda n: n >= 1
    )  # the first attempt failed: it waits 3 s now
    started = time.monotonic()
    stopped = api.post(f"/api/tasks/{task['id']}/run/stop")
    assert stopped.status_code == 200 and stopped.json()["status"] == "stopped"
    assert time.monotonic() - started < 2
    time.sleep(0.3)
    assert len(llm.completions()) == 1  # nothing was asked after the stop


# ── secrets, history and limits ──────────────────────────────────────


def test_the_key_never_reaches_history_snapshot_context_or_logs(
    api: TestClient, llm: FakeLlm, caplog: pytest.LogCaptureFixture
) -> None:
    make_provider(api, llm)
    agent = make_agent(api)
    # a provider that echoes the key in its answer and in its error
    llm.script = [(200, completion(f"Your key is {API_KEY}."))]
    with caplog.at_level(logging.DEBUG):
        run = _run(api, _flow(api, agent))
        step = _step(api, run)
        llm.script = [(400, {"error": {"message": f"bad request with {API_KEY}"}})]
        failed = _step(api, _run(api, _flow(api, agent), "failed"))
    assert step["output"] == "Your key is ***."
    assert failed["reason"] == "HTTP 400: the provider rejected the request: bad request with ***"
    settings = api.app.state.settings  # type: ignore[attr-defined]
    with sqlite3.connect(settings.data_dir / settings.database_filename) as db:
        stored = json.dumps(
            [
                db.execute(f"SELECT * FROM {table}").fetchall()
                for table in (
                    "run_node_results",
                    "executions",
                    "pipeline_runs",
                    "llm_providers",
                    "agents",
                    "agent_versions",
                )
            ],
            default=str,
        )
    assert API_KEY not in stored
    assert API_KEY not in caplog.text and "Bearer" not in caplog.text


def test_a_missing_secret_fails_the_node_before_any_request(api: TestClient, llm: FakeLlm) -> None:
    make_provider(api, llm)
    agent = make_agent(api)
    pipeline = _flow(api, agent)
    api.delete("/api/secrets/LLM_KEY")
    llm.hits.clear()
    run = _run(api, pipeline, "failed")
    assert _ask(run)["reason"] == "Secret LLM_KEY does not exist"
    assert llm.completions() == []


def test_the_detail_is_masked_with_the_rest_of_a_result() -> None:
    result = NodeResult(
        "pass",
        output="a",
        detail={"user_prompt": "key=hunter22", "attempts": [{"error": "hunter22"}]},
    )
    masked = _masked(result, {"K": "hunter22"})
    assert masked.detail == {"user_prompt": "key=***", "attempts": [{"error": "***"}]}


def test_the_detail_goes_with_its_execution(api: TestClient, llm: FakeLlm) -> None:
    make_provider(api, llm)
    agent = make_agent(api)
    run = _run(api, _flow(api, agent))
    task = run["task"]
    settings = api.app.state.settings  # type: ignore[attr-defined]

    def details() -> int:
        with sqlite3.connect(settings.data_dir / settings.database_filename) as db:
            return int(
                db.execute(
                    "SELECT count(*) FROM run_node_results WHERE detail IS NOT NULL AND detail != 'null'"
                ).fetchone()[0]
            )

    assert details() == 1
    assert (
        api.delete(f"/api/tasks/{task['id']}/executions/{run['execution_id']}").status_code == 204
    )
    assert details() == 0


def test_a_long_answer_is_cut_in_the_context_only_and_says_so(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    agent = make_agent(api)
    llm.script = [(200, completion("word " * 2000, finish="length"))]
    run = _run(api, _flow(api, agent))
    step = _step(api, run)
    assert len(step["output"]) == 10000  # the step keeps all of it
    assert "the model stopped at its token limit" in step["reason"]
    assert "longer than the 4 KiB the run context keeps" in step["reason"]
    task = run["task"]
    context = api.get(f"/api/tasks/{task['id']}/executions/{run['execution_id']}/context").json()
    entry = context["nodes"]["Ask"]
    assert entry["truncated"] is True and entry["output"].endswith("[output truncated]")
    assert len(entry["output"].encode()) < 4200


def test_an_output_beyond_the_limit_of_a_step_is_cut_visibly_for_every_kind(
    api: TestClient, llm: FakeLlm, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "RESULT_OUTPUT_LIMIT_CHARS", 1024)
    make_provider(api, llm)
    agent = make_agent(api)
    llm.script = [(200, completion("y" * 3000))]
    run = _run(api, _flow(api, agent, before="head -c 2000 /dev/zero | tr '\\0' 'x'"))
    code = next(r for r in run["node_results"] if r["kind"] == "code")
    assert len(code["output"]) == 1024 and code["output"].endswith("\n[output truncated]")
    assert code["data"]["output_truncated"] is True
    assert code["reason"] == "Note: the output was cut at 1 Ki characters"
    step = _ask(run)
    assert len(step["output"]) == 1024 and step["output"].endswith("\n[output truncated]")
    assert step["data"]["output_truncated"] is True and step["data"]["model"] == "small"
    assert step["reason"] == "Note: the output was cut at 1 Ki characters"


def test_a_short_output_is_stored_as_it_is(api: TestClient, llm: FakeLlm) -> None:
    make_provider(api, llm)
    run = _run(api, _flow(api, make_agent(api)))
    code = next(r for r in run["node_results"] if r["kind"] == "code")
    assert code["output"] == "Login is broken" and "output_truncated" not in (code["data"] or {})
    assert code["reason"] is None


# ── the other ways in ────────────────────────────────────────────────


def test_the_step_detail_is_in_the_integration_api_and_the_flow_draws_the_node(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    run = _run(api, _flow(api, make_agent(api)))
    task, step = run["task"], _ask(run)
    read = api.get(
        f"/api/v1/artifacts/{task['number']}/executions/{run['execution_id']}/steps/{step['id']}"
    )
    assert read.status_code == 200 and read.json()["detail"]["user_prompt"].startswith("Analyse:")
    flow = api.get(f"/api/tasks/{task['id']}/executions/{run['execution_id']}/flow")
    assert flow.status_code == 200, flow.text
    assert '"kind":"agent"' in flow.text  # the frozen node is drawn like every other kind
