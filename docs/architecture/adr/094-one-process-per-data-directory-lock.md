# ADR-094: One process per data directory, enforced by a file lock

**Status:** Accepted  
**Date:** 2026-11-27  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-020](020-sqlite-stays-postgres-as-data-source.md) (the "one process, one volume" consequence is enforced, not only documented)  
**Amended by:** —  
**Implemented in:** `openartifact/process_lock.py`, the lifespan in `openartifact/app.py`, `tests/test_process_lock.py`  
**Affected chapters:** arc42 [7 Deployment](../arc42/07-deployment-view.md), [11 Risks](../arc42/11-risks-and-technical-debt.md) (risk 3), [operations guide](../../guides/operations.md#one-process-one-volume)

## 1. Title

How does the application make sure that only one process uses a data directory?

## 2. Context

The event bus, the run engine, the caps and the registry of Code processes live in the memory of one process
(ADR-020, arc42 risk 3). The start of the application calls `RunEngine.recover()`, which sets every `running` run
and execution to `stopped` with the note *Interrupted by restart*. Until now the "one process per volume" rule was
only written down. A second process on the same data directory (an overlapping deployment, a second
`openartifact` started by hand) marked the first process's live runs as stopped while they kept running and
writing.

## 3. Decision

- **An exclusive, non-blocking `flock`** (`LOCK_EX | LOCK_NB`) on `<data_dir>/openartifact.lock`. The lifespan takes
  it first, before it touches the database or runs recovery, and holds it until the end of shutdown. It is
  released in a `finally`, so a failed startup or a shutdown step that raises releases it too; the order of the
  other startup and shutdown steps is unchanged.
- **Lock held by another process:** the start fails with `ConfigurationError` naming the directory, the lock file
  and that another OpenArtifact process uses it. Uvicorn reports "Application startup failed" and exits; nothing
  is recovered or written by the application.
- **No stale locks, no PID file.** The kernel drops a `flock` when the holding process ends in any way,
  `SIGKILL` and an OOM kill included. The file itself stays in the directory and carries no content; it is not
  deleted at shutdown (deleting it would let a process that opened the old file and one that creates a new one
  both hold "the" lock).
- **Not inherited.** The descriptor is opened with `O_CLOEXEC` (Python's default), so Execute Command processes do not
  hold the lock and an orphaned child cannot block the next start.
- **Counted within one process.** The invariant is one *process*: a second application object in the same process
  (the in-process test apps; several tests keep two or three apps on one data directory open at the same time)
  increments a counter instead of being refused, and the lock is released when the last one ends. Such apps
  already share the one database engine of `openartifact/database.py`.
- **Availability over enforcement.** If the lock cannot be taken for another reason — a file system without lock
  support (`ENOLCK`, `EOPNOTSUPP` on some network or FUSE file systems), a lock file that cannot be created, a
  platform without `fcntl` — the application logs a warning that a second process would not be refused and
  starts. An unusable data directory is still reported by the database step, with its existing message.

### Why `flock` and not `fcntl`/`lockf` record locks

POSIX record locks belong to the process: they never conflict within one process, and closing *any* descriptor of
the file in the process drops them. `flock` locks belong to the open file description, which matches "this
application holds the directory". On Linux, `flock` on NFS is mapped to a record lock on the server, so it also
works across NFS clients; an exclusive record lock needs a descriptor open for writing, so the lock file is opened
read-write (read-only only where writing is refused: a lock file of another user or a read-only mount, where it is
honoured on a local file system).

## 4. Consequences

- **Easier:** an overlapping start can no longer stop the running instance's runs. With `docker compose up -d` the
  old container is stopped before the new one starts (compose's default recreate), so an update is not affected.
- **Relied on:** an in-process lock is enough to serialise a read-merge-write of the database, because no other process
  writes the same data. The first use: changes to the nodes of one graph run one after the other (`api/graphs.py`,
  `_graph_writes`), so two settings saved at once both stay (`tests/test_node_update_concurrency.py`).
- **Operator-visible:** a second container or process on the same volume exits at start with the message above. A
  container with `restart: unless-stopped` is restarted by Docker and refused again until the first one ends.
- **Migrations:** the image's entrypoint runs `alembic upgrade head` through `python -m openartifact.process_lock`,
  which holds the same lock while the command runs and exits with status 3 without running it when another process
  holds it: a second container is refused before it migrates the database the first one serves. The lock is
  released between the migration and the start of the server; a process that slips into that moment is refused by
  the one that took it first. Alembic run by hand outside the image does not take the lock.
- **Not covered:** a file system that silently accepts `flock` without sharing it between machines (some FUSE or
  virtualised mounts) gives no protection across those machines.
- **Tests:** `tests/test_process_lock.py` covers the refusal (in-process and from another process), the release
  after shutdown, after a failed start and after `SIGKILL`, the untouched `running` run of the other process, the
  shared lock within one process, the warning paths, and the migration step (its command runs inside the lock, is
  not run while another process holds it, and its exit status is passed on).
