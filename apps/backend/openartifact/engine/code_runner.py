"""Runs the text of a Code node as a child process, bounded in time, output and resources.

The code is written to a fresh private directory under the system temp directory and run with
``sh`` or the application's own Python (``-I``, isolated). The environment holds ``PATH``, ``LANG``,
``HOME``, the secrets the node asked for (``NAME=value``) and one random marker
(``OPENARTIFACT_CODE_RUN``, see ``code_registry``); never an application setting: the API token and the
secret key stay with the application. The child leads its own process group so that a timeout or a
stopped run ends it together with everything it started.

Hardening, applied by a small Python wrapper that sets the limits and then replaces itself by the real
process (so no ``preexec_fn`` in a threaded program): ``RLIMIT_CPU`` (timeout plus a margin),
``RLIMIT_AS`` (memory), ``RLIMIT_NPROC`` (processes added; the kernel counts per user, so the limit is
the user's current count plus the setting, and root is exempt), ``RLIMIT_FSIZE``, ``RLIMIT_NOFILE`` and no
core files. If a limit cannot be applied the node fails instead of running unlimited. Where the
``resource`` module does not exist the code runs without limits and the result's reason says so.
``PR_SET_PDEATHSIG`` makes the kernel kill the direct child if the application is killed hard; what
the code started in the background is cleaned up by the next start (``code_registry``).

The application process is made non-dumpable before the first child starts (``security.
protect_process_memory``), so the code cannot read the token and secret key from ``/proc/<ppid>/environ``.
The database file stays readable to it (same user); stored credentials are encrypted with a key derived
from the secret key. In open mode (no API token) Code nodes do not run unless
``OPENARTIFACT_CODE_NODES_WITHOUT_TOKEN`` is on (see ``executors``).

NOT covered, whatever the limits: there is no network namespace (the code can reach every address the
application can, including the metadata and internal services that HTTP nodes refuse), no filesystem
isolation (it reads and writes what the application's user can) and it runs as the application's own
user. Memory and process limits are per process / per user, not a cgroup. The switch
``OPENARTIFACT_CODE_NODES_ENABLED`` stays the way to forbid Code nodes. The children belong to this
process: on a graceful shutdown they are ended with their runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openartifact.engine import code_registry
from openartifact.engine.results import NodeResult, failed
from openartifact.security import protect_process_memory

try:
    import resource
except ImportError:  # not a Unix: no limits can be applied
    resource = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

KILL_GRACE_SECONDS = 2.0
#: How long to wait for the pipes to close after the process ended (a background child may hold them).
DRAIN_SECONDS = 1.0
#: The tail of stdout always kept, so the last line (the result protocol) survives truncation.
TAIL_BYTES = 8192
MAX_DATA_JSON_CHARS = 16384
TRUNCATED_MARK = "[output truncated]"
#: CPU time a process may use beyond the wall-clock timeout before the kernel ends it.
CPU_MARGIN_SECONDS = 5
#: The wrapper exits with this code, after this first line on stderr, when a limit cannot be applied.
LIMIT_FAILED_CODE = 125
LIMIT_FAILED_MARK = "OPENARTIFACT_LIMITS:"
NO_LIMITS_NOTE = "Resource limits are not available on this platform; the code ran without them"
_MEMORY_SIGNS = ("MemoryError", "Cannot allocate memory", "out of memory", "std::bad_alloc")

_WRAPPER = f"""
import json, os, sys
spec = json.loads(sys.argv[1])
def fail(text):
    sys.stderr.write("{LIMIT_FAILED_MARK} " + text + "\\n")
    os._exit({LIMIT_FAILED_CODE})
if os.getppid() != spec["ppid"]:
    os._exit(1)
try:
    import resource
    for name, (soft, hard) in spec["rlimits"].items():
        number = getattr(resource, name)
        _, current = resource.getrlimit(number)
        if current != resource.RLIM_INFINITY:
            hard = min(hard, current)
            soft = min(soft, hard)
        resource.setrlimit(number, (soft, hard))
except Exception as error:
    fail(type(error).__name__ + ": " + str(error))
import signal
for name in ("SIGPIPE", "SIGXFSZ"):  # Python ignores these; the code must get the defaults
    signal.signal(getattr(signal, name), signal.SIG_DFL)
try:
    import ctypes
    ctypes.CDLL(None).prctl(1, signal.SIGKILL)
except Exception:
    pass
argv = sys.argv[2:]
os.execvp(argv[0], argv)
"""


@dataclass(frozen=True)
class CodeLimits:
    """What a Code node's process may use (see the ``code_*_limit`` settings)."""

    memory_mb: int = 512
    processes: int = 64
    file_mb: int = 64
    open_files: int = 256


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


def _environment(home: str, extra: Mapping[str, str], marker: str) -> dict[str, str]:
    return {
        **extra,
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "HOME": home,
        code_registry.MARKER_VARIABLE: marker,
    }


def _user_tasks() -> int:
    """Processes and threads of this user (what ``RLIMIT_NPROC`` counts); 0 if ``/proc`` is missing."""
    uid = os.getuid()
    own = str(os.getpid())
    total = 0
    with contextlib.suppress(OSError):
        for item in os.scandir("/proc"):
            if item.name == own:  # a non-dumpable process may not show our uid: count it by hand
                total += len(os.listdir("/proc/self/task"))
            elif item.name.isdigit():
                with contextlib.suppress(OSError):
                    if item.stat().st_uid == uid:
                        total += len(os.listdir(f"{item.path}/task"))
    return total


