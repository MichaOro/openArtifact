"""The Start button of the Dry run tab is the Stop while a dry run runs (ADR-086 addendum 2).

A dry run skips every node that writes and does not wait for a timer, so what keeps one running is a node that only reads: an HTTP GET to a
local server that answers late. The application of this module is therefore served with the HTTP node allowed to reach the local network
(the shared test application is not)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import _serve
from tests.e2e.helpers import arrange, eventually
from tests.e2e.test_dry_run_tab import DIALOG, _choose_card, _dry_run_tab
from tests.helpers import build_pipeline, connect, kind_of, link, node, post


@pytest.fixture(scope="module")
def local_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    yield from _serve(tmp_path_factory.mktemp("dry-stop"), http_allow_private_networks="true")


@pytest.fixture
def api(local_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=local_url) as client:
        for task in client.get("/api/tasks").json():
            client.post(f"/api/tasks/{task['id']}/run/stop")  # 409 when nothing runs
            assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
        for path in ("/api/pipelines", "/api/actions"):
            for graph in client.get(path).json():
                assert client.delete(f"{path}/{graph['id']}").status_code == 204
        yield client


@pytest.fixture(scope="module")
def _slow_state() -> Iterator[dict[str, Any]]:
    """A local server whose answer comes only when the test lets it (or after 20 s): `release` is the event of the running test."""
    state: dict[str, Any] = {"release": threading.Event()}

    class Slow(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            state["release"].wait(20)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"late")

        def log_message(self, *args: Any) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{httpd.server_port}/slow"
    yield state
    state["release"].set()
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def slow_server(_slow_state: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """The slow server for one test: its answers wait for `release` of this test, and are let go when the test ends."""
    _slow_state["release"] = threading.Event()
    yield _slow_state
    _slow_state["release"].set()


def _reading_pipeline(api: httpx.Client, url: str) -> dict[str, Any]:
    """A pipeline whose one action GETs `url`: a read, so a dry run really does it."""
    pipeline = build_pipeline(api, stages=1, name="Reading", stage_name="Read stage")
    definition = post(api, "/api/actions", name="Read")
    trigger, output = kind_of(api, definition, "trigger"), kind_of(api, definition, "output")
    get = node(api, definition, "http", config={"method": "GET", "url": url})
    connect(api, definition, trigger, "out", get, "in")
    connect(api, definition, get, "pass", output, "pass")
    link(api, pipeline, pipeline["stages"][0][1], definition)
    arrange(api, pipeline)
    return pipeline


def test_the_start_button_is_the_stop_while_the_dry_run_runs_and_the_row_follows_it(
    page: Page, local_url: str, api: httpx.Client, slow_server: dict[str, Any]
) -> None:
    pipeline = _reading_pipeline(api, slow_server["url"])
    task = post(api, "/api/tasks", title="Test card", status="backlog")
    page.goto(f"{local_url}/pipelines/{pipeline['slug']}")
    page.locator(".ge-node--trigger").dblclick(position={"x": 20, "y": 5})
    panel = _dry_run_tab(page.locator(DIALOG))
    _choose_card(page, panel, "Test")
    panel.get_by_role("button", name="Start dry run").click()
    row = panel.locator(".ge-dry__runs .history-row")
    expect(row.locator(".history-chip")).to_have_text("Running")
    stop = panel.get_by_role("button", name="Stop processing")
    expect(stop).to_be_enabled()
    expect(panel.get_by_role("button", name="Start dry run")).to_have_count(0)
    stop.click()
    expect(row.locator(".history-chip")).to_have_text("Stopped")  # the row follows the run
    expect(panel.get_by_role("button", name="Start dry run")).to_be_enabled()
    expect(panel.get_by_role("button", name="Stop processing")).to_have_count(0)
    eventually(
        lambda: api.get(f"/api/tasks/{task['id']}/executions").json()["items"][0]["status"],
        "stopped",
    )


def test_the_row_and_the_button_follow_a_dry_run_to_its_end_without_a_reload(
    page: Page, local_url: str, api: httpx.Client, slow_server: dict[str, Any]
) -> None:
    pipeline = _reading_pipeline(api, slow_server["url"])
    post(api, "/api/tasks", title="Test card", status="backlog")
    page.goto(f"{local_url}/pipelines/{pipeline['slug']}")
    page.locator(".ge-node--trigger").dblclick(position={"x": 20, "y": 5})
    panel = _dry_run_tab(page.locator(DIALOG))
    _choose_card(page, panel, "Test")
    panel.get_by_role("button", name="Start dry run").click()
    row = panel.locator(".ge-dry__runs .history-row")
    expect(row.locator(".history-chip")).to_have_text("Running")
    expect(panel.get_by_role("button", name="Stop processing")).to_be_visible()
    slow_server[
        "release"
    ].set()  # the answer comes: the run ends by itself, nobody clicks and nothing is reloaded
    expect(row.locator(".history-chip")).to_have_text("Done")
    expect(panel.get_by_role("button", name="Start dry run")).to_be_enabled()
    expect(panel.get_by_role("button", name="Stop processing")).to_have_count(0)
