"""One process per data directory: the lock the lifespan holds (ADR-094)."""

from __future__ import annotations

import errno
import fcntl
import logging
import os
import signal
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Generator
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from openartifact import process_lock
from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.exceptions import ConfigurationError
from tests.helpers import build_pipeline, make_task, post, wait_for_run

ROOT = Path(__file__).resolve().parent.parent
REFUSED = r"is in use by another OpenArtifact process"

Holder = Callable[[Path], subprocess.Popen[str]]

# Holds the lock of the directory in argv[1] until it is killed or its stdin closes.
_HOLDER = """
import sys
from pathlib import Path
from openartifact.process_lock import hold
with hold(Path(sys.argv[1])):
    print("held", flush=True)
    sys.stdin.read()
"""


@pytest.fixture
def holder() -> Generator[Holder, None, None]:
    """``holder(dir)`` starts another process that holds the lock of ``dir``; all end afterwards."""
    started: list[subprocess.Popen[str]] = []

    def start(data_dir: Path) -> subprocess.Popen[str]:
        proc = subprocess.Popen(
            [sys.executable, "-c", _HOLDER, str(data_dir)],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        started.append(proc)
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "held"
        return proc

    yield start
    for proc in started:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)
        for stream in (proc.stdin, proc.stdout):
            if stream is not None:
                stream.close()


def test_a_second_process_is_refused_and_named_the_directory(
    tmp_path: Path, holder: Holder
) -> None:
    holder(tmp_path)
    with pytest.raises(ConfigurationError, match=REFUSED) as refused, process_lock.hold(tmp_path):
        pass
    assert str(tmp_path) in str(refused.value)
    assert (tmp_path / process_lock.LOCK_FILENAME).exists()


def test_the_lock_is_released_when_its_process_is_killed(tmp_path: Path, holder: Holder) -> None:
    proc = holder(tmp_path)
    with pytest.raises(ConfigurationError, match=REFUSED), process_lock.hold(tmp_path):
        pass
    os.kill(proc.pid, signal.SIGKILL)
    assert proc.wait(timeout=10) == -signal.SIGKILL
    with process_lock.hold(tmp_path):  # no stale lock: the kernel dropped it with the process
        pass


def test_the_descriptor_is_not_inherited_by_child_processes(tmp_path: Path) -> None:
    with process_lock.hold(tmp_path):
        (held,) = process_lock._held.values()
        assert not os.get_inheritable(held.fd)
    assert not process_lock._held


def test_applications_of_one_process_share_the_lock(tmp_path: Path, holder: Holder) -> None:
    """The invariant is one process: the in-process test apps share it, the lock stays until the last."""
    with process_lock.hold(tmp_path):
        with process_lock.hold(tmp_path):
            pass
        assert len(process_lock._held) == 1  # the outer one still holds it
        proc = subprocess.run(
            [sys.executable, "-c", _HOLDER, str(tmp_path)],
            cwd=ROOT,
            input="",
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode != 0 and REFUSED in proc.stderr
    assert not process_lock._held


def test_a_second_app_refuses_before_recovery_and_leaves_the_running_run_alone(
    migrated_settings: Settings, holder: Holder
) -> None:
    path = migrated_settings.data_dir / migrated_settings.database_filename
    with TestClient(_create_app(migrated_settings)) as first:
        pipeline = build_pipeline(first, stages=1)
        task = make_task(first)
        post(first, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
        wait_for_run(first, task, "done")
    with sqlite3.connect(path) as conn:  # the other process's run, still going
        conn.execute("UPDATE pipeline_runs SET status = 'running', note = NULL")
        conn.execute("UPDATE executions SET status = 'running', note = NULL, finished_at = NULL")
    conn.close()

    other = holder(migrated_settings.data_dir)
    with (
        pytest.raises(ConfigurationError, match=REFUSED),
        TestClient(_create_app(migrated_settings)),
    ):
        pass

    def states() -> list[tuple[str, str | None]]:
        with sqlite3.connect(path) as conn:
            rows = conn.execute("SELECT status, note FROM pipeline_runs").fetchall()
            rows += conn.execute("SELECT status, note FROM executions").fetchall()
        conn.close()
        return rows

    assert states() == [("running", None), ("running", None)]

    other.kill()
    other.wait(timeout=10)
    with TestClient(_create_app(migrated_settings)):  # without the other process, recovery runs
        pass
    assert states() == [("stopped", "Interrupted by restart")] * 2


def test_the_lock_is_released_after_shutdown_and_after_a_failed_startup(
    settings: Settings,
) -> None:
    with TestClient(_create_app(settings)):
        assert len(process_lock._held) == 1
    assert not process_lock._held
    with TestClient(_create_app(settings)):  # the next application starts on the same directory
        pass
    assert not process_lock._held

    with (
        patch("openartifact.database.build_engine", side_effect=RuntimeError("boom")),
        pytest.raises(ConfigurationError, match="Cannot connect to database: boom"),
        TestClient(_create_app(settings)),
    ):
        pass
    assert not process_lock._held


def test_a_file_system_without_locks_starts_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def no_locks(fd: int, operation: int) -> None:
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(fcntl, "flock", no_locks)
    with (
        caplog.at_level(logging.WARNING, logger="openartifact.process_lock"),
        process_lock.hold(tmp_path),
    ):
        assert not process_lock._held
    assert "cannot be locked" in caplog.text and "No locks available" in caplog.text
    assert "starting without the lock" in caplog.text


def test_a_platform_without_fcntl_starts_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(process_lock, "fcntl", None)
    with (
        caplog.at_level(logging.WARNING, logger="openartifact.process_lock"),
        process_lock.hold(tmp_path),
    ):
        assert not process_lock._held
    assert "This platform has no fcntl" in caplog.text


def _run_locked(data_dir: Path, *command: str) -> subprocess.CompletedProcess[str]:
    """``python -m openartifact.process_lock COMMAND`` with the data directory of the settings set to ``data_dir``."""
    return subprocess.run(
        [sys.executable, "-m", "openartifact.process_lock", *command],
        cwd=ROOT,
        env={**os.environ, "OPENARTIFACT_DATA_DIR": str(data_dir)},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_migration_step_runs_its_command_under_the_lock(tmp_path: Path) -> None:
    """The image's migration step (``scripts/docker-entrypoint.sh``) holds the lock while its command runs."""
    probe = (
        "import fcntl, os, sys; fd = os.open(sys.argv[1], os.O_RDONLY)\n"
        "try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "except BlockingIOError: sys.exit(7)\n"
        "sys.exit(0)"
    )
    done = _run_locked(
        tmp_path, sys.executable, "-c", probe, str(tmp_path / process_lock.LOCK_FILENAME)
    )
    assert done.returncode == 7, done.stderr  # the command saw the lock taken: it ran inside it


def test_the_migration_step_is_refused_while_another_process_holds_the_lock(
    tmp_path: Path, holder: Holder
) -> None:
    holder(tmp_path)
    marker = tmp_path / "ran"
    refused = _run_locked(tmp_path, sys.executable, "-c", f"open({str(marker)!r}, 'w')")
    assert refused.returncode == process_lock.REFUSED_STATUS
    assert "is in use by another OpenArtifact process" in refused.stderr
    assert not marker.exists(), "the command ran although the directory is in use"


def test_the_migration_step_passes_on_the_exit_status_of_its_command(tmp_path: Path) -> None:
    assert _run_locked(tmp_path, sys.executable, "-c", "raise SystemExit(5)").returncode == 5
    assert _run_locked(tmp_path).returncode == 2  # no command: usage
