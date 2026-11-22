"""The registry of Code-node processes: what a restart may kill and delete, and what it must never touch.

The registry lives in the temp directory; every test points ``tempfile.gettempdir`` at its own folder.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from openartifact.engine import code_registry
from openartifact.engine.code_registry import (
    DIRECTORY_PREFIX,
    Entry,
    cleanup_leftovers,
    new_marker,
    record,
    registry_directory,
    start_time_of,
)

pytestmark = pytest.mark.skipif(not Path("/proc").is_dir(), reason="the registry needs /proc")


@pytest.fixture
def temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    return tmp_path


def _dead_owner_entry(
    pid: int, directory: Path, *, pgid: int | None = None, start: int = 0
) -> Entry:
    """An entry written by an application that no longer exists (a pid no process can have)."""
    return Entry(
        pid=pid,
        pgid=pgid if pgid is not None else pid,
        start_time=start,
        marker=new_marker(),
        node_id="n",
        directory=str(directory),
        owner_pid=4_000_000_000,
        owner_start_time=1,
    )


def _write(folder: Path, entry: Entry) -> Path:
    file = folder / f"{entry.pid}-{entry.marker}.json"
    file.write_text(json.dumps(asdict(entry)))
    return file


@pytest.fixture
def folder(temp: Path) -> Path:
    found = registry_directory()
    assert found is not None
    return found


@pytest.fixture
def killpg_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Replace ``killpg`` by a recorder: no test may signal a process group for real."""
    calls: list[int] = []
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: calls.append(pgid))
    return calls


def test_the_registry_directory_is_private_and_made_once(temp: Path) -> None:
    found = registry_directory()
    assert found == temp / f"openartifact-code-{os.getuid()}"
    assert found.stat().st_mode & 0o777 == 0o700
    assert registry_directory() == found


def test_a_registry_directory_open_to_others_is_not_used(temp: Path) -> None:
    (temp / f"openartifact-code-{os.getuid()}").mkdir(mode=0o755)
    (temp / f"openartifact-code-{os.getuid()}").chmod(0o755)
    assert registry_directory() is None
    assert record(os.getpid(), "n", new_marker(), str(temp)) is None
    assert cleanup_leftovers() == 0


def test_a_registry_directory_that_cannot_be_inspected_is_not_used(
    temp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self: Path, *args: object, **kwargs: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "mkdir", refuse)
    assert registry_directory() is None


