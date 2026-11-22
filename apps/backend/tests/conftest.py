"""Shared test fixtures: isolated settings, a migrated database and a client with the real lifespan.

The database is migrated once per revision into a template file; every test gets a copy, so a test
costs milliseconds instead of running the migrations again. The templates live in a directory shared
by all pytest-xdist workers and are built under a file lock, so ``-n`` builds each one once per run.
Tests never see the developer's ``OPENARTIFACT_*`` environment or ``.env``.
"""

from __future__ import annotations

import asyncio
import fcntl
import gc
import logging
import os
import shutil
import sqlite3
import weakref
from collections.abc import Callable, Generator
from contextlib import closing
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

import openartifact.database as db_mod
from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import alembic_config


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever the developer has exported (a token, a data directory ...) must not change a test."""
    for name in [n for n in os.environ if n.upper().startswith("OPENARTIFACT_")]:
        monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def _restore_logging() -> Generator[None, None, None]:
    """``configure_logging`` (run by ``create_app``) changes shared loggers: put them back."""
    names = ("openartifact", "mcp", "httpx")
    saved = {
        n: (list(lg.handlers), lg.level, lg.propagate)
        for n in names
        if (lg := logging.getLogger(n))
    }
    yield
    for name, (handlers, level, propagate) in saved.items():
        logger = logging.getLogger(name)
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate


@pytest.fixture(autouse=True)
def clean_engine() -> Generator[None, None, None]:
    """No test starts or leaves a shared database engine behind."""

    def reset() -> None:
        if db_mod._engine is not None:
            asyncio.run(db_mod.dispose_engine())

    reset()
    yield
    reset()
    gc.collect()  # a leaked connection warns here, not in a random later test


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Provide settings pointing to a temporary directory (open mode, so Code nodes are opted in)."""
    return Settings(  # type: ignore[call-arg]
        data_dir=tmp_path,
        database_filename="test.db",
        code_nodes_without_token=True,  # open mode runs no Code nodes otherwise
        _env_file=None,
    )


@pytest.fixture
def app_routes() -> Callable[[Any], list[str]]:
    """Collect all route paths from a FastAPI app, including nested routers."""

    def _collect(app: Any) -> list[str]:
        paths: list[str] = []
        for route in app.routes:
            _find_paths(route, paths)
        return paths

    def _find_paths(route: Any, paths: list[str]) -> None:
        path = getattr(route, "path", None)
        if path is not None:
            paths.append(path)
            return

        # _IncludedRouter: access the included router's routes via include_context
        ctx = getattr(route, "include_context", None)
        if ctx is not None:
            inner_router = getattr(ctx, "included_router", None)
            if inner_router is not None:
                for subroute in getattr(inner_router, "routes", []):
                    _find_paths(subroute, paths)

    return _collect


def _checkpoint(path: Path) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


@pytest.fixture(scope="session")
def _revision_template(tmp_path_factory: pytest.TempPathFactory) -> Callable[[str], Path]:
    """``template(revision)``: a database migrated to that revision (``"head"`` is the newest).

    Built once per revision, on the nearest older template that already exists, so that a test of
    one migration step does not pay for all the steps before it. Under pytest-xdist the templates
    sit next to the worker directories and a lock file per revision makes the first worker build
    while the others wait.
    """
    base = tmp_path_factory.getbasetemp()
    root = (base.parent if os.environ.get("PYTEST_XDIST_WORKER") else base) / "revision-templates"
    root.mkdir(exist_ok=True)
    script = ScriptDirectory.from_config(alembic_config())
    order = [r.revision for r in reversed(list(script.walk_revisions()))]
    head = order[-1]

    def template(revision: str) -> Path:
        revision = head if revision == "head" else revision
        target = root / f"{revision}.db"
        with (root / f"{revision}.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if target.exists():
                return target
            older = [r for r in order[: order.index(revision)] if (root / f"{r}.db").exists()]
            work = root / f"{revision}.{os.getpid()}.building"
            if older:
                shutil.copy(root / f"{older[-1]}.db", work)
            with pytest.MonkeyPatch.context() as patch:
                patch.setenv("OPENARTIFACT_DATA_DIR", str(root))
                patch.setenv("OPENARTIFACT_DATABASE_FILENAME", work.name)
                command.upgrade(alembic_config(), revision)
            _checkpoint(work)
            for leftover in root.glob(f"{work.name}-*"):
                leftover.unlink()
            work.replace(target)
        return target

    return template


@pytest.fixture
def unmigrated_settings(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings for an empty temp database that alembic (which reads them from the environment)
    migrates: for tests that go to a revision, seed old data and go on."""
    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    return settings


@pytest.fixture
def at_revision(
    unmigrated_settings: Settings, _revision_template: Callable[[str], Path]
) -> Callable[[str], Path]:
    """``at_revision("0012")`` puts a copy of the database at that revision in place and returns its path;
    the test then runs only the step it is about."""
    path = unmigrated_settings.data_dir / unmigrated_settings.database_filename

    def put(revision: str) -> Path:
        shutil.copy(_revision_template(revision), path)
        return path

    return put


@pytest.fixture
def migrated_settings(
    unmigrated_settings: Settings, at_revision: Callable[[str], Path]
) -> Settings:
    """Settings pointing at a temp database with all migrations applied (a copy of the template)."""
    at_revision("head")
    return unmigrated_settings


@pytest.fixture(scope="session")
def _open_connections() -> Generator[weakref.WeakSet[aiosqlite.Connection], None, None]:
    """Every aiosqlite connection created in this process (weakly held)."""
    created: weakref.WeakSet[aiosqlite.Connection] = weakref.WeakSet()
    original = aiosqlite.Connection.__init__

    def remember(self: aiosqlite.Connection, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        created.add(self)

    aiosqlite.Connection.__init__ = remember  # type: ignore[method-assign]
    yield created
    aiosqlite.Connection.__init__ = original  # type: ignore[method-assign]


def _live(created: weakref.WeakSet[aiosqlite.Connection]) -> set[aiosqlite.Connection]:
    return {c for c in created if c._thread.is_alive()}


@pytest.fixture
def client(
    migrated_settings: Settings,
    request: pytest.FixtureRequest,
    _open_connections: weakref.WeakSet[aiosqlite.Connection],
) -> Generator[TestClient, None, None]:
    """Test client with the real lifespan (shared engine) on a migrated database.

    After the test no database connection may be alive: a leftover means something (a run, a task)
    kept using the engine after shutdown, and fails here, at its source, not in a later test.
    """
    before = _live(_open_connections)
    with TestClient(_create_app(migrated_settings)) as c:
        yield c
    assert db_mod._engine is None
    leaked = _live(_open_connections) - before
    for connection in leaked:
        connection._thread.join(
            timeout=2
        )  # closing is asynchronous: give the thread a moment to end
    if leaked:
        gc.collect()
        leaked = {c for c in leaked if c._thread.is_alive()}
    assert not leaked, (
        f"{request.node.nodeid} left {len(leaked)} aiosqlite connection(s) open after the client "
        "shut down: a background run or task still uses the engine"
    )


@pytest.fixture
def published(client: TestClient) -> list[tuple[str, dict[str, Any]]]:
    """Record everything the app publishes on its event bus."""
    events: list[tuple[str, dict[str, Any]]] = []
    bus = client.app.state.event_bus  # type: ignore[attr-defined]
    original = bus.publish

    def spy(event_type: str, data: dict[str, Any]) -> Any:
        events.append((event_type, data))
        return original(event_type, data)

    bus.publish = spy
    return events
