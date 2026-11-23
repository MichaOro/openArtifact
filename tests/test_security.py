"""Security hardening: Host check, headers, cookie, startup checks, body limits, cross-site guard,
finite coordinates and the limits and atomic start of the run engine."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.exceptions import ArtifactError, ConfigurationError
from openartifact.security import COOKIE_MAX_AGE, SECURE_COOKIE, session_valid, session_value
from tests.helpers import (
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

TOKEN = "s3cure-token-" + "x" * 30
SECRET = "k" * 40
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
HTML = {"Accept": "text/html"}


def _settings(base: Settings, **changes: Any) -> Settings:
    return base.model_copy(update={"api_token": TOKEN, "secret_key": SECRET, **changes})


@pytest.fixture
def make_client(migrated_settings: Settings) -> Generator[Callable[..., TestClient], None, None]:
    """Build clients of the application with changed settings; all are closed afterwards."""
    clients: list[TestClient] = []

    def make(
        secured: bool = True, base_url: str = "http://testserver", **changes: Any
    ) -> TestClient:
        settings = (
            _settings(migrated_settings, **changes)
            if secured
            else migrated_settings.model_copy(update=changes)
        )
        client = TestClient(_create_app(settings), base_url=base_url)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in reversed(clients):
        client.__exit__(None, None, None)


# ── startup checks ────────────────────────────────────────────────────────────


def test_a_token_needs_at_least_32_characters(migrated_settings: Settings) -> None:
    with pytest.raises(ConfigurationError, match="at least 32 characters"):
        _create_app(_settings(migrated_settings, api_token="short"))


def test_a_token_is_refused_together_with_the_default_secret_key(
    migrated_settings: Settings,
) -> None:
    with pytest.raises(ConfigurationError, match="SECRET_KEY"):
        _create_app(_settings(migrated_settings, secret_key="change-me-in-production"))
    with pytest.raises(ConfigurationError, match="SECRET_KEY"):
        _create_app(_settings(migrated_settings, secret_key=""))


def test_starting_without_a_token_warns_that_the_application_is_open(
    migrated_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        caplog.at_level(logging.WARNING, logger="openartifact"),
        TestClient(_create_app(migrated_settings)),
    ):
        pass
    assert "No OPENARTIFACT_API_TOKEN" in caplog.text


# ── Host check ────────────────────────────────────────────────────────────────


def test_a_host_outside_the_allowed_list_is_refused_everywhere(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(secured=False, allowed_hosts="board.example, *.corp.example")
    assert client.get("/api/tasks", headers={"Host": "attacker.example"}).status_code == 400
    assert client.post("/mcp", json={}, headers={"Host": "attacker.example"}).status_code == 400
    assert client.get("/", headers={"Host": "attacker.example"}).status_code == 400
    assert client.get("/api/tasks", headers={"Host": "board.example:2909"}).status_code == 200
    assert client.get("/api/tasks", headers={"Host": "BOARD.example"}).status_code == 200
    assert client.get("/api/tasks", headers={"Host": "a.corp.example"}).status_code == 200
    assert client.get("/api/tasks", headers={"Host": "corp.example.evil"}).status_code == 400
    # a container health check must work whatever the list says
    assert client.get("/health", headers={"Host": "127.0.0.1"}).status_code == 200


def test_without_an_allowed_hosts_list_every_host_is_accepted(client: TestClient) -> None:
    assert client.get("/api/tasks", headers={"Host": "anything.example"}).status_code == 200


# ── security headers ──────────────────────────────────────────────────────────


def test_responses_carry_the_security_headers(client: TestClient) -> None:
    for path in ("/", "/api/tasks", "/login", "/static/css/tokens.css", "/nope"):
        headers = client.get(path).headers
        policy = headers["content-security-policy"]
        assert "default-src 'self'" in policy and "frame-ancestors 'none'" in policy, path
        assert "base-uri 'none'" in policy and "form-action 'self'" in policy
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "same-origin"
        assert "strict-transport-security" not in headers  # plain http


def test_scripts_are_limited_to_the_application_unless_the_owner_opts_out(
    make_client: Callable[..., TestClient],
) -> None:
    strict = make_client(secured=False).get("/").headers["content-security-policy"]
    assert "script-src 'self';" in strict and "unsafe-inline'; style" not in strict
    relaxed = make_client(secured=False, csp_script_unsafe_inline=True)
    assert (
        "script-src 'self' 'unsafe-inline';" in relaxed.get("/").headers["content-security-policy"]
    )


def test_no_template_carries_an_inline_script() -> None:
    """The strict policy only works while every <script> has a src."""
    import re
    from pathlib import Path

    templates = Path(__file__).resolve().parent.parent / "openartifact" / "templates"
    for path in templates.rglob("*.html"):
        for tag in re.findall(r"<script\b[^>]*>", path.read_text()):
            if (
                'type="application/json"' in tag
            ):  # a data block (the dictionary, ADR-056) is never executed
                continue
            assert "src=" in tag, f"inline script in {path.name}: {tag}"


def test_hsts_is_sent_only_over_https(make_client: Callable[..., TestClient]) -> None:
    plain = make_client(secured=False)
    assert "strict-transport-security" not in plain.get("/health").headers
    secure = make_client(secured=False, base_url="https://testserver")
    assert "max-age=" in secure.get("/health").headers["strict-transport-security"]


def test_swagger_gets_its_own_policy_for_the_cdn(client: TestClient) -> None:
    assert "cdn.jsdelivr.net" in client.get("/api/docs").headers["content-security-policy"]
    assert "cdn.jsdelivr.net" not in client.get("/").headers["content-security-policy"]


# ── session cookie ────────────────────────────────────────────────────────────


def _sign_in(client: TestClient) -> Any:
    return client.post("/login", data={"token": TOKEN, "next": "/"}, follow_redirects=False)


def test_the_cookie_is_secure_and_host_prefixed_when_asked(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(cookie_secure="true", base_url="https://testserver")
    cookie = _sign_in(client).headers["set-cookie"]
    assert cookie.startswith(f"{SECURE_COOKIE}=") and "Secure" in cookie and "Path=/" in cookie
    assert client.get("/api/tasks").status_code == 200  # the prefixed cookie is the one that counts
    client.post("/logout", follow_redirects=False)
    assert not client.cookies


def test_the_cookie_is_plain_over_http_and_secure_when_the_request_is_https(
    make_client: Callable[..., TestClient],
) -> None:
    assert "Secure" not in _sign_in(make_client()).headers["set-cookie"]
    cookie = _sign_in(make_client(base_url="https://testserver")).headers["set-cookie"]
    assert cookie.startswith(f"{SECURE_COOKIE}=") and "Secure" in cookie
    off = make_client(cookie_secure="false")
    assert "Secure" not in _sign_in(off).headers["set-cookie"]


def test_a_session_expires_on_the_server(make_client: Callable[..., TestClient]) -> None:
    client = make_client()
    settings = client.app.state.settings  # type: ignore[attr-defined]
    assert session_valid(settings, session_value(settings))
    old = session_value(settings, issued_at=int(time.time()) - COOKIE_MAX_AGE - 10)
    assert not session_valid(settings, old)
    client.cookies.set("oa_session", old)
    assert client.get("/api/tasks").status_code == 401
    client.cookies.set("oa_session", session_value(settings))
    assert client.get("/api/tasks").status_code == 200


def test_a_cookie_with_a_changed_time_or_from_another_token_or_secret_is_refused(
    make_client: Callable[..., TestClient], migrated_settings: Settings
) -> None:
    settings = make_client().app.state.settings  # type: ignore[attr-defined]
    stamp, _, signature = session_value(settings).partition(".")
    assert not session_valid(settings, f"{int(stamp) + 5}.{signature}")
    assert not session_valid(settings, signature)
    assert not session_valid(settings, None)
    value = session_value(settings)
    rotated_token = settings.model_copy(update={"api_token": "another-token-" + "y" * 30})
    rotated_secret = settings.model_copy(update={"secret_key": "z" * 40})
    assert not session_valid(rotated_token, value)
    assert not session_valid(rotated_secret, value)


# ── sizes and malformed input ─────────────────────────────────────────────────


def test_a_large_or_undecodable_sign_in_body_is_not_a_crash(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client()
    big = client.post("/login", content=b"token=" + b"a" * 10_000, headers=_form())
    assert big.status_code == 413
    bad = client.post("/login", content=b"token=\xff\xfe", headers=_form())
    assert bad.status_code == 401 and "not right" in bad.text


def _form() -> dict[str, str]:
    return {"Content-Type": "application/x-www-form-urlencoded"}


def test_a_request_body_above_the_limit_gets_413(make_client: Callable[..., TestClient]) -> None:
    client = make_client(secured=False, max_request_bytes=1000)
    ok = client.post("/api/tasks", json={"title": "x", "status": "backlog"})
    assert ok.status_code == 201
    declared = client.post("/api/tasks", json={"title": "x" * 2000, "status": "backlog"})
    assert declared.status_code == 413

    def chunks() -> Any:
        for _ in range(5):
            yield b'{"title": "' + b"x" * 400 + b'"}'

    streamed = client.post(
        "/api/tasks", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert streamed.status_code == 413
    assert client.get("/api/tasks").status_code == 200  # the server is fine


def test_a_non_ascii_bearer_header_is_a_refusal_not_a_server_error(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client()
    odd = {b"Authorization": "Bearer tøken-ünïcode".encode("latin-1")}
    assert client.get("/api/tasks", headers=odd).status_code == 401
    assert client.get("/api/v1/artifacts", headers=odd).status_code == 401
    assert client.post("/mcp", json={}, headers=odd).status_code == 401
    # the cookie header is decoded safely too
    assert client.get("/api/tasks", headers={b"Cookie": b"oa_session=\xe9\xe8"}).status_code == 401
    assert client.get("/api/tasks", headers=HEADERS).status_code == 200


def test_an_unauthorised_websocket_is_closed_with_a_policy_violation(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client()
    with pytest.raises(WebSocketDisconnect) as closed, client.websocket_connect("/ws"):
        pass
    assert closed.value.code == 1008


# ── cross-site requests ───────────────────────────────────────────────────────


def test_a_cross_site_request_cannot_start_or_stop_a_run(client: TestClient) -> None:
    task = make_task(client)
    url = f"/api/tasks/{task['id']}/run"
    forged = {"Content-Type": "text/plain", "Origin": "https://evil.example"}
    assert client.post("/api/tasks/1/run", headers=forged).status_code == 403
    assert client.post(f"{url}/stop", headers=forged).status_code == 403
    assert client.post(url, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post(url, headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
    assert client.post(url, headers={"Origin": "null"}).status_code == 403
    # a same-origin browser and a script without browser headers get through to the real answer
    same = {"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}
    assert client.post(url, headers=same).status_code == 422  # no pipeline chosen yet
    assert client.post(url).status_code == 422


def test_unsafe_methods_of_every_kind_are_guarded(client: TestClient) -> None:
    evil = {"Origin": "https://evil.example"}
    assert client.post("/logout", headers=evil, follow_redirects=False).status_code == 403
    assert client.delete("/api/tasks/x", headers=evil).status_code == 403
    assert client.patch("/api/tasks/x", json={}, headers=evil).status_code == 403
    assert client.get("/api/tasks", headers=evil).status_code == 200  # reading is not guarded


def test_a_body_that_is_not_json_is_refused_on_the_api(client: TestClient) -> None:
    assert client.post("/api/tasks", content=b"title=x", headers=_form()).status_code == 415
    plain = {"Content-Type": "text/plain"}
    assert client.post("/api/tasks", content=b"{}", headers=plain).status_code == 415
    typed = {"Content-Type": "application/json; charset=utf-8"}
    assert client.post("/api/tasks", content=b'{"title":"x"}', headers=typed).status_code == 201


# ── coordinates ───────────────────────────────────────────────────────────────


def test_coordinates_must_be_finite_and_bounded(client: TestClient) -> None:
    pipeline = client.post("/api/pipelines", json={"name": "P"}).json()
    nodes = f"/api/pipelines/{pipeline['id']}/nodes"
    json_header = {"Content-Type": "application/json"}
    for body in (b'{"kind":"stage","x":Infinity,"y":NaN}', b'{"kind":"stage","x":-Infinity}'):
        assert client.post(nodes, content=body, headers=json_header).status_code == 422
    assert client.post(nodes, json={"kind": "stage", "x": 1e308}).status_code == 422
    made = client.post(nodes, json={"kind": "stage", "x": 10, "y": -20})
    assert made.status_code == 201
    node = f"{nodes}/{made.json()['id']}"
    assert client.patch(node, content=b'{"width":Infinity}', headers=json_header).status_code == 422
    assert client.patch(node, json={"height": 1e9}).status_code == 422
    assert client.patch(node, json={"width": 300, "height": 200}).status_code == 200


# ── engine ────────────────────────────────────────────────────────────────────


def test_two_simultaneous_starts_make_one_run(client: TestClient) -> None:
    pipeline = slow_pipeline(client)
    task = make_task(client)
    engine = client.app.state.engine  # type: ignore[attr-defined]
    reached_the_database: list[int] = []
    real_start = engine._start

    async def counting(*args: Any, **kwargs: Any) -> Any:
        reached_the_database.append(1)
        return await real_start(*args, **kwargs)

    engine._start = counting

    async def both() -> tuple[Any, ...]:
        return await asyncio.gather(
            engine.start(task["id"], pipeline["id"]),
            engine.start(task["id"], pipeline["id"]),
            return_exceptions=True,
        )

    results = client.portal.call(both)  # type: ignore[union-attr]
    errors = [r for r in results if isinstance(r, ArtifactError)]
    assert [e.status for e in errors] == [409]
    assert len(reached_the_database) == 1  # the loser is refused by the in-process guard
    assert len(engine._jobs) == 1
    stopped = client.post(f"/api/tasks/{task['id']}/run/stop")
    assert stopped.status_code == 200
    assert not engine._jobs
    assert wait_for_run(client, task, "stopped")["note"] == "stopped"  # nothing orphaned writes on


def test_the_database_refuses_a_second_start_even_without_the_in_process_guard(
    client: TestClient,
) -> None:
    pipeline = slow_pipeline(client)
    task = make_task(client)
    engine = client.app.state.engine  # type: ignore[attr-defined]
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    jobs = dict(engine._jobs)
    engine._jobs.clear()  # as if another server process held the run
    refused = client.post(f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]})
    engine._jobs.update(jobs)  # the first run is still ours: stop it, or it outlives the engine
    assert refused.status_code == 409
    assert client.post(f"/api/tasks/{task['id']}/run/stop").status_code == 200
    assert not engine._jobs
    assert wait_for_run(client, task, "stopped")["note"] == "stopped"


def test_a_stopped_run_does_not_take_the_bookkeeping_of_its_successor(client: TestClient) -> None:
    pipeline = slow_pipeline(client)
    task = make_task(client)
    url = f"/api/tasks/{task['id']}/run"
    engine = client.app.state.engine  # type: ignore[attr-defined]
    post(client, url, pipeline_id=pipeline["id"])
    assert client.post(f"{url}/stop").status_code == 200
    post(client, url, pipeline_id=pipeline["id"])
    assert task["id"] in engine._jobs
    assert client.post(f"{url}/stop").status_code == 200  # and can be stopped, nothing is orphaned


def test_runs_above_the_limit_are_refused_with_429(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(secured=False, max_concurrent_runs=2)
    pipeline = slow_pipeline(client)
    tasks = [make_task(client) for _ in range(3)]
    for task in tasks[:2]:
        post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    refused = client.post(f"/api/tasks/{tasks[2]['id']}/run", json={"pipeline_id": pipeline["id"]})
    assert refused.status_code == 429 and "2 runs" in refused.json()["detail"]
    client.post(f"/api/tasks/{tasks[0]['id']}/run/stop")
    again = client.post(f"/api/tasks/{tasks[2]['id']}/run", json={"pipeline_id": pipeline["id"]})
    assert again.status_code == 201


def test_a_run_counts_the_nodes_of_actions_against_the_step_limit(client: TestClient) -> None:
    """One action whose definition chains twelve nodes: the action and its nodes count against the same
    limit, so ten steps are exhausted inside the action, not by the number of actions."""
    assert client.put("/api/settings/run-limits", json={"max_steps": 10}).status_code == 200
    definition = post(client, "/api/actions", name="Many steps")
    previous, port = kind_of(client, definition, "trigger"), "out"
    for edge in client.get(graph_url(definition)).json()["edges"]:
        client.delete(f"{graph_url(definition)}/edges/{edge['id']}")
    for n in range(12):
        step = node(client, definition, "set", name=f"Set {n}", config={"fields": f"n = {n}"})
        connect(client, definition, previous, port, step, "in")
        previous, port = step, "pass"
    connect(client, definition, previous, port, kind_of(client, definition, "output"), "pass")
    pipeline = build_pipeline(client, stages=1)
    link(client, pipeline, pipeline["stages"][0][1], definition)
    task = make_task(client)
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = wait_for_run(client, task, "failed")
    assert (
        run["note"]
        == "The pipeline does not come to an end: more than 10 steps (Settings > Run limits)"
    )
    assert len(run["node_results"]) == 10  # the steps before the limit were recorded


def test_event_streams_are_limited(make_client: Callable[..., TestClient]) -> None:
    client = make_client(secured=False, max_sse_subscribers=1)
    bus = client.app.state.event_bus  # type: ignore[attr-defined]
    held = bus.subscribe()
    response = client.get("/api/events")
    assert response.status_code == 503
    bus.unsubscribe(held)
    assert not bus.full


def test_protecting_the_process_memory_is_idempotent_and_reports_the_outcome() -> None:
    from openartifact.security import protect_process_memory

    first = protect_process_memory()
    assert protect_process_memory() is first
