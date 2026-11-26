"""Code nodes under resource limits, and the cleanup of processes an earlier application left behind."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openartifact.engine import code_registry, code_runner
from openartifact.engine.code_runner import CodeLimits, run_code
from openartifact.engine.results import NodeResult

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")


async def _run(code: str, language: str = "sh", timeout: int = 10, **limits: int) -> NodeResult:
    return await run_code(language, code, timeout, 65536, limits=CodeLimits(**limits))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except (ProcessLookupError, FileNotFoundError):
        return False


def _wait_gone(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


# ── limits ───────────────────────────────────────────────────────────


async def test_the_limits_are_set_in_the_process() -> None:
    code = "import json, resource as r\nprint(json.dumps({n: r.getrlimit(getattr(r, n)) for n in ('RLIMIT_AS', 'RLIMIT_FSIZE', 'RLIMIT_NOFILE', 'RLIMIT_CORE', 'RLIMIT_CPU')}))"
    result = await _run(code, "python", timeout=10, memory_mb=300, file_mb=7, open_files=77)
    seen = json.loads(result.output)
    assert seen["RLIMIT_AS"] == [300 * 1024 * 1024] * 2
    assert seen["RLIMIT_FSIZE"] == [7 * 1024 * 1024] * 2
    assert seen["RLIMIT_NOFILE"] == [77, 77]
    assert seen["RLIMIT_CORE"] == [0, 0]
    assert seen["RLIMIT_CPU"][0] == 10 + code_runner.CPU_MARGIN_SECONDS


async def test_the_code_gets_the_default_signal_handling_not_the_wrappers() -> None:
    result = await _run("yes | head -n 1\necho done")
    assert (result.outcome, result.output) == ("pass", "y\ndone\n")


async def test_a_process_that_asks_for_too_much_memory_fails_with_a_reason() -> None:
    result = await _run(
        "x = bytearray(400 * 1024 * 1024)\nprint('allocated')", "python", memory_mb=128
    )
    assert result.outcome == "fail"
    assert "allocated" not in result.output
    assert result.reason is not None and "memory limit of 128 MiB" in result.reason


async def test_a_fork_bomb_runs_into_the_process_limit() -> None:
    code = (
        "import os, time\n"
        "made = 0\n"
        "for _ in range(400):\n"
        "    try:\n"
        "        pid = os.fork()\n"
        "    except OSError:\n"
        "        print('blocked after', made)\n"
        "        break\n"
        "    if pid == 0:\n"
        "        os.close(1)\n"
        "        os.close(2)\n"
        "        time.sleep(30)\n"
        "        os._exit(0)\n"
        "    made += 1\n"
        "else:\n"
        "    print('not blocked')\n"
    )
    result = await _run(code, "python", processes=6)
    assert "blocked after" in result.output, result.output
    assert "not blocked" not in result.output


async def test_a_file_that_is_too_big_cannot_be_written() -> None:
    py = await _run(
        "f = open('big', 'wb')\nf.write(b'x' * 3_000_000)\nf.flush()\nprint('written')",
        "python",
        file_mb=1,
    )
    assert py.outcome == "fail" and "written" not in py.output
    assert py.reason == "Exit code 1 (file size limit of 1 MiB exceeded?)"
    sh = await _run("exec dd if=/dev/zero of=big bs=1M count=3 2>/dev/null", file_mb=1)
    assert sh.outcome == "fail"
    assert sh.reason == "File size limit exceeded (1 MiB)"


async def test_too_many_open_files_fail() -> None:
    code = "import os\nfiles = [open(os.devnull) for _ in range(200)]\nprint('opened', len(files))"
    result = await _run(code, "python", open_files=40)
    assert result.outcome == "fail" and "opened" not in result.output
    assert "Too many open files" in result.output


async def test_a_cpu_spin_is_ended_by_the_kernel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(code_runner, "CPU_MARGIN_SECONDS", -9)  # CPU limit 1 s of a 10 s timeout
    started = time.monotonic()
    result = await _run("while :; do :; done", timeout=10)
    assert result.outcome == "fail"
    assert result.reason == "CPU time limit exceeded"
    assert time.monotonic() - started < 6


async def test_a_limit_that_cannot_be_applied_fails_the_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(code_runner, "_rlimits", lambda *a: {"RLIMIT_NOPE": [1, 1]})
    result = await _run("echo ran")
    assert result.outcome == "fail" and "ran" not in result.output
    assert result.reason is not None
    assert result.reason.startswith("The resource limits could not be applied")


async def test_without_the_resource_module_the_code_runs_and_the_result_says_so(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(code_runner, "resource", None)
    caplog.set_level(logging.WARNING)
    ok = await _run("echo hi")
    bad = await _run("exit 3")
    assert (ok.outcome, ok.output.strip(), ok.reason) == ("pass", "hi", code_runner.NO_LIMITS_NOTE)
    assert bad.reason == f"Exit code 3. {code_runner.NO_LIMITS_NOTE}"
    assert "Resource limits are not available" in caplog.text


# ── the registry and the cleanup ─────────────────────────────────────


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return code_registry.registry_directory() or pytest.fail("no registry")


def _dead_pid() -> int:
    process = subprocess.Popen(["true"])
    process.wait()
    return process.pid


def _sleeper(marker: str | None = None, *, own_group: bool = True) -> subprocess.Popen[bytes]:
    """A process that sleeps and starts a sleeping child of its own (same group)."""
    env = {**os.environ, **({code_registry.MARKER_VARIABLE: marker} if marker else {})}
    process = subprocess.Popen(
        ["sh", "-c", "sleep 60 & sleep 60"], env=env, start_new_session=own_group
    )
    time.sleep(0.2)
    return process


def _write(registry: Path, process: subprocess.Popen[bytes], **changes: object) -> Path:
    entry = {
        "pid": process.pid,
        "pgid": process.pid,
        "start_time": code_registry.start_time_of(process.pid),
        "marker": "a" * 32,
        "node_id": "n",
        "directory": str(registry.parent / "oa-code-x"),
        "owner_pid": _dead_pid(),
        "owner_start_time": 1,
        **changes,
    }
    file = registry / f"{process.pid}.json"
    file.write_text(json.dumps(entry))
    return file


def test_a_leftover_process_group_is_killed_and_its_files_removed(registry: Path) -> None:
    leftover_dir = registry.parent / "oa-code-x"
    leftover_dir.mkdir()
    process = _sleeper()
    file = _write(registry, process)
    assert code_registry.cleanup_leftovers() >= 1
    process.wait(timeout=5)
    assert process.returncode == -signal.SIGKILL
    assert not file.exists() and not leftover_dir.exists()


def test_a_reused_process_id_is_not_killed(registry: Path) -> None:
    innocent = _sleeper()
    start = code_registry.start_time_of(innocent.pid)
    assert start is not None
    file = _write(registry, innocent, start_time=start + 1)  # same pid, another process
    try:
        code_registry.cleanup_leftovers()
        assert innocent.poll() is None and _alive(innocent.pid)
        assert not file.exists()  # the stale entry is dropped
    finally:
        os.killpg(innocent.pid, signal.SIGKILL)
        innocent.wait()


def test_a_process_with_the_marker_is_killed_even_when_its_leader_is_gone(registry: Path) -> None:
    marker = "b" * 32
    straggler = _sleeper(marker, own_group=False)
    leader = subprocess.Popen(["true"])
    leader.wait()
    _write(registry, leader, marker=marker, start_time=0)
    code_registry.cleanup_leftovers()
    straggler.wait(timeout=5)
    assert straggler.returncode == -signal.SIGKILL
    subprocess.run(["pkill", "-KILL", "-P", str(straggler.pid)], check=False)


def test_the_entry_of_a_running_application_is_left_alone(registry: Path) -> None:
    process = _sleeper()
    file = _write(
        registry,
        process,
        owner_pid=os.getpid(),
        owner_start_time=code_registry.start_time_of(os.getpid()),
    )
    try:
        assert code_registry.cleanup_leftovers() == 0
        assert process.poll() is None and file.exists()
    finally:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def test_a_foreign_or_broken_registry_is_not_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    open_dir = tmp_path / f"openartifact-code-{os.getuid()}"
    open_dir.mkdir(mode=0o777)
    open_dir.chmod(0o777)
    assert code_registry.registry_directory() is None
    assert code_registry.cleanup_leftovers() == 0
    assert code_registry.record(os.getpid(), "n", "m", "d") is None


async def test_a_running_node_is_recorded_and_forgotten(registry: Path) -> None:
    seen: list[str] = []

    async def watch() -> None:
        for _ in range(100):
            seen.extend(p.name for p in registry.glob("*.json"))
            if seen:
                return
            await asyncio.sleep(0.05)

    result, _ = await asyncio.gather(run_code("sh", "sleep 1", 10, 1000, node_id="node-1"), watch())
    assert result.outcome == "pass" and len(seen) == 1
    assert list(registry.glob("*.json")) == []


def test_after_a_hard_kill_the_child_dies_with_the_parent_and_the_cleanup_ends_the_rest(
    registry: Path, tmp_path: Path
) -> None:
    child_file, grandchild_file = tmp_path / "child", tmp_path / "grandchild"
    script = (
        "import asyncio\n"
        "from openartifact.engine.code_runner import run_code\n"
        f"code = 'echo $$ > {child_file}\\nsleep 100 &\\necho $! > {grandchild_file}\\nwait'\n"
        "asyncio.run(run_code('sh', code, 100, 1000))\n"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", script], env={**os.environ, "TMPDIR": str(tmp_path)}
    )
    deadline = time.monotonic() + 10
    while not (grandchild_file.exists() and grandchild_file.read_text().strip()):
        assert time.monotonic() < deadline and parent.poll() is None
        time.sleep(0.05)
    child, grandchild = int(child_file.read_text()), int(grandchild_file.read_text())
    parent.kill()
    parent.wait()
    assert _wait_gone(child)  # PR_SET_PDEATHSIG
    assert _alive(grandchild)  # the kernel cannot reach it
    assert list(registry.glob("*.json"))
    assert code_registry.cleanup_leftovers() >= 1
    assert _wait_gone(grandchild)
    assert list(registry.glob("*.json")) == []


def test_the_application_cleans_up_when_it_starts(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    asyncio.run(client.app.state.engine.recover())  # type: ignore[attr-defined]
    assert "Cleaned up 0 leftover code process(es)" in caplog.text
