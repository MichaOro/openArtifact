"""One application process per data directory, enforced by an OS lock on a file in it (ADR-094).

The application keeps its run engine, event bus and caps in the memory of one process, and the start
marks every ``running`` run as interrupted (``RunEngine.recover``). A second process on the same data
directory would stop the first one's live runs, so the lifespan holds :func:`hold` for its whole life
and takes it before it touches the database.

The lock is ``flock(LOCK_EX | LOCK_NB)`` on :data:`LOCK_FILENAME`. The kernel drops it when the holding
process ends in any way, ``SIGKILL`` included, so a lock file left behind is never stale: the file stays
in the directory and is not a PID file. Its descriptor is not inherited by child processes (Code
nodes), so a leftover child cannot keep it.

Within one process the lock is counted, not refused: the invariant is one *process* per directory,
and several applications in one process (the in-process test apps) already share the one database
engine of :mod:`openartifact.database`.

Where locking is not possible (a file system without lock support, a platform without ``fcntl``, a lock
file that cannot be created) the application logs a warning and starts without the lock: availability
over enforcement.

``python -m openartifact.process_lock COMMAND ...`` runs a command while holding the lock (the image runs its
migrations this way, ``scripts/docker-entrypoint.sh``): a second container is refused before it migrates the
database the first one serves.
"""

from __future__ import annotations

import errno
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # not POSIX: the supported targets (Linux, macOS) always have it
    fcntl = None  # type: ignore[assignment]

from openartifact.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

#: The file in the data directory whose lock marks the directory as in use.
LOCK_FILENAME = "openartifact.lock"

#: errno values of a lock that another process holds (``EACCES`` on some systems, per the Python docs)
_HELD = frozenset({errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES})


class _Held:
    """A lock this process holds: its descriptor and how many holders in the process share it."""

    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.count = 1


_guard = threading.Lock()  # the TestClient runs each lifespan in a thread of its own
_held: dict[str, _Held] = {}  # by the real path of the lock file


def _open(path: Path) -> int:
    """The lock file's descriptor, opened for writing: on NFS Linux emulates ``flock`` with a byte-range lock, and an
    exclusive one needs a descriptor open for writing (``EBADF`` otherwise, which would leave the directory unlocked).
    Read-only only where writing is refused (a lock file of another user, a read-only mount); ``flock`` works on it
    on a local file system."""
    try:
        return os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    except OSError as exc:
        if exc.errno not in (errno.EACCES, errno.EROFS):
            raise
        return os.open(path, os.O_RDONLY | os.O_CLOEXEC)


def _acquire(data_dir: Path) -> str | None:
    """Take the lock; the key to release it with, or ``None`` when the process runs without it."""
    path = data_dir / LOCK_FILENAME
    if fcntl is None:
        logger.warning(
            "This platform has no fcntl: the data directory %s is not locked, so a second "
            "OpenArtifact process on it would not be refused",
            data_dir,
        )
        return None
    with _guard:
        key = os.path.realpath(path)
        if (held := _held.get(key)) is not None:  # another application of this process
            held.count += 1
            return key
        try:
            if not data_dir.exists():
                data_dir.mkdir(parents=True, exist_ok=True)
                logger.info("Created data directory: %s", data_dir)
            fd = _open(path)
        except OSError as exc:  # the database step reports an unusable directory itself
            logger.warning(
                "The lock file %s cannot be opened (%s): starting without the lock, so a second "
                "OpenArtifact process on this data directory would not be refused",
                path,
                exc,
            )
            return None
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in _HELD:
                raise ConfigurationError(
                    f"The data directory {data_dir} is in use by another OpenArtifact process "
                    f"(it holds the lock on {path}). Only one process may use a data directory: "
                    "stop the other process or container first."
                ) from exc
            logger.warning(
                "The lock file %s cannot be locked (%s), probably a file system without lock "
                "support: starting without the lock, so a second OpenArtifact process on this "
                "data directory would not be refused",
                path,
                exc,
            )
            return None
        _held[key] = _Held(fd)
        return key


def _release(key: str | None) -> None:
    if key is None:
        return
    with _guard:
        held = _held[key]
        held.count -= 1
        if held.count == 0:
            del _held[key]
            os.close(held.fd)  # closing the only descriptor drops the lock


@contextmanager
def hold(data_dir: Path) -> Iterator[None]:
    """Hold the lock of ``data_dir`` for the block; refuse with ``ConfigurationError`` if another
    process holds it. The lock is released when the block ends, however it ends."""
    key = _acquire(data_dir)
    try:
        yield
    finally:
        _release(key)


#: Exit status of :func:`main` when another process holds the lock (uvicorn exits with 3 after a failed startup too).
REFUSED_STATUS = 3


def main(argv: list[str] | None = None) -> int:
    """Run ``argv`` while holding the lock of the settings' data directory; its exit status, or
    :data:`REFUSED_STATUS` without running it when another process holds the lock."""
    from openartifact.config import get_settings  # the settings only when run as a command

    command = sys.argv[1:] if argv is None else argv
    if not command:
        sys.stderr.write("usage: python -m openartifact.process_lock COMMAND [ARG ...]\n")
        return 2
    try:
        with hold(get_settings().data_dir):
            return subprocess.call(command)
    except ConfigurationError as error:
        sys.stderr.write(f"ERROR: {error}\n")
        return REFUSED_STATUS


if __name__ == "__main__":
    sys.exit(main())