def test_a_registry_directory_that_vanishes_before_it_is_inspected_is_not_used(
    temp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def vanished(self: Path) -> None:
        raise FileNotFoundError(self)

    monkeypatch.setattr(Path, "lstat", vanished)
    assert registry_directory() is None


def test_start_time_of_a_missing_process_is_none() -> None:
    assert start_time_of(4_000_000_000) is None
    assert start_time_of(os.getpid()) is not None


def test_record_writes_one_file_that_describes_the_process(folder: Path, temp: Path) -> None:
    marker = new_marker()
    file = record(os.getpid(), "node-1", marker, str(temp / "oa-code-x"))
    assert file == folder / f"{os.getpid()}-{marker}.json"
    written = json.loads(file.read_text())
    assert (written["pid"], written["pgid"], written["marker"], written["node_id"]) == (
        os.getpid(),
        os.getpid(),
        marker,
        "node-1",
    )
    assert written["start_time"] == start_time_of(os.getpid())


def test_record_survives_an_unwritable_registry(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self: Path, *args: object, **kwargs: object) -> int:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", refuse)
    assert record(os.getpid(), "n", new_marker(), "/nowhere") is None
    assert list(folder.iterdir()) == []


def test_a_process_that_does_not_exist_is_not_recorded(folder: Path) -> None:
    assert record(4_000_000_000, "n", new_marker(), "/nowhere") is None
    assert list(folder.iterdir()) == []


@pytest.mark.parametrize(
    "content",
    ["not json", "[1, 2]", json.dumps({"pid": 1}), json.dumps({"pid": "x", "extra": 1})],
    ids=["no json", "wrong shape", "missing fields", "unknown fields"],
)
def test_a_corrupt_registry_file_is_removed_without_killing(
    folder: Path, killpg_calls: list[int], content: str
) -> None:
    file = folder / "1-corrupt.json"
    file.write_text(content)
    assert cleanup_leftovers() == 0
    assert not file.exists()
    assert killpg_calls == []


def test_an_entry_of_a_running_application_is_left_alone(folder: Path, temp: Path) -> None:
    kept = temp / f"{DIRECTORY_PREFIX}alive"
    kept.mkdir()
    entry = _dead_owner_entry(4_000_000_000, kept)
    entry.owner_pid, entry.owner_start_time = os.getpid(), start_time_of(os.getpid()) or 0
    file = _write(folder, entry)
    assert cleanup_leftovers() == 0
    assert file.exists()
    assert kept.is_dir()


def test_an_entry_of_a_dead_application_is_forgotten_and_its_directory_removed(
    folder: Path, temp: Path
) -> None:
    leftover = temp / f"{DIRECTORY_PREFIX}gone"
    leftover.mkdir()
    (leftover / "main.py").write_text("print(1)")
    file = _write(folder, _dead_owner_entry(4_000_000_000, leftover))
    assert cleanup_leftovers() == 0  # the process is gone: nothing to kill
    assert not file.exists()
    assert not leftover.exists()


def test_an_entry_whose_directory_is_outside_the_temp_directory_is_not_removed(
    folder: Path, temp: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A tampered registry file must not turn the clean-up into ``rm -r`` of user data."""
    elsewhere = tmp_path_factory.mktemp("userdata") / f"{DIRECTORY_PREFIX}precious"
    elsewhere.mkdir()
    (elsewhere / "thesis.txt").write_text("keep me")
    file = _write(folder, _dead_owner_entry(4_000_000_000, elsewhere))
    cleanup_leftovers()
    assert (elsewhere / "thesis.txt").read_text() == "keep me"
    assert not file.exists()  # the entry itself is still cleared


def test_an_entry_whose_directory_lacks_the_prefix_is_not_removed(folder: Path, temp: Path) -> None:
    userdata = temp / "documents"
    userdata.mkdir()
    (userdata / "a.txt").write_text("keep me")
    _write(folder, _dead_owner_entry(4_000_000_000, userdata))
    cleanup_leftovers()
    assert (userdata / "a.txt").read_text() == "keep me"


def test_a_nested_directory_below_the_temp_directory_is_not_removed(
    folder: Path, temp: Path
) -> None:
    nested = temp / "sub" / f"{DIRECTORY_PREFIX}deep"
    nested.mkdir(parents=True)
    _write(folder, _dead_owner_entry(4_000_000_000, nested))
    cleanup_leftovers()
    assert nested.is_dir()


def test_an_entry_with_a_changed_group_id_kills_only_the_pid(
    folder: Path, temp: Path, killpg_calls: list[int]
) -> None:
    """The recorded group no longer belongs to the process: never signal a stranger's group."""
    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        start = start_time_of(victim.pid)
        assert start is not None
        # the process leads no group of its own (it is in this test's group): the entry's pgid is wrong
        assert os.getpgid(victim.pid) != victim.pid
        _write(folder, _dead_owner_entry(victim.pid, temp / f"{DIRECTORY_PREFIX}x", start=start))
        assert cleanup_leftovers() == 1
        assert victim.wait(10) == -signal.SIGKILL
    finally:
        victim.kill()
        victim.wait()
    assert killpg_calls == []


def test_an_entry_with_the_right_group_signals_the_group_and_the_process(
    folder: Path, temp: Path, killpg_calls: list[int]
) -> None:
    victim = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True
    )
    try:
        start = start_time_of(victim.pid)
        assert start is not None
        _write(folder, _dead_owner_entry(victim.pid, temp / f"{DIRECTORY_PREFIX}x", start=start))
        assert cleanup_leftovers() == 1
        assert victim.wait(10) == -signal.SIGKILL
    finally:
        victim.kill()
        victim.wait()
    assert killpg_calls == [victim.pid]


def test_a_reused_process_id_with_another_start_time_is_not_killed(
    folder: Path, temp: Path, killpg_calls: list[int]
) -> None:
    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        start = start_time_of(bystander.pid)
        assert start is not None
        _write(
            folder,
            _dead_owner_entry(bystander.pid, temp / f"{DIRECTORY_PREFIX}x", start=start + 1),
        )
        assert cleanup_leftovers() == 0
        assert bystander.poll() is None
    finally:
        bystander.kill()
        bystander.wait()
    assert killpg_calls == []


def test_a_process_carrying_the_marker_is_killed_even_without_a_matching_pid(
    folder: Path, temp: Path
) -> None:
    """A background child of the code keeps the marker in its environment after the parent died."""
    entry = _dead_owner_entry(4_000_000_000, temp / f"{DIRECTORY_PREFIX}x")
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        env={**os.environ, code_registry.MARKER_VARIABLE: entry.marker},
    )
    try:
        _write(folder, entry)
        assert cleanup_leftovers() == 1
        assert child.wait(10) == -signal.SIGKILL
    finally:
        child.kill()
        child.wait()
