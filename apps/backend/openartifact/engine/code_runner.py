"""Runs the text of a Code node as a child process, bounded in time and output.

The code is written to a fresh private directory under the system temp directory and run with
``sh`` or the application's own Python (``-I``, isolated). There is no sandbox: the process has the
rights of the application and can reach whatever the application can, except that its environment
holds only ``PATH``, ``LANG`` and ``HOME`` (never an ``OPENARTIFACT_*`` value: the API token and the
secret key stay with the application). The child leads its own process group so that a timeout or
a stopped run ends it together with everything it started. The children belong to this process:
on a graceful shutdown they are ended with their runs; if the application is killed hard, they
keep running until the container (or the user) ends them.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from openartifact.engine.results import NodeResult, failed

KILL_GRACE_SECONDS = 2.0
#: How long to wait for the pipes to close after the process ended (a background child may hold them).
DRAIN_SECONDS = 1.0
#: The tail of stdout always kept, so the last line (the result protocol) survives truncation.
TAIL_BYTES = 8192
MAX_DATA_JSON_CHARS = 16384
TRUNCATED_MARK = "[output truncated]"


class _Stream:
    """Collects one pipe: the first ``limit`` bytes, the last ``TAIL_BYTES`` and whether it was cut."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.head = bytearray()
        self.tail = b""
        self.cut = False

    async def read(self, reader: asyncio.StreamReader) -> None:
        while chunk := await reader.read(65536):
            room = self.limit - len(self.head)
            if room > 0:
                self.head += chunk[:room]
            if len(chunk) > max(room, 0):
                self.cut = True
            self.tail = (self.tail + chunk)[-TAIL_BYTES:]

    def text(self) -> str:
        text = self.head.decode("utf-8", errors="replace")
        return f"{text}\n{TRUNCATED_MARK}" if self.cut else text


def _environment(home: str) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "HOME": home,
    }


def _kill_group(pid: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, sig)


def _protocol(tail: bytes) -> dict[str, Any] | None:
    """The result protocol: the last non-empty line of stdout is a JSON object with a boolean ``ok``."""
    lines = [line for line in tail.decode("utf-8", errors="replace").splitlines() if line.strip()]
    if not lines:
        return None
    try:
        value = json.loads(lines[-1])
    except ValueError:
        return None
    if isinstance(value, dict) and isinstance(value.get("ok"), bool):
        return value
    return None


def _combine(stdout: _Stream, stderr: _Stream) -> str:
    out = stdout.text()
    err = stderr.text()
    if not err:
        return out
    return f"{out}{'' if out.endswith(chr(10)) or not out else chr(10)}[stderr]\n{err}"


async def run_code(
    language: str, code: str, timeout_seconds: int, output_limit_bytes: int
) -> NodeResult:
    """Run ``code`` (``sh`` or ``python``) and return how it ended.

    Passes on exit code 0 (unless the result protocol says ``ok: false``). Fails on any other exit
    code, on a timeout ("Timeout after N s") and when the code is empty. The child and everything it
    started are killed on a timeout and when this task is cancelled.
    """
    if not code.strip():
        return failed("The code is empty")
    started = time.monotonic()
    directory = tempfile.mkdtemp(prefix="oa-code-")  # mode 0700
    process: asyncio.subprocess.Process | None = None
    readers: list[asyncio.Task[None]] = []
    try:
        script = Path(directory) / ("script.py" if language == "python" else "script.sh")
        script.write_text(code, encoding="utf-8")
        argv = [sys.executable, "-I", str(script)] if language == "python" else ["sh", str(script)]
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=directory,
                env=_environment(directory),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError:
            return failed("The process could not be started")
        assert process.stdout is not None and process.stderr is not None
        stdout, stderr = _Stream(output_limit_bytes), _Stream(output_limit_bytes)
        readers += [
            asyncio.create_task(stdout.read(process.stdout)),
            asyncio.create_task(stderr.read(process.stderr)),
        ]
        timed_out = False
        try:
            await asyncio.wait_for(process.wait(), timeout_seconds)
        except TimeoutError:
            timed_out = True
            _kill_group(process.pid, signal.SIGTERM)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), KILL_GRACE_SECONDS)
        _kill_group(process.pid, signal.SIGKILL)  # whatever it left behind
        _, pending = await asyncio.wait(readers, timeout=DRAIN_SECONDS)
        for task in pending:
            task.cancel()
        duration = time.monotonic() - started
        output = _combine(stdout, stderr)
        if timed_out:
            return NodeResult(
                "fail",
                exit_code=process.returncode,
                output=output,
                reason=f"Timeout after {timeout_seconds} s",
                duration=duration,
            )
        code_returned = process.returncode
        assert code_returned is not None
        report = _protocol(stdout.tail)
        reason = report.get("reason") if report else None
        data = report.get("data") if report else None
        if not isinstance(reason, str):
            reason = None
        if not isinstance(data, dict) or len(json.dumps(data)) > MAX_DATA_JSON_CHARS:
            data = None
        if code_returned != 0:
            if reason is None:
                reason = (
                    f"Killed by signal {-code_returned}"
                    if code_returned < 0
                    else f"Exit code {code_returned}"
                )
            return NodeResult("fail", code_returned, output, reason, data, duration=duration)
        if report is not None and report["ok"] is False:
            return NodeResult(
                "fail", 0, output, reason or "The code reported ok: false", data, duration
            )
        return NodeResult("pass", 0, output, None, data, duration)
    finally:
        # also on cancellation (the run was stopped): nothing of the node may stay alive
        if process is not None:
            _kill_group(process.pid, signal.SIGKILL)
            if process.returncode is None:  # cancelled: reap it so that no transport is left open
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(process.wait(), KILL_GRACE_SECONDS)
        for task in readers:
            task.cancel()
        shutil.rmtree(directory, ignore_errors=True)
