"""The Host check (HTTP and WebSocket, IPv6 literals) and the streamed body limit as ASGI middleware."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send
from starlette.websockets import WebSocketDisconnect

from openartifact.api.hardening import BodyLimit, HostCheck, _host_only
from openartifact.app import _create_app
from openartifact.config import Settings


@pytest.fixture
def make_client(migrated_settings: Settings) -> Generator[Callable[..., TestClient], None, None]:
    clients: list[TestClient] = []

    def make(**changes: Any) -> TestClient:
        client = TestClient(_create_app(migrated_settings.model_copy(update=changes)))
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in reversed(clients):
        client.__exit__(None, None, None)


# ── Host ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("header", "host"),
    [
        ("Example.org:2909", "example.org"),
        ("example.org", "example.org"),
        ("[::1]:2909", "[::1]"),
        ("[FD00::5]", "[fd00::5]"),
        ("  localhost:80 ", "localhost"),
        ("", ""),
    ],
)
def test_the_host_name_is_taken_without_the_port_and_keeps_ipv6_brackets(
    header: str, host: str
) -> None:
    assert _host_only(header) == host


def test_an_ipv6_literal_is_accepted_only_when_listed(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(allowed_hosts="[::1]")
    assert client.get("/api/tasks", headers={"Host": "[::1]:8000"}).status_code == 200
    assert client.get("/api/tasks", headers={"Host": "[::1]"}).status_code == 200
    assert client.get("/api/tasks", headers={"Host": "[::2]:1"}).status_code == 400
    assert client.get("/api/tasks", headers={"Host": "::1"}).status_code == 400  # not a host name


def test_a_websocket_with_a_foreign_host_is_closed_before_anything_else(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(allowed_hosts="board.example")
    with (
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect("/ws", headers={"Host": "evil.example"}),
    ):
        pass
    assert closed.value.code == 1008


async def _run(middleware: Any, scope: Scope, messages: list[Message]) -> list[Message]:
    """Drive a middleware with the client's ``messages``; return what it sent."""
    incoming = iter(messages)
    sent: list[Message] = []

    async def receive() -> Message:
        return next(incoming, {"type": "http.disconnect"})

    async def send(message: Message) -> None:
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


def _scope(kind: str = "http", *, host: str = "x", path: str = "/", **extra: Any) -> Scope:
    return {
        "type": kind,
        "path": path,
        "method": "POST",
        "headers": [(b"host", host.encode()), *extra.pop("headers", [])],
        **extra,
    }


async def test_a_websocket_of_an_allowed_host_reaches_the_application_and_a_foreign_one_does_not() -> (
    None
):
    reached: list[str] = []

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        reached.append(scope["type"])

    check = HostCheck(application, ["board.example"])
    assert await _run(check, _scope("websocket", host="board.example"), []) == []
    assert await _run(check, _scope("websocket", host="evil.example"), []) == [
        {"type": "websocket.close", "code": 1008}
    ]
    assert reached == ["websocket"]


async def test_the_health_path_and_other_scope_types_skip_the_host_check() -> None:
    reached: list[str] = []

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        reached.append(scope["type"] + scope.get("path", ""))

    check = HostCheck(application, ["board.example"])
    await _run(check, _scope(host="evil", path="/health"), [])
    await _run(check, {"type": "lifespan"}, [])
    assert reached == ["http/health", "lifespan"]


# ── streamed body ─────────────────────────────────────────────────────────────


def _chunks(*sizes: int) -> list[Message]:
    return [
        {"type": "http.request", "body": b"x" * size, "more_body": i < len(sizes) - 1}
        for i, size in enumerate(sizes)
    ]


async def test_a_streamed_body_above_the_limit_gets_413_when_the_application_has_not_answered() -> (
    None
):
    async def reads_all(scope: Scope, receive: Receive, send: Send) -> None:
        while (await receive())["type"] == "http.request":
            pass

    sent = await _run(BodyLimit(reads_all, 100), _scope(), _chunks(60, 60))
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413


async def test_an_application_error_after_the_limit_is_exceeded_is_not_a_server_error() -> None:
    """The application sees the client leave and may raise; the answer is still the 413."""

    async def fails_on_disconnect(scope: Scope, receive: Receive, send: Send) -> None:
        while (await receive())["type"] == "http.request":
            pass
        raise RuntimeError("client went away")

    sent = await _run(BodyLimit(fails_on_disconnect, 100), _scope(), _chunks(60, 60))
    assert sent[0]["status"] == 413


async def test_an_application_error_within_the_limit_is_not_swallowed() -> None:
    async def fails(scope: Scope, receive: Receive, send: Send) -> None:
        await receive()
        raise RuntimeError("a real bug")

    with pytest.raises(RuntimeError, match="a real bug"):
        await _run(BodyLimit(fails, 100), _scope(), _chunks(10))


async def test_nothing_the_application_answers_after_the_limit_is_sent() -> None:
    async def answers_anyway(scope: Scope, receive: Receive, send: Send) -> None:
        while (await receive())["type"] == "http.request":
            pass
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"accepted"})

    sent = await _run(BodyLimit(answers_anyway, 100), _scope(), _chunks(60, 60))
    assert [m.get("status") for m in sent if m["type"] == "http.response.start"] == [413]
    assert b"accepted" not in b"".join(m.get("body", b"") for m in sent)


def test_a_chunked_body_above_the_limit_gets_413_and_the_server_stays_up(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(max_request_bytes=1024)

    def chunks() -> Generator[bytes, None, None]:
        for _ in range(4):
            yield b'{"title": "' + b"a" * 400 + b'"}'

    streamed = client.post(
        "/api/tasks", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert streamed.status_code == 413
    assert streamed.text == "The request is too large"
    assert client.get("/health").status_code == 200
