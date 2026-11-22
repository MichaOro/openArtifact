"""A record of the processes Code nodes started, so that a hard kill of the application leaves no orphans.

A Code node's process leads its own process group. When the application ends gracefully, the runs are
cancelled and the groups are killed. When it is killed hard (``SIGKILL``, the container's OOM killer),
the direct child dies with it (``PR_SET_PDEATHSIG``, see ``code_runner``), but anything the code started
in the background lives on. For that case every started process is noted in a private directory
(``<temp dir>/openartifact-code-<uid>``, mode 0700) as one small JSON file; the next start calls
:func:`cleanup_leftovers`, which ends what is still running and removes the temp directories.

Safety against a reused process id: the file holds the start time of the process (field 22 of
``/proc/<pid>/stat``) and a random marker that the child and its descendants carry in their environment
(``OPENARTIFACT_CODE_RUN``, nothing sensitive). Only a process whose pid *and* start time match, or whose
environment carries the marker of an entry, is killed. A file whose owner (the application that wrote
it) is still running belongs to a running application and is left alone. Needs ``/proc`` (Linux); where it
is missing nothing is recorded and nothing is cleaned up.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import signal
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MARKER_VARIABLE = "OPENARTIFACT_CODE_RUN"
DIRECTORY_PREFIX = "oa-code-"
_MARKER = re.compile(rb"(?:^|\0)" + MARKER_VARIABLE.encode() + rb"=([0-9a-f]{32})(?:\0|$)")


@dataclass
class Entry:
    """One started process: what is needed to recognise it again after a restart."""

    pid: int
    pgid: int
    start_time: int
    marker: str
    node_id: str
    directory: str
    owner_pid: int
    owner_start_time: int


def new_marker() -> str:
    return uuid.uuid4().hex


def start_time_of(pid: int) -> int | None:
    """The start time (clock ticks after boot) of a process, ``None`` if it does not exist or ``/proc`` is missing."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        # the name in field 2 may hold spaces and parentheses: count from the last ')'
        return int(stat[stat.rindex(")") + 2 :].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def registry_directory() -> Path | None:
    """The private directory of the registry, created if needed; ``None`` if it cannot be trusted."""
    path = Path(tempfile.gettempdir()) / f"openartifact-code-{os.getuid()}"
    try:
        path.mkdir(mode=0o700, exist_ok=True)
        info = path.lstat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077 or path.is_symlink():
            logger.warning("The code process registry %s is not private; it is not used", path)
            return None
    except OSError:
        return None
    return path


def record(pid: int, node_id: str, marker: str, directory: str) -> Path | None:
    """Note a started process (its own group leader); returns the file to :func:`forget` later."""
    folder = registry_directory()
    start = start_time_of(pid)
    owner_start = start_time_of(os.getpid())
    if folder is None or start is None or owner_start is None:
        return None
    entry = Entry(pid, pid, start, marker, node_id, directory, os.getpid(), owner_start)
    file = folder / f"{pid}-{marker}.json"
    try:
        file.write_text(json.dumps(asdict(entry)))
    except OSError:
        return None
    return file


def forget(file: Path | None) -> None:
    if file is not None:
        with contextlib.suppress(OSError):
            file.unlink()


def _load(file: Path) -> Entry | None:
    try:
        return Entry(**json.loads(file.read_text()))
    except (OSError, ValueError, TypeError):
        return None


def _marked_processes() -> dict[str, list[int]]:
    """The processes of this user whose environment carries a marker, by marker."""
    found: dict[str, list[int]] = {}
    for item in os.scandir("/proc"):
        if not item.name.isdigit():
            continue
        try:
            if item.stat().st_uid != os.getuid():
                continue
            environ = Path(item.path, "environ").read_bytes()
        except OSError:
            continue
        if match := _MARKER.search(environ):
            found.setdefault(match[1].decode(), []).append(int(item.name))
    return found


def _owner_alive(entry: Entry) -> bool:
    return start_time_of(entry.owner_pid) == entry.owner_start_time


def cleanup_leftovers() -> int:
    """End what earlier applications left behind; returns the number of processes killed.

    Entries of an application that still runs are skipped. Everything else is killed if it is
    recognised (see the module docstring), and its file and temp directory are removed.
    """
    folder = registry_directory()
    if folder is None or not Path("/proc").is_dir():
        return 0
    entries = [(f, _load(f)) for f in sorted(folder.glob("*.json"))]
    own = (os.getpid(), start_time_of(os.getpid()))
    killed = 0
    marked = _marked_processes()
    for file, entry in entries:
        if entry is None:
            forget(file)
            continue
        if (entry.owner_pid, entry.owner_start_time) == own or _owner_alive(entry):
            continue
        victims = set(marked.get(entry.marker, []))
        if start_time_of(entry.pid) == entry.start_time:
            victims.add(entry.pid)
            with contextlib.suppress(ProcessLookupError, PermissionError):
                if os.getpgid(entry.pid) == entry.pgid:
                    os.killpg(entry.pgid, signal.SIGKILL)
        for pid in victims:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)
        killed += len(victims)
        directory = Path(entry.directory)
        if directory.name.startswith(DIRECTORY_PREFIX) and directory.parent == Path(
            tempfile.gettempdir()
        ):
            shutil.rmtree(directory, ignore_errors=True)
        forget(file)
    return killed
