"""Fixtures for the browser tests: a real server on a free port, a clean board per test."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.e2e.helpers import Board

BACKEND_DIR = Path(__file__).resolve().parents[2]
SECURED_TOKEN = "e2e-access-token-" + "x" * 24


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Everything below tests/e2e is an e2e test (excluded from the default run)."""
    for item in items:
        if "tests/e2e" in item.nodeid:
            item.add_marker(pytest.mark.e2e)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _serve(data_dir: Path, **settings: str) -> Iterator[str]:
    """Migrate a database in ``data_dir`` and serve the application from it on a free port.

    The environment is the shell's without any ``OPENARTIFACT_*`` variable, plus ``settings``.
    """
    port = _free_port()
    env = {
        **{k: v for k, v in os.environ.items() if not k.upper().startswith("OPENARTIFACT_")},
        "OPENARTIFACT_DATA_DIR": str(data_dir),
        "OPENARTIFACT_HOST": "127.0.0.1",
        "OPENARTIFACT_PORT": str(port),
        "OPENARTIFACT_CODE_NODES_WITHOUT_TOKEN": "true",  # the open-mode test servers run Code nodes
        **{f"OPENARTIFACT_{k.upper()}": v for k, v in settings.items()},
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
    )
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "openartifact.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--timeout-graceful-shutdown",
            "1",
            "--log-level",
            "warning",
        ],
        cwd=BACKEND_DIR,
        env=env,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            raise RuntimeError("the application did not start")
        yield url
    finally:
        server.terminate()
        server.wait(timeout=10)


@pytest.fixture(scope="session")
def base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """The application without an access token."""
    yield from _serve(tmp_path_factory.mktemp("data"))


@pytest.fixture(scope="session")
def secured_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A second application with an access token (``SECURED_TOKEN``) and its own database."""
    yield from _serve(
        tmp_path_factory.mktemp("secured"), api_token=SECURED_TOKEN, secret_key="k" * 40
    )


@pytest.fixture
def browser_context_args(browser_context_args: dict[str, Any]) -> dict[str, Any]:
    """Light theme, desktop size, no stored UI state."""
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 800},
        "color_scheme": "light",
    }


DEFAULT_LANES = (("backlog", "Backlog"), ("in_progress", "In Progress"), ("done", "Done"))


def _reset_lanes(client: httpx.Client) -> None:
    """Delete the lanes a test added, restore deleted default lanes (at the end) and their titles."""
    keys = [lane["status"] for lane in client.get("/api/lanes").json()]
    for key in keys:
        if key not in dict(DEFAULT_LANES):
            client.delete(f"/api/lanes/{key}").raise_for_status()
    for key, title in DEFAULT_LANES:
        if key not in keys:
            client.post("/api/lanes", json={"title": title}).raise_for_status()
    lanes = client.get("/api/lanes").json()
    if [(lane["status"], lane["title"]) for lane in lanes] != list(DEFAULT_LANES):
        for key, _ in DEFAULT_LANES:  # through temporary titles: the defaults may be swapped
            client.put(f"/api/lanes/{key}", json={"title": f"~{key}"}).raise_for_status()
        for key, title in DEFAULT_LANES:
            client.put(f"/api/lanes/{key}", json={"title": title}).raise_for_status()


@pytest.fixture
def api(base_url: str) -> Iterator[httpx.Client]:
    """REST client; the server is emptied before each test: runs stopped, artifacts, pipelines and
    action definitions deleted, the lanes back to the three defaults (the server lives for the whole session)."""
    with httpx.Client(base_url=base_url) as client:
        for task in client.get("/api/tasks").json():
            client.post(f"/api/tasks/{task['id']}/run/stop")  # 409 when nothing runs
            assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
        _reset_lanes(client)
        for path in ("/api/pipelines", "/api/actions"):
            for graph in client.get(path).json():
                assert client.delete(f"{path}/{graph['id']}").status_code == 204
        yield client


@pytest.fixture
def board(page: Any, base_url: str, api: httpx.Client) -> Board:
    """The board page object, opened on an empty board."""
    return Board(page, base_url, api)
