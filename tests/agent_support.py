"""A small OpenAI-compatible server for the agent tests, and the settings that let a test reach it.

``FakeLlm`` answers ``GET /v1/models`` and ``POST /v1/chat/completions`` (and ``GET /v1/key``, as
OpenRouter has it). ``script`` holds the next answers of the completion endpoint, one per request; when
it is empty the answer is a success that echoes the user's prompt. Other mounts behave differently:
``/nomodels/v1`` has no model list, ``/html/v1`` answers everything with a web page, ``/denied/v1``
refuses the key.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from fastapi.testclient import TestClient

TOKEN = "agent-test-token-" + "x" * 20
KEY = "k" * 40
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
API_KEY = "sk-test-1234567890-secret-key"
SECURE = {"api_token": TOKEN, "secret_key": KEY, "llm_allow_private_networks": True}
MODELS = [{"id": "small", "name": "Small model"}, {"id": "large"}]


def completion(
    text: str = "Hello", finish: str | None = "stop", usage: Any = "default"
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "x",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}
        ],
    }
    if usage == "default":
        body["usage"] = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    elif usage is not None:
        body["usage"] = usage
    return body


class FakeLlm:
    """The server and what it saw. ``script`` entries: ``(status, body)`` or
    ``(status, body, headers, delay_seconds)``; ``body`` is JSON data or raw bytes."""

    def __init__(self) -> None:
        self.script: list[tuple[Any, ...]] = []
        self.hits: list[dict[str, Any]] = []
        self.models: Any = {"data": MODELS}
        self.key_status = 200
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status: int, body: Any, headers: dict[str, str] | None = None) -> None:
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header(
                    "Content-Type", "text/html" if isinstance(body, bytes) else "application/json"
                )
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                hit: dict[str, Any] = {
                    "method": self.command,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "json": json.loads(raw) if raw else None,
                }
                fake.hits.append(hit)
                mount, _, rest = self.path.partition("/v1/")
                if mount == "/html":
                    return self._send(200, b"<html><body>Welcome</body></html>")
                if mount == "/denied":
                    return self._send(401, {"error": {"message": "Invalid API key", "code": 401}})
                if mount == "/redirect":
                    return self._send(302, b"", {"Location": "http://169.254.169.254/latest"})
                if rest == "models":
                    if mount == "/nomodels":
                        return self._send(404, {"error": {"message": "Not Found"}})
                    return self._send(200, fake.models)
                if rest == "key":
                    if fake.key_status != 200:
                        return self._send(fake.key_status, {"error": {"message": "No auth"}})
                    return self._send(200, {"data": {"label": "test", "usage": 0}})
                if rest == "chat/completions":
                    if fake.script:
                        status, body, *more = fake.script.pop(0)
                        headers = more[0] if more else None
                        if len(more) > 1:
                            time.sleep(more[1])
                        return self._send(status, body, headers)
                    prompt = hit["json"]["messages"][-1]["content"]
                    return self._send(200, completion(f"Answer to: {prompt}"))
                return self._send(404, {"error": {"message": "Not Found"}})

            do_GET = do_POST = _handle  # noqa: N815

            def log_message(self, *args: Any) -> None:
                pass

        class Quiet(ThreadingHTTPServer):
            def handle_error(self, request: Any, client_address: Any) -> None:
                pass  # a client that gave up (a timeout test) is not worth a traceback

        self._httpd = Quiet(("127.0.0.1", 0), Handler)
        self._httpd.block_on_close = False
        self.port = self._httpd.server_address[1]
        threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()

    def url(self, mount: str = "") -> str:
        return f"http://127.0.0.1:{self.port}{mount}/v1"

    def completions(self) -> list[dict[str, Any]]:
        return [h for h in self.hits if h["path"].endswith("/chat/completions")]

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


@contextmanager
def fake_llm() -> Iterator[FakeLlm]:
    server = FakeLlm()
    try:
        yield server
    finally:
        server.close()


def put_secret(client: TestClient, name: str = "LLM_KEY", value: str = API_KEY) -> None:
    response = client.put(f"/api/secrets/{name}", json={"value": value}, headers=HEADERS)
    assert response.status_code in (200, 201), response.text


def make_provider(client: TestClient, llm: FakeLlm, **changes: Any) -> dict[str, Any]:
    """A saved custom provider on the fake server: models fetched, ``small`` enabled and the default."""
    put_secret(client)
    body = {
        "kind": "openai_compatible",
        "name": "Local",
        "base_url": llm.url(),
        "secret_name": "LLM_KEY",
        "allow_http": True,
        "default_model": "small",
        "is_default": True,
        **changes,
    }
    response = client.post("/api/providers", json=body, headers=HEADERS)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def make_agent(
    client: TestClient, name: str = "Triage", publish: bool = True, **draft: Any
) -> dict[str, Any]:
    """An agent with one required input ``ticket`` and an optional ``context``; published by default."""
    config = {
        "user_prompt": "Analyse: ${input.ticket}\nContext: ${input.context}",
        "inputs": [
            {"name": "ticket", "required": True},
            {"name": "context", "default": "none"},
        ],
        **draft,
    }
    response = client.post("/api/agents", json={"name": name, "draft": config}, headers=HEADERS)
    assert response.status_code == 201, response.text
    agent = response.json()
    if publish:
        published = client.post(f"/api/agents/{agent['id']}/publish", headers=HEADERS)
        assert published.status_code == 200, published.text
        agent = published.json()["agent"]
    return agent  # type: ignore[no-any-return]
