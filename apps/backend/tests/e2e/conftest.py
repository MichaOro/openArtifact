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


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Everything below tests/e2e is an e2e test (excluded from the default run)."""
    for item in items:
        if "tests/e2e" in item.nodeid:
            item.add_marker(pytest.mark.e2e)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Migrate a temporary database and serve the application from it."""
    port = _free_port()
    env = {
        **os.environ,
        "OPENARTIFACT_DATA_DIR": str(tmp_path_factory.mktemp("data")),
        "OPENARTIFACT_HOST": "127.0.0.1",
        "OPENARTIFACT_PORT": str(port),
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


@pytest.fixture
def browser_context_args(browser_context_args: dict[str, Any]) -> dict[str, Any]:
    """Light theme, desktop size, no stored UI state."""
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 800},
        "color_scheme": "light",
    }


@pytest.fixture
def api(base_url: str) -> Iterator[httpx.Client]:
    """REST client; the board is emptied before each test."""
    with httpx.Client(base_url=base_url) as client:
        for task in client.get("/api/tasks").json():
            client.delete(f"/api/tasks/{task['id']}")
        yield client


@pytest.fixture
def board(page: Any, base_url: str, api: httpx.Client) -> Board:
    """The board page object, opened on an empty board."""
    return Board(page, base_url, api)
