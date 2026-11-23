"""The agent runtime: the guarded client against a local server, retries, time limits and the node's result."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from openartifact.agents import client, runtime
from openartifact.agents.client import (
    UNENCRYPTED_REFUSED,
    Completion,
    Endpoint,
    IncompatibleError,
    NoModelListError,
    ProviderError,
    retry_after_seconds,
    status_error,
)
from openartifact.agents.resolve import ProviderInfo, freeze
from openartifact.agents.runtime import BACKOFF_SECONDS, endpoint_of, run_completion, run_node
from openartifact.agents.schemas import AgentConfig, InputSpec
from openartifact.engine import http_runner
from openartifact.engine.context import NodeIndex, RunContext, RunView
from tests.agent_support import API_KEY, FakeLlm, completion, fake_llm

MESSAGES = [{"role": "user", "content": "Hi"}]


@pytest.fixture
def llm() -> Iterator[FakeLlm]:
    with fake_llm() as server:
        yield server


def _endpoint(
    llm: FakeLlm, mount: str = "", *, private: bool = True, key: str | None = API_KEY
) -> Endpoint:
    return Endpoint(llm.url(mount), key, private)


# ── the client ───────────────────────────────────────────────────────


async def test_a_completion_sends_the_openai_request_and_reads_the_answer(llm: FakeLlm) -> None:
    done = await client.complete(
        _endpoint(llm), "small", MESSAGES, temperature=0.3, max_tokens=64, timeout=5
    )
    assert done.text == "Answer to: Hi" and done.finish_reason == "stop" and done.status == 200
    assert done.usage() == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    (hit,) = llm.hits
    assert (hit["method"], hit["path"]) == ("POST", "/v1/chat/completions")
    assert hit["json"] == {
        "model": "small",
        "messages": MESSAGES,
        "stream": False,
        "temperature": 0.3,
        "max_tokens": 64,
    }
    assert hit["headers"]["authorization"] == f"Bearer {API_KEY}"
    assert hit["headers"]["host"] == f"127.0.0.1:{llm.port}"


async def test_settings_that_are_not_set_and_a_missing_key_are_not_sent(llm: FakeLlm) -> None:
    await client.complete(_endpoint(llm, key=None), "small", MESSAGES, timeout=5)
    (hit,) = llm.hits
    assert set(hit["json"]) == {"model", "messages", "stream"}
    assert "authorization" not in hit["headers"]


async def test_usage_the_provider_does_not_send_stays_unknown(llm: FakeLlm) -> None:
    llm.script = [
        (200, completion("a", usage=None)),
        (
            200,
            completion(
                "b", usage={"prompt_tokens": 3, "completion_tokens": "x", "total_tokens": True}
            ),
        ),
        (200, completion("c", usage={"prompt_tokens": -1})),
    ]
    first = await client.complete(_endpoint(llm), "small", MESSAGES, timeout=5)
    second = await client.complete(_endpoint(llm), "small", MESSAGES, timeout=5)
    third = await client.complete(_endpoint(llm), "small", MESSAGES, timeout=5)
    assert first.usage() == {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    assert second.usage() == {"prompt_tokens": 3, "completion_tokens": None, "total_tokens": None}
    assert third.prompt_tokens is None


async def test_content_parts_are_joined_and_a_missing_content_is_empty(llm: FakeLlm) -> None:
    parts = completion()
    parts["choices"][0]["message"]["content"] = [
        {"type": "text", "text": "a"},
        {"type": "x"},
        {"text": "b"},
    ]
    none = completion()
    none["choices"][0]["message"]["content"] = None
    none["choices"][0]["finish_reason"] = 7
    llm.script = [(200, parts), (200, none)]
    assert (await client.complete(_endpoint(llm), "small", MESSAGES, timeout=5)).text == "ab"
    empty = await client.complete(_endpoint(llm), "small", MESSAGES, timeout=5)
    assert empty.text == "" and empty.finish_reason is None


@pytest.mark.parametrize(
    ("status", "transient", "text"),
    [
        (400, False, "HTTP 400: the provider rejected the request: bad"),
        (401, False, "HTTP 401: the provider did not accept the API key: bad"),
        (403, False, "HTTP 403: the provider refused the request (the key has no access): bad"),
        (404, False, "HTTP 404: not found (check the address and the model): bad"),
        (422, False, "HTTP 422: the provider rejected the request: bad"),
        (408, True, "HTTP 408: the provider timed out: bad"),
        (429, True, "HTTP 429: rate limited: bad"),
        (500, True, "HTTP 500: the provider failed: bad"),
        (503, True, "HTTP 503: the provider failed: bad"),
    ],
)
async def test_a_refusal_says_what_happened_and_whether_trying_again_can_help(
    llm: FakeLlm, status: int, transient: bool, text: str
) -> None:
    llm.script = [(status, {"error": {"message": "bad"}}, {"Retry-After": "7"})]
    with pytest.raises(ProviderError) as caught:
        await client.complete(_endpoint(llm), "small", MESSAGES, timeout=5)
    error = caught.value
    assert (error.message, error.status, error.transient, error.retry_after) == (
        text,
        status,
        transient,
        7.0,
    )


async def test_an_error_reported_inside_a_success_is_an_error(llm: FakeLlm) -> None:
    llm.script = [
        (200, {"error": {"message": "overloaded", "code": 529}}),
        (200, {"error": "something\x00odd\n" + "x" * 400}),
        (200, {"error": {"message": "quota", "code": 402}}),
    ]
    with pytest.raises(ProviderError) as first:
        await client.complete(_endpoint(llm), "small", MESSAGES, timeout=5)
    assert (first.value.status, first.value.transient) == (529, True)
    with pytest.raises(ProviderError) as second:
        await client.complete(_endpoint(llm), "small", MESSAGES, timeout=5)
    assert second.value.status == 502 and "\x00" not in second.value.message
    assert len(second.value.message) < 340
    with pytest.raises(ProviderError) as third:
        await client.complete(_endpoint(llm), "small", MESSAGES, timeout=5)
    assert (third.value.status, third.value.transient) == (402, False)


@pytest.mark.parametrize(
    "body", [b"<html>ok</html>", {"choices": []}, {"choices": ["x"]}, {"data": 1}, [1]]
)
async def test_an_answer_that_is_not_a_chat_completion_is_incompatible(
    llm: FakeLlm, body: Any
) -> None:
    llm.script = [(200, body)]
    with pytest.raises(IncompatibleError, match="not an OpenAI-compatible chat completion"):
        await client.complete(_endpoint(llm), "small", MESSAGES, timeout=5)


async def test_models_are_listed_with_their_labels(llm: FakeLlm) -> None:
    assert await client.list_models(_endpoint(llm)) == [("small", "Small model"), ("large", "")]
    assert llm.hits[0]["path"] == "/v1/models"


async def test_an_endpoint_without_a_model_list_says_so(llm: FakeLlm) -> None:
    with pytest.raises(NoModelListError) as caught:
        await client.list_models(_endpoint(llm, "/nomodels"))
    assert caught.value.status == 404


@pytest.mark.parametrize(
    "models", [{"data": [{"name": "x"}]}, {"data": "x"}, {"models": []}, [], {"data": [{"id": ""}]}]
)
async def test_a_model_list_in_another_shape_is_incompatible(llm: FakeLlm, models: Any) -> None:
    llm.models = models
    with pytest.raises(IncompatibleError):
        await client.list_models(_endpoint(llm))


async def test_a_web_page_is_not_a_model_list_and_a_refused_key_is_an_error(llm: FakeLlm) -> None:
    with pytest.raises(IncompatibleError):
        await client.list_models(_endpoint(llm, "/html"))
    with pytest.raises(ProviderError, match="HTTP 401") as caught:
        await client.list_models(_endpoint(llm, "/denied"))
    assert not isinstance(caught.value, IncompatibleError | NoModelListError)


async def test_the_key_check_accepts_refuses_and_rejects_another_shape(llm: FakeLlm) -> None:
    await client.check_key(_endpoint(llm))
    llm.key_status = 401
    with pytest.raises(ProviderError, match="HTTP 401"):
        await client.check_key(_endpoint(llm))
    with pytest.raises(IncompatibleError):
        await client.check_key(_endpoint(llm, "/html"))


# ── the guarded path ─────────────────────────────────────────────────


async def test_a_private_address_is_refused_unless_it_is_allowed(llm: FakeLlm) -> None:
    with pytest.raises(ProviderError, match="private network address") as caught:
        await client.complete(_endpoint(llm, private=False), "small", MESSAGES, timeout=5)
    assert caught.value.transient is False and llm.hits == []


async def test_a_metadata_address_is_refused_even_when_private_ones_are_allowed() -> None:
    endpoint = Endpoint("http://169.254.169.254/v1", None, True)
    with pytest.raises(ProviderError, match="cloud metadata address"):
        await client.list_models(endpoint, timeout=2)


async def test_a_name_that_resolves_to_an_internal_address_is_refused(
    monkeypatch: pytest.MonkeyPatch, llm: FakeLlm
) -> None:
    async def resolve(host: str, port: int) -> list[Any]:
        import ipaddress

        return [ipaddress.ip_address("93.184.216.34"), ipaddress.ip_address("10.0.0.5")]

    monkeypatch.setattr(http_runner, "_resolve", resolve)
    with pytest.raises(ProviderError, match="private network address"):
        await client.list_models(Endpoint(f"http://llm.example:{llm.port}/v1"), timeout=2)
    assert llm.hits == []


async def test_a_redirect_is_not_followed(llm: FakeLlm) -> None:
    with pytest.raises(ProviderError, match="HTTP 302"):
        await client.list_models(_endpoint(llm, "/redirect"))
    assert len(llm.hits) == 1  # the metadata address in Location was never asked


@pytest.mark.parametrize(
    "url", ["ftp://x/v1", "http://user:pw@127.0.0.1/v1", "http:///v1", "not a url"]
)
async def test_an_address_that_cannot_be_used_is_refused_without_a_request(url: str) -> None:
    with pytest.raises(ProviderError, match="The address of the provider is not valid") as caught:
        await client.list_models(Endpoint(url, API_KEY, True), timeout=2)
    assert API_KEY not in caught.value.message and "pw" not in caught.value.message


async def test_a_closed_port_is_a_failure_that_can_pass() -> None:
    with fake_llm() as gone:
        url = gone.url()
    with pytest.raises(ProviderError, match="The connection failed") as caught:
        await client.list_models(Endpoint(url, None, True), timeout=2)
    assert caught.value.transient is True


async def test_an_answer_larger_than_the_limit_is_refused(llm: FakeLlm) -> None:
    llm.script = [(200, completion("x" * 5000))]
    with pytest.raises(ProviderError, match="larger than the limit"):
        await client.complete(_endpoint(llm), "small", MESSAGES, timeout=5, limit=1000)


async def test_a_slow_answer_is_a_timeout_that_can_pass(llm: FakeLlm) -> None:
    llm.script = [(200, completion(), None, 1.5)]
    with pytest.raises(ProviderError, match="Timeout") as caught:
        await client.complete(_endpoint(llm), "small", MESSAGES, timeout=0.3)
    assert caught.value.transient is True


def test_retry_after_is_seconds_or_a_date_and_bounded() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert retry_after_seconds("12") == 12.0
    assert retry_after_seconds(" 1.5 ") == 1.5
    assert retry_after_seconds("99999") == 3600.0
    assert retry_after_seconds("Thu, 01 Jan 2026 12:00:30 GMT", now) == 30.0
    assert retry_after_seconds("Thu, 01 Jan 2026 11:00:00 GMT", now) == 0.0
    assert retry_after_seconds("Thu, 01 Jan 2026 12:00:30", now) == 30.0
    assert retry_after_seconds("soon") is None
    assert retry_after_seconds(None) is None and retry_after_seconds("") is None


def test_an_error_without_a_usable_body_still_has_a_text() -> None:
    assert status_error(500, None).message == "HTTP 500: the provider failed"
    assert (
        status_error(418, {"error": {"message": 1}}).message
        == "HTTP 418: the provider rejected the request"
    )
    assert status_error(429, {}, None).retry_after is None


# ── retries and time limits ──────────────────────────────────────────


class Scripted:
    """A stand-in for ``client.complete`` and ``asyncio.sleep``: the outcomes in order, the waits recorded."""

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.waits: list[float] = []

    async def complete(
        self, endpoint: Endpoint, model: str, messages: Any, **more: Any
    ) -> Completion:
        self.calls.append({"model": model, "messages": messages, **more})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, float | int):
            await asyncio.sleep(outcome)
            return OK
        return outcome  # type: ignore[no-any-return]

    async def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)


OK = Completion("Fine", "stop", 5, 2, 7, 200)
ENDPOINT = Endpoint("https://llm.example/v1", "key")


def _transient(status: int | None = 503, retry_after: float | None = None) -> ProviderError:
    return ProviderError(
        f"HTTP {status}: down" if status else "The connection failed",
        status=status,
        transient=True,
        retry_after=retry_after,
    )


async def _run(script: Scripted, **settings: Any) -> runtime.Outcome:
    return await run_completion(
        ENDPOINT, "small", MESSAGES, complete=script.complete, sleep=script.sleep, **settings
    )


async def test_the_first_answer_ends_the_request() -> None:
    script = Scripted(OK)
    outcome = await _run(script, temperature=0.1, max_tokens=9)
    assert outcome.completion is OK and outcome.error is None and outcome.http_status == 200
    assert len(outcome.attempts) == 1 and script.waits == []
    attempt = outcome.attempts[0].to_data()
    assert (
        attempt["number"],
        attempt["http_status"],
        attempt["error"],
        attempt["wait_seconds"],
    ) == (1, 200, None, None)
    assert attempt["started_at"].endswith("Z")
    assert script.calls[0]["temperature"] == 0.1 and script.calls[0]["max_tokens"] == 9
    assert script.calls[0]["timeout"] == 60


async def test_failures_that_can_pass_are_retried_with_the_agreed_waits() -> None:
    script = Scripted(_transient(None), _transient(500), _transient(408), _transient(502), OK)
    outcome = await _run(script, retries=4)
    assert outcome.completion is OK
    assert script.waits == [3.0, 10.0, 30.0, 60.0] == list(BACKOFF_SECONDS)
    assert [a.http_status for a in outcome.attempts] == [None, 500, 408, 502, 200]
    assert [a.wait_seconds for a in outcome.attempts] == [3.0, 10.0, 30.0, 60.0, None]
    assert outcome.attempts[0].error == "The connection failed"


async def test_the_default_is_three_retries_and_then_the_node_gives_up() -> None:
    script = Scripted(*[_transient(503) for _ in range(6)])
    outcome = await _run(script)
    assert outcome.completion is None and len(outcome.attempts) == 4
    assert outcome.error == "HTTP 503: down (gave up after 4 attempts)"
    assert outcome.http_status == 503 and script.waits == [3.0, 10.0, 30.0]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_a_permanent_failure_is_not_retried(status: int) -> None:
    script = Scripted(ProviderError(f"HTTP {status}: no", status=status), OK)
    outcome = await _run(script, retries=4)
    assert outcome.completion is None and len(outcome.attempts) == 1 and script.waits == []
    assert outcome.error == f"HTTP {status}: no" and outcome.http_status == status


async def test_no_retries_means_one_attempt() -> None:
    script = Scripted(_transient(503), OK)
    outcome = await _run(script, retries=0)
    assert outcome.error == "HTTP 503: down" and len(outcome.attempts) == 1 and script.waits == []


async def test_more_retries_than_allowed_are_cut_to_four() -> None:
    script = Scripted(*[_transient(503) for _ in range(9)])
    outcome = await _run(script, retries=99)
    assert len(outcome.attempts) == 5


async def test_retry_after_of_a_429_replaces_the_wait() -> None:
    script = Scripted(_transient(429, retry_after=42.0), _transient(503, retry_after=99.0), OK)
    outcome = await _run(script)
    assert script.waits == [42.0, 10.0]  # only a 429 says how long to wait
    assert outcome.attempts[0].retry_after == 42.0 and outcome.attempts[1].retry_after is None


async def test_a_wait_that_does_not_fit_the_time_limit_ends_the_node() -> None:
    script = Scripted(_transient(429, retry_after=120.0), OK)
    outcome = await _run(script, total_timeout=60)
    assert outcome.completion is None and script.waits == [] and len(outcome.attempts) == 1
    assert outcome.error == (
        "HTTP 429: down; not tried again: the wait of 120 s does not fit the time limit of 60 s"
    )


async def test_the_time_limit_of_the_node_bounds_every_attempt() -> None:
    script = Scripted(5.0, OK)
    outcome = await _run(script, request_timeout=30, total_timeout=0.2, retries=2)
    assert outcome.completion is None and len(outcome.attempts) == 1
    assert script.calls[0]["timeout"] <= 0.2
    assert "Timeout after 0.2" in (outcome.error or "") and "does not fit the time limit" in (
        outcome.error or ""
    )
    assert outcome.duration < 2


async def test_an_attempt_that_takes_too_long_is_a_timeout_and_is_retried() -> None:
    script = Scripted(5.0, OK)
    outcome = await _run(script, request_timeout=0.1, total_timeout=30)
    assert outcome.completion is OK and script.waits == [3.0]
    assert (
        outcome.attempts[0].error == "Timeout after 0.1 s"
        and outcome.attempts[0].http_status is None
    )


async def test_time_that_runs_out_while_waiting_ends_the_node() -> None:
    script = Scripted(_transient(429, retry_after=0.1), OK)

    async def oversleep(seconds: float) -> None:  # the wait fitted, but took longer than announced
        script.waits.append(seconds)
        await asyncio.sleep(0.5)

    outcome = await run_completion(
        ENDPOINT, "small", MESSAGES, complete=script.complete, sleep=oversleep, total_timeout=0.3
    )
    assert outcome.completion is None and script.waits == [0.1] and len(script.calls) == 1
    assert outcome.error == "HTTP 429: down; the time limit of 0.3 s is over"


async def test_stopping_the_run_ends_a_wait_at_once() -> None:
    script = Scripted(_transient(503), OK)
    started = asyncio.Event()

    async def real_sleep(seconds: float) -> None:
        started.set()
        await asyncio.sleep(seconds)

    task = asyncio.create_task(
        run_completion(ENDPOINT, "small", MESSAGES, complete=script.complete, sleep=real_sleep)
    )
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(script.calls) == 1


async def test_against_a_real_server_a_429_is_retried_and_then_answered(llm: FakeLlm) -> None:
    llm.script = [(429, {"error": {"message": "slow down"}}, {"Retry-After": "2"}), (500, b"oops")]
    script = Scripted()
    outcome = await run_completion(
        _endpoint(llm), "small", MESSAGES, sleep=script.sleep, request_timeout=5
    )
    assert outcome.completion is not None and outcome.completion.text == "Answer to: Hi"
    assert script.waits == [2.0, 10.0]
    assert [a.http_status for a in outcome.attempts] == [429, 500, 200]
    assert outcome.attempts[0].error == "HTTP 429: rate limited: slow down"
    assert len(llm.completions()) == 3


# ── the node ─────────────────────────────────────────────────────────


def _frozen(**node: Any) -> dict[str, Any]:
    config = AgentConfig(
        system_prompt_enabled=True,
        system_prompt="You answer in ${input.lang}.",
        user_prompt="Ticket: ${input.ticket}",
        inputs=[InputSpec(name="ticket", required=True), InputSpec(name="lang", default="English")],
        provider_id="p1",
        model="small",
        temperature=0.4,
        max_tokens=256,
        retries=1,
    ).model_dump()
    providers = {
        "p1": ProviderInfo(
            "p1",
            "openai_compatible",
            "Local",
            "https://llm.example/v1",
            "LLM_KEY",
            True,
            "small",
            True,
            frozenset({"small", "large"}),
        )
    }
    agent = {"id": "a1", "name": "Triage", "active": True, "version": 3, "config": config}
    node_config = {"agent_id": "a1", "inputs": "ticket = ${var.ticket}", **node}
    return {
        "id": "n1",
        "name": "Ask",
        "kind": "agent",
        "config": node_config,
        "agent": freeze(agent, node_config, providers),
    }


VIEW = RunView(RunContext({"vars": {"ticket": "Login is broken"}}), NodeIndex())


async def test_the_node_fills_the_prompts_calls_the_model_and_returns_the_answer() -> None:
    script = Scripted(OK)
    result = await run_node(_frozen(), VIEW, "key", complete=script.complete, sleep=script.sleep)
    assert (result.outcome, result.output, result.reason) == ("pass", "Fine", None)
    assert result.data == {
        "agent_id": "a1",
        "agent_version": 3,
        "provider": "Local",
        "model": "small",
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        "finish_reason": "stop",
        "attempts": 1,
        "iterations": 1,
    }
    call = script.calls[0]
    assert call["messages"] == [
        {"role": "system", "content": "You answer in English."},
        {"role": "user", "content": "Ticket: Login is broken"},
    ]
    assert (call["model"], call["temperature"], call["max_tokens"]) == ("small", 0.4, 256)
    detail = result.detail or {}
    assert detail["agent"] == {"id": "a1", "name": "Triage", "version": 3}
    assert detail["provider"] == {"id": "p1", "name": "Local", "kind": "openai_compatible"}
    assert detail["system_prompt"] == "You answer in English."
    assert detail["user_prompt"] == "Ticket: Login is broken"
    assert detail["overrides"] == {}
    assert (
        detail["settings"]["retries"] == 1 and detail["settings"]["request_timeout_seconds"] == 60
    )
    assert [(i["name"], i["state"], i["value"]) for i in detail["inputs"]] == [
        ("ticket", "mapped", "Login is broken"),
        ("lang", "default", "English"),
    ]
    assert len(detail["attempts"]) == 1 and detail["usage"]["total_tokens"] == 7
    assert "key" not in str(detail)


async def test_the_overrides_of_the_node_take_effect_and_are_recorded() -> None:
    script = Scripted(OK)
    node = _frozen(
        system_prompt_enabled=False,
        user_prompt="Short: ${input.ticket}",
        model="large",
        temperature=0,
        max_tokens=10,
    )
    result = await run_node(node, VIEW, None, complete=script.complete, sleep=script.sleep)
    call = script.calls[0]
    assert call["messages"] == [{"role": "user", "content": "Short: Login is broken"}]
    assert (call["model"], call["temperature"], call["max_tokens"]) == ("large", 0, 10)
    assert (result.detail or {})["overrides"] == {
        "system_prompt_enabled": False,
        "user_prompt": "Short: ${input.ticket}",
        "model": "large",
        "temperature": 0,
        "max_tokens": 10,
    }
    assert (result.detail or {})["system_prompt"] is None


@pytest.mark.parametrize(
    ("node", "view", "reason"),
    [
        ({"inputs": ""}, VIEW, "required input 'ticket' is not mapped"),
        (
            {"inputs": "ticket = ${var.missing}"},
            VIEW,
            "${var.missing}: variable 'missing' is not set",
        ),
        ({"inputs": "ticket"}, VIEW, "Input mapping: Line 1 is not 'name = value'"),
        ({"inputs": "ticket = x\nother = y"}, VIEW, "input 'other' is not declared by the agent"),
        ({"user_prompt": "${input.unknown}"}, VIEW, "${input.unknown} is not a declared input"),
        ({"user_prompt": "   "}, VIEW, "The user prompt is empty"),
    ],
)
async def test_a_node_that_cannot_build_its_request_fails_without_asking_the_model(
    node: dict[str, Any], view: RunView, reason: str
) -> None:
    script = Scripted(OK)
    result = await run_node(
        _frozen(**node), view, "key", complete=script.complete, sleep=script.sleep
    )
    assert result.outcome == "fail" and result.reason == reason
    assert script.calls == []
    assert (result.data or {})["attempts"] == 0 and (result.detail or {})["attempts"] == []


async def test_a_frozen_error_and_a_missing_agent_fail_with_their_reason() -> None:
    node = _frozen()
    node["agent"]["error"] = 'Agent "Triage" is inactive'
    result = await run_node(node, VIEW, "key")
    assert (result.outcome, result.reason) == ("fail", 'Agent "Triage" is inactive')
    assert result.data == {"agent_id": "a1", "agent_version": 3}
    old = {
        "id": "n",
        "name": "Ask",
        "kind": "agent",
        "config": {},
    }  # a snapshot of before agents existed
    assert (await run_node(old, VIEW, None)).reason == "This execution has no agent for the node"


async def test_a_failed_request_fails_the_node_with_every_attempt_recorded() -> None:
    script = Scripted(
        _transient(429, retry_after=1.0),
        ProviderError("HTTP 401: the provider did not accept the API key", status=401),
    )
    result = await run_node(_frozen(), VIEW, "key", complete=script.complete, sleep=script.sleep)
    assert result.outcome == "fail"
    assert result.reason == "HTTP 401: the provider did not accept the API key"
    assert (result.data or {})["status"] == 401 and (result.data or {})["attempts"] == 2
    assert (result.data or {})["usage"] is None
    attempts = (result.detail or {})["attempts"]
    assert [(a["http_status"], a["wait_seconds"]) for a in attempts] == [(429, 1.0), (401, None)]


async def test_an_empty_answer_fails_and_a_cut_or_long_answer_is_noted() -> None:
    empty = Completion("  ", "content_filter", 1, 0, 1, 200)
    result = await run_node(_frozen(), VIEW, "key", complete=Scripted(empty).complete)
    assert result.outcome == "fail"
    assert result.reason == "The model returned no text (finish reason: content_filter)"
    assert (result.data or {})["usage"] == {
        "prompt_tokens": 1,
        "completion_tokens": 0,
        "total_tokens": 1,
    }
    nothing = Completion("", None, None, None, None, 200)
    assert (
        await run_node(_frozen(), VIEW, "key", complete=Scripted(nothing).complete)
    ).reason == "The model returned no text"
    cut = Completion("x" * 5000, "length", None, None, None, 200)
    result = await run_node(_frozen(), VIEW, "key", complete=Scripted(cut).complete)
    assert result.outcome == "pass" and len(result.output) == 5000
    assert result.reason is not None
    assert "the model stopped at its token limit" in result.reason
    assert "longer than the 4 KiB the run context keeps" in result.reason
    assert (result.data or {})["usage"] == {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
    }


def test_openrouter_has_a_fixed_public_address_and_another_provider_may_be_local() -> None:
    openrouter = {"kind": "openrouter", "base_url": "http://evil.example", "allow_http": True}
    assert endpoint_of(openrouter, "k") == Endpoint("https://openrouter.ai/api/v1", "k", False)
    custom = {"kind": "openai_compatible", "base_url": "http://10.0.0.5/v1", "allow_http": True}
    assert endpoint_of(custom, None).allow_private is True  # an address is an address
    assert endpoint_of(custom, None).url("/models") == "http://10.0.0.5/v1/models"


async def test_an_http_provider_without_the_tick_is_refused_before_any_request() -> None:
    """A snapshot of a provider whose http address was never confirmed sends nothing (the key and
    the prompts would travel unencrypted)."""
    node = _frozen()
    node["agent"]["provider"].update(base_url="http://10.0.0.5/v1", allow_http=False)
    script = Scripted(OK)
    result = await run_node(node, VIEW, "key", complete=script.complete, sleep=script.sleep)
    assert result.outcome == "fail" and result.reason == UNENCRYPTED_REFUSED
    assert script.calls == []
