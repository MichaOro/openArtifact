"""The executors of Code and HTTP nodes called directly: how they handle secrets and surprises."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import pytest

from openartifact.credentials.store import SecretResolveError
from openartifact.engine import executors
from openartifact.engine.executors import EXECUTORS, Limits
from openartifact.engine.results import NodeResult
from openartifact.models import NodeKind

SECRET = "hunter2-value"


def _http(url: str = "http://127.0.0.1:9/", **config: str) -> dict[str, Any]:
    return {"id": "n1", "config": {"url": url, "headers": "", "body": "", **config}}


def _code(secrets: str = "", code: str = "echo hi") -> dict[str, Any]:
    return {
        "id": "n2",
        "config": {"language": "bash", "code": code, "timeout_seconds": 5, "secrets": secrets},
    }


async def _resolver(names: Sequence[str]) -> dict[str, str]:
    known = {"TOKEN": SECRET}
    missing = [n for n in names if n not in known]
    if missing:
        raise SecretResolveError(f"Unknown secret: {missing[0]}")
    return {n: known[n] for n in names}


async def test_an_exception_in_the_node_is_reported_by_type_and_never_leaks_the_secret(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def explode(*args: Any, **kwargs: Any) -> NodeResult:
        raise RuntimeError(f"upstream said token {SECRET}")

    monkeypatch.setattr(executors, "run_http", explode)
    node = _http(headers="Authorization: Bearer ${secret:TOKEN}")
    with caplog.at_level(logging.DEBUG):
        result = await EXECUTORS[NodeKind.HTTP].run(node, Limits(secrets=_resolver))
    assert (result.outcome, result.reason) == ("fail", "The node failed (RuntimeError)")
    assert result.output == ""
    assert result.data is None
    assert SECRET not in caplog.text  # the exception text is neither logged nor returned
    assert SECRET not in repr(result)


async def test_a_result_that_echoes_the_secret_is_masked_in_output_reason_and_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def echo(*args: Any, **kwargs: Any) -> NodeResult:
        return NodeResult(
            "fail",
            output=f"got {SECRET}",
            reason=f"bad {SECRET}",
            data={"header": f"Bearer {SECRET}", "list": [SECRET], SECRET: 1},
        )

    monkeypatch.setattr(executors, "run_http", echo)
    result = await EXECUTORS[NodeKind.HTTP].run(
        _http(headers="X: ${secret:TOKEN}"), Limits(secrets=_resolver)
    )
    assert result.output == "got ***"
    assert result.reason == "bad ***"
    assert result.data == {"header": "Bearer ***", "list": ["***"], "***": 1}


async def test_without_a_secret_resolver_a_node_that_uses_a_secret_fails() -> None:
    result = await EXECUTORS[NodeKind.HTTP].run(
        _http(headers="X: ${secret:TOKEN}"), Limits(secrets=None)
    )
    assert (result.outcome, result.reason) == ("fail", "Secrets are not available")
    code = await EXECUTORS[NodeKind.CODE].run(_code("TOKEN"), Limits(secrets=None))
    assert (code.outcome, code.reason) == ("fail", "Secrets are not available")


async def test_a_node_without_secrets_does_not_need_a_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, str] | None] = []

    async def fake(config: dict[str, Any], **kwargs: Any) -> NodeResult:
        seen.append(kwargs["secrets"])
        return NodeResult("pass", output="ok")

    monkeypatch.setattr(executors, "run_http", fake)
    result = await EXECUTORS[NodeKind.HTTP].run(_http(), Limits(secrets=None))
    assert (result.outcome, result.output) == ("pass", "ok")
    assert seen == [{}]


async def test_an_unknown_secret_fails_the_node_with_the_resolver_message() -> None:
    result = await EXECUTORS[NodeKind.HTTP].run(
        _http(headers="X: ${secret:NOPE}"), Limits(secrets=_resolver)
    )
    assert (result.outcome, result.reason) == ("fail", "Unknown secret: NOPE")


async def test_a_malformed_secret_name_fails_a_code_node_without_starting_a_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def never(*args: Any, **kwargs: Any) -> NodeResult:
        raise AssertionError("the process must not start")

    monkeypatch.setattr(executors, "run_code", never)
    result = await EXECUTORS[NodeKind.CODE].run(_code("lower case!"), Limits(secrets=_resolver))
    assert result.outcome == "fail"
    assert result.reason == (
        "Each line is one secret name: capitals, digits and underscores, starting with a letter"
    )


async def test_a_malformed_secret_reference_fails_an_http_node_without_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def never(*args: Any, **kwargs: Any) -> NodeResult:
        raise AssertionError("no request may be sent")

    monkeypatch.setattr(executors, "run_http", never)
    result = await EXECUTORS[NodeKind.HTTP].run(
        _http(headers="X: ${secret:bad name}"), Limits(secrets=_resolver)
    )
    assert result.outcome == "fail"
    assert result.reason and "secret" in result.reason.lower()


async def test_code_nodes_are_refused_when_disabled_or_blocked_in_open_mode() -> None:
    disabled = await EXECUTORS[NodeKind.CODE].run(_code(), Limits(code_nodes_enabled=False))
    assert (disabled.outcome, disabled.reason) == ("fail", executors.CODE_DISABLED_REASON)
    blocked = await EXECUTORS[NodeKind.CODE].run(_code(), Limits(code_blocked_in_open_mode=True))
    assert (blocked.outcome, blocked.reason) == ("fail", executors.OPEN_MODE_CODE_REASON)
