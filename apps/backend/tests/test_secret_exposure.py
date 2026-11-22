"""End to end: a secret a node used appears in no response, no event, no snapshot and not in the database file.

An HTTP node sends ``Authorization: Bearer ${secret:TOKEN}`` to a local server that echoes the header
back (in the body and in a response header), and a Code node prints its secret. Afterwards every read
endpoint, every event frame and the raw database files are searched for the value in all the forms
``forms_of`` knows (as it is, percent-encoded, Base64, JSON-escaped).
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Generator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.secret_refs import forms_of
from tests.helpers import build_pipeline, make_task, wait_for_run
from tests.test_execution_nodes import _definition, _start, _use

API_TOKEN = "exposure-api-token-" + "x" * 20
KEY = "k" * 40
HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}
PLAIN = "pl4intext-Secret/with+odd chars&="


class _Echo(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        auth = self.headers.get("Authorization", "")
        reply = json.dumps({"auth": auth, "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Echo", auth)  # an echoed header ends up in no stored field either
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def echo() -> Iterator[int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def secured(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(
        update={"api_token": API_TOKEN, "secret_key": KEY, "http_allow_private_networks": True}
    )
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


class _Frames:
    """The frames of the real ``GET /api/events`` endpoint, read through the ASGI interface."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.frames: list[str] = []
        self._first = threading.Event()
        self._stop: asyncio.Event | None = None
        self._done: Any = None

    def __enter__(self) -> _Frames:
        async def start() -> None:
            self._stop = asyncio.Event()

        portal = self.client.portal
        assert portal is not None
        portal.call(start)
        self._done = portal.start_task_soon(self._consume)
        assert self._first.wait(10), "the event stream did not start"
        return self

    async def _consume(self) -> None:
        assert self._stop is not None
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/events",
            "raw_path": b"/api/events",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"authorization", HEADERS["Authorization"].encode()),
            ],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 80),
        }

        async def receive() -> dict[str, Any]:
            assert self._stop is not None
            await self._stop.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.body" and message.get("body"):
                self.frames.append(message["body"].decode())
                self._first.set()

        await self.client.app(scope, receive, send)  # type: ignore[arg-type]

    def __exit__(self, *exc: object) -> None:
        async def stop() -> None:
            assert self._stop is not None
            self._stop.set()

        assert self.client.portal is not None
        self.client.portal.call(stop)
        self._done.result(10)


def _everywhere_plain(texts: dict[str, str], value: str) -> list[str]:
    """The names of the texts that hold the value in any of its forms."""
    return [name for name, text in texts.items() if any(form in text for form in forms_of(value))]


def test_a_used_secret_appears_in_no_response_event_or_database_file(
    secured: TestClient, migrated_settings: Settings, echo: int
) -> None:
    assert secured.put("/api/secrets/TOKEN", json={"value": PLAIN}).status_code == 201
    pipeline, task = build_pipeline(secured, stages=2), make_task(secured, "Exposed")
    http = _definition(
        secured,
        "http",
        method="POST",
        url=f"http://127.0.0.1:{echo}/x?k=${{secret:TOKEN}}",
        headers="Authorization: Bearer ${secret:TOKEN}",
        body="${secret:TOKEN}",
    )
    code = _definition(
        secured, "code", language="sh", code='echo "$TOKEN" >&2; echo "$TOKEN"', secrets="TOKEN"
    )
    _use(secured, pipeline, http)
    second = pipeline["stages"][1][1]
    secured.patch(
        f"/api/pipelines/{pipeline['id']}/nodes/{second['id']}", json={"definition_id": code["id"]}
    )

    with _Frames(secured) as stream:
        _start(secured, pipeline, task)
        run = wait_for_run(secured, task, "done")
        assert run["status"] == "done"

    executions = secured.get(f"/api/tasks/{task['id']}/executions").json()
    execution = executions["items"][0]
    base = f"/api/tasks/{task['id']}/executions/{execution['id']}"
    detail = secured.get(base).json()
    assert [
        (s["kind"], s["outcome"]) for s in detail["steps"] if s["kind"] in ("http", "code")
    ] == [
        ("http", "pass"),
        ("code", "pass"),
    ]
    step_urls = [f"{base}/steps/{s['id']}" for s in detail["steps"]]
    paths = [
        "/api/tasks",
        f"/api/tasks/{task['id']}",
        f"/api/tasks/{task['id']}/executions",
        base,
        f"{base}/flow",
        f"{base}/flow?outputs=true",
        *step_urls,
        "/api/executions",
        "/api/runs",
        f"/api/runs/{task['id']}/results",
        "/api/secrets",
        "/api/secrets/TOKEN/uses",
        "/api/v1/secrets",
        "/api/v1/artifacts",
        f"/api/v1/artifacts/{task['id']}/run/results",
        f"/api/pipelines/{pipeline['id']}",
        f"/api/actions/{http['id']}",
        f"/api/actions/{code['id']}",
    ]
    texts: dict[str, str] = {}
    for path in paths:
        response = secured.get(path)
        assert response.status_code == 200, (path, response.text)
        texts[path] = response.text
    texts["sse"] = "".join(stream.frames)
    for name in ("data", "data-wal"):  # the database and its write-ahead log
        file = migrated_settings.data_dir / (
            migrated_settings.database_filename + ("-wal" if name == "data-wal" else "")
        )
        texts[file.name] = file.read_bytes().decode("latin-1") if file.exists() else ""

    # the test must be able to see what it is looking for: the echo really reached the node's output
    steps_text = "".join(texts[u] for u in step_urls)
    assert "Bearer ***" in steps_text
    assert "event: run.updated" in texts["sse"] and "event: execution.updated" in texts["sse"]
    assert _everywhere_plain(texts, PLAIN) == []
    # the references (names, never values) are what the stored graphs and snapshots hold
    assert "${secret:TOKEN}" in texts[f"/api/actions/{http['id']}"]


def test_the_value_is_not_found_in_a_failed_run_either(secured: TestClient, echo: int) -> None:
    """The server answers 500 and echoes the header: the failure reason and output are masked too."""
    assert secured.put("/api/secrets/TOKEN", json={"value": PLAIN}).status_code == 201
    pipeline, task = build_pipeline(secured, stages=1), make_task(secured, "Fails")
    http = _definition(
        secured,
        "http",
        method="POST",
        url=f"http://127.0.0.1:{echo}/x",
        headers="Authorization: Bearer ${secret:TOKEN}",
        success_status="418",
    )
    _use(secured, pipeline, http)
    _start(secured, pipeline, task)
    wait_for_run(secured, task, "failed")
    results = secured.get(f"/api/runs/{task['id']}/results")
    assert results.status_code == 200
    assert _everywhere_plain({"results": results.text}, PLAIN) == []
    assert "not an accepted status" in results.text
    assert "Bearer ***" in results.text