def _rlimits(limits: CodeLimits, timeout_seconds: int, baseline_tasks: int) -> dict[str, list[int]]:
    cpu = max(1, timeout_seconds + CPU_MARGIN_SECONDS)
    megabyte = 1024 * 1024
    return {
        "RLIMIT_CPU": [cpu, cpu + 1],  # SIGXCPU first, SIGKILL a second later
        "RLIMIT_AS": [limits.memory_mb * megabyte] * 2,
        "RLIMIT_NPROC": [baseline_tasks + limits.processes] * 2,
        "RLIMIT_FSIZE": [limits.file_mb * megabyte] * 2,
        "RLIMIT_NOFILE": [limits.open_files] * 2,
        "RLIMIT_CORE": [0, 0],
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


def _noted(result: NodeResult) -> NodeResult:
    """Say in the reason that no limits could be applied (only where the platform has none)."""
    if resource is None:
        result.reason = f"{result.reason}. {NO_LIMITS_NOTE}" if result.reason else NO_LIMITS_NOTE
    return result


def _exit_reason(code: int, output: str, limits: CodeLimits) -> str:
    """Why a process ended with a nonzero ``code``; names the resource limit when it is the likely cause."""
    if code < 0:
        if -code == signal.SIGXCPU:
            return "CPU time limit exceeded"
        if -code == signal.SIGXFSZ:
            return f"File size limit exceeded ({limits.file_mb} MiB)"
        return f"Killed by signal {-code}"
    if "File too large" in output:
        return f"Exit code {code} (file size limit of {limits.file_mb} MiB exceeded?)"
    if any(sign in output for sign in _MEMORY_SIGNS):
        return f"Exit code {code} (memory limit of {limits.memory_mb} MiB exceeded?)"
    return f"Exit code {code}"


async def run_code(
    language: str,
    code: str,
    timeout_seconds: int,
    output_limit_bytes: int,
    *,
    env: Mapping[str, str] | None = None,
    limits: CodeLimits | None = None,
    node_id: str = "",
) -> NodeResult:
    """Run ``code`` (``sh`` or ``python``) and return how it ended.

    Passes on exit code 0 (unless the result protocol says ``ok: false``). Fails on any other exit
    code, on a timeout ("Timeout after N s"), on a resource limit that stops it and when the code is
    empty. ``env`` (the secrets the node asked for) is added to the environment. The child and
    everything it started are killed on a timeout and when this task is cancelled.
    """
    if not code.strip():
        return failed("The code is empty")
    started = time.monotonic()
    limits = limits or CodeLimits()
    protect_process_memory()  # before the first child exists: it must not read our /proc/<pid>/environ
    directory = tempfile.mkdtemp(prefix=code_registry.DIRECTORY_PREFIX)  # mode 0700
    process: asyncio.subprocess.Process | None = None
    readers: list[asyncio.Task[None]] = []
    entry: Path | None = None
    try:
        script = Path(directory) / ("script.py" if language == "python" else "script.sh")
        script.write_text(code, encoding="utf-8")
        argv = [sys.executable, "-I", str(script)] if language == "python" else ["sh", str(script)]
        marker = code_registry.new_marker()
        if resource is not None:
            baseline = await asyncio.to_thread(_user_tasks)
            spec = {"ppid": os.getpid(), "rlimits": _rlimits(limits, timeout_seconds, baseline)}
            argv = [sys.executable, "-I", "-c", _WRAPPER, json.dumps(spec), *argv]
        else:
            logger.warning(NO_LIMITS_NOTE)
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=directory,
                env=_environment(directory, env or {}, marker),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError:
            return failed("The process could not be started")
        assert process.stdout is not None and process.stderr is not None
        entry = code_registry.record(process.pid, node_id, marker, directory)
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
            return _noted(
                NodeResult(
                    "fail",
                    exit_code=process.returncode,
                    output=output,
                    reason=f"Timeout after {timeout_seconds} s",
                    duration=duration,
                )
            )
        code_returned = process.returncode
        assert code_returned is not None
        if (
            resource is not None
            and code_returned == LIMIT_FAILED_CODE
            and stderr.text().startswith(LIMIT_FAILED_MARK)
        ):
            detail = stderr.text().splitlines()[0][len(LIMIT_FAILED_MARK) :].strip()
            return failed(f"The resource limits could not be applied ({detail[:200]})")
        report = _protocol(stdout.tail)
        reason = report.get("reason") if report else None
        data = report.get("data") if report else None
        if not isinstance(reason, str):
            reason = None
        if not isinstance(data, dict) or len(json.dumps(data)) > MAX_DATA_JSON_CHARS:
            data = None
        if code_returned != 0:
            if reason is None:
                reason = _exit_reason(code_returned, output, limits)
            return _noted(NodeResult("fail", code_returned, output, reason, data, duration))
        if report is not None and report["ok"] is False:
            return _noted(
                NodeResult(
                    "fail", 0, output, reason or "The code reported ok: false", data, duration
                )
            )
        return _noted(NodeResult("pass", 0, output, None, data, duration))
    finally:
        # also on cancellation (the run was stopped): nothing of the node may stay alive
        code_registry.forget(entry)
        if process is not None:
            _kill_group(process.pid, signal.SIGKILL)
            if process.returncode is None:  # cancelled: reap it so that no transport is left open
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(process.wait(), KILL_GRACE_SECONDS)
        for task in readers:
            task.cancel()
        shutil.rmtree(directory, ignore_errors=True)
