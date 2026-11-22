"""The Code node's process: exit codes, protocol, timeout, truncation, environment, cancellation."""

from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path

import pytest

from openartifact.engine.code_runner import run_code
from openartifact.engine.executors import Limits, _code
from openartifact.engine.results import NodeResult
from tests.helpers import bare_settings

LIMIT = 65536


async def _run(
    code: str, language: str = "sh", timeout: int = 10, limit: int = LIMIT
) -> NodeResult:
    return await run_code(language, code, timeout, limit)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except (ProcessLookupError, FileNotFoundError):
        return False


async def _gone(pid: int, seconds: float = 3.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        await asyncio.sleep(0.05)
    return False


async def test_sh_passes_on_exit_code_zero_and_keeps_the_output() -> None:
    result = await _run("echo ok")
    assert (result.outcome, result.exit_code, result.output.strip()) == ("pass", 0, "ok")


async def test_python_runs_with_the_applications_interpreter() -> None:
    result = await _run("import sys\nprint(sys.flags.isolated)", "python")
    assert result.outcome == "pass"
    assert result.output.strip() == "1"


@pytest.mark.parametrize("language", ["sh", "python"])
async def test_a_nonzero_exit_code_fails_with_it_as_reason(language: str) -> None:
    code = "exit 3" if language == "sh" else "import sys\nsys.exit(3)"
    result = await _run(code, language)
    assert (result.outcome, result.exit_code, result.reason) == ("fail", 3, "Exit code 3")


async def test_stderr_is_kept_after_stdout() -> None:
    result = await _run("echo out\necho err >&2")
    assert result.output == "out\n[stderr]\nerr\n"


async def test_empty_code_fails_without_starting_anything() -> None:
    result = await _run("  \n")
    assert (result.outcome, result.reason) == ("fail", "The code is empty")


async def test_the_result_protocol_can_fail_an_exit_code_zero() -> None:
    result = await _run('echo log\necho \'{"ok": false, "reason": "no stock", "data": {"n": 2}}\'')
    assert (result.outcome, result.exit_code, result.reason) == ("fail", 0, "no stock")
    assert result.data == {"n": 2}


async def test_the_result_protocol_passes_data_on() -> None:
    result = await _run('echo \'{"ok": true, "data": {"id": 7}}\'')
    assert (result.outcome, result.data) == ("pass", {"id": 7})


@pytest.mark.parametrize("last", ['{"ok": "yes"}', "{not json", "[1, 2]", '"ok"'])
async def test_a_last_line_that_is_not_the_protocol_leaves_only_the_exit_code(last: str) -> None:
    result = await _run(f"echo '{last}'")
    assert (result.outcome, result.reason, result.data) == ("pass", None, None)


async def test_the_protocol_line_survives_truncation_of_long_output() -> None:
    code = 'import sys\nprint(\'x\' * 200000)\nprint(\'{"ok": false, "reason": "late"}\')'
    result = await _run(code, "python", limit=100)
    assert (result.outcome, result.reason) == ("fail", "late")
    assert "[output truncated]" in result.output


async def test_the_exit_code_wins_over_an_ok_true_line() -> None:
    result = await _run("echo '{\"ok\": true}'\nexit 2")
    assert (result.outcome, result.exit_code) == ("fail", 2)


async def test_output_is_cut_at_the_limit_and_marked() -> None:
    result = await _run("print('x' * 100000)", "python", limit=1000)
    assert result.outcome == "pass"
    assert len(result.output) < 1100
    assert result.output.endswith("[output truncated]")


async def test_a_timeout_kills_the_whole_process_group(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    started = time.monotonic()
    result = await _run(f"sleep 300 &\necho $! > {pidfile}\nwait", timeout=1)
    assert result.outcome == "fail"
    assert result.reason == "Timeout after 1 s"
    assert time.monotonic() - started < 6
    assert await _gone(int(pidfile.read_text()))


async def test_a_process_that_ignores_sigterm_is_killed_after_the_grace() -> None:
    result = await _run("trap '' TERM\nwhile true; do sleep 1; done", timeout=1)
    assert result.reason == "Timeout after 1 s"


async def test_a_child_left_in_the_background_does_not_survive(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    result = await _run(f"sleep 300 >/dev/null 2>&1 &\necho $! > {pidfile}")
    assert result.outcome == "pass"
    assert await _gone(int(pidfile.read_text()))


async def test_a_background_child_holding_the_output_does_not_delay_the_node(
    tmp_path: Path,
) -> None:
    """`sleep 300 &` keeps stdout open: the node ends with the shell, not with the timeout."""
    pidfile = tmp_path / "pid"
    started = time.monotonic()
    result = await _run(f"sleep 300 &\necho $! > {pidfile}\necho done", timeout=20)
    assert (result.outcome, result.exit_code, result.output) == ("pass", 0, "done\n")
    assert time.monotonic() - started < 5, "waited for the pipe instead of the process"
    assert await _gone(int(pidfile.read_text()))  # and nothing of the node stays alive


async def test_the_exit_code_of_a_shell_with_a_background_child_is_kept() -> None:
    result = await _run("sleep 300 &\nexit 3", timeout=20)
    assert (result.outcome, result.exit_code) == ("fail", 3)


async def test_the_environment_holds_no_openartifact_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENARTIFACT_API_TOKEN", "t" * 40)
    monkeypatch.setenv("OPENARTIFACT_SECRET_KEY", "very-secret")
    monkeypatch.setenv("SOMETHING_ELSE", "x")
    sh = await _run("env")
    py = await _run("import os\nprint(sorted(os.environ))", "python")
    for result in (sh, py):
        # the one random marker the orphan cleanup recognises a process by is allowed
        assert "OPENARTIFACT" not in re.sub(
            r"OPENARTIFACT_CODE_RUN(\W+[0-9a-f]{32})?", "", result.output
        )
        assert "very-secret" not in result.output
        assert "SOMETHING_ELSE" not in result.output
    assert {line.split("=")[0] for line in sh.output.split()} >= {"PATH", "HOME"}


async def test_the_directory_is_private_removed_afterwards_and_stdin_is_closed(
    tmp_path: Path,
) -> None:
    where = tmp_path / "where"
    result = await _run(f"pwd > {where}\nstat -c %a . \ncat")
    assert result.outcome == "pass"
    assert result.output.strip() == "700"
    assert not Path(where.read_text().strip()).exists()


async def test_cancelling_kills_the_child_and_removes_the_directory(tmp_path: Path) -> None:
    pidfile, where = tmp_path / "pid", tmp_path / "where"
    task = asyncio.create_task(
        _run(f"pwd > {where}\nsleep 300 &\necho $! > {pidfile}\nwait", timeout=60)
    )
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        await asyncio.sleep(0.05)
    pid = int(pidfile.read_text())
    assert _alive(pid)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await _gone(pid)
    assert not Path(where.read_text().strip()).exists()


async def test_a_disabled_code_node_fails_without_running() -> None:
    node = {"config": {"language": "sh", "code": "echo hi", "timeout_seconds": 5}}
    result = await _code(node, Limits(code_nodes_enabled=False))
    assert (result.outcome, result.reason) == ("fail", "Code nodes are disabled")
    assert result.output == ""


_OPEN = "Code nodes need OPENARTIFACT_API_TOKEN: the application is open without it"
_NODE = {"config": {"language": "sh", "code": "echo ran", "timeout_seconds": 5}}


@pytest.mark.parametrize(
    ("changes", "runs"),
    [
        ({}, False),  # open mode: no token, no opt-in
        ({"code_nodes_without_token": True}, True),  # explicit opt-in
        ({"api_token": "t" * 40}, True),  # token mode is unaffected
        ({"api_token": "t" * 40, "code_nodes_without_token": True}, True),
    ],
)
async def test_code_nodes_in_open_mode_need_the_opt_in(
    changes: dict[str, object], runs: bool
) -> None:
    limits = Limits.from_settings(bare_settings(**changes))
    result = await _code(_NODE, limits)
    if runs:
        assert (result.outcome, result.output.strip()) == ("pass", "ran")
    else:
        assert (result.outcome, result.reason, result.output) == ("fail", _OPEN, "")


def test_building_the_limits_does_not_log(caplog: pytest.LogCaptureFixture) -> None:
    """The opt-in warning belongs to the application start (it is logged there, formatted)."""
    with caplog.at_level("WARNING", logger="openartifact"):
        Limits.from_settings(bare_settings(code_nodes_without_token=True))
    assert not caplog.records


_READ_PARENT_ENVIRON = """
import os
for name in ("environ", "maps", "fd"):
    try:
        (os.listdir if name == "fd" else open)(f"/proc/{os.getppid()}/{name}")
        print("READABLE", name)
    except PermissionError:
        print("DENIED", name)
"""

_PARENT = """
import asyncio, os, sys
from openartifact.engine.code_runner import run_code
result = asyncio.run(run_code("python", sys.argv[1], 20, 65536))
print(result.output.strip())
"""


@pytest.mark.skipif(not Path("/proc/self/environ").exists(), reason="needs Linux /proc")
def test_a_code_process_cannot_read_the_environment_of_the_application() -> None:
    """Real processes: a parent holds a secret in its initial environment and runs a Code node."""
    import subprocess
    import sys

    env = {**os.environ, "OPENARTIFACT_API_TOKEN": "t" * 40}
    # control: an ordinary child of an ordinary process of this user reads it (the finding is real)
    control = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import subprocess,sys;subprocess.run([sys.executable,'-I','-c',{_READ_PARENT_ENVIRON!r}])",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "READABLE environ" in control.stdout
    guarded = subprocess.run(
        [sys.executable, "-c", _PARENT, _READ_PARENT_ENVIRON],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert guarded.stdout.split() == ["DENIED", "environ", "DENIED", "maps", "DENIED", "fd"], (
        guarded.stderr
    )
