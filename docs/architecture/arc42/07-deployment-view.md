# 7. Deployment View

## 7.1 Runtime-Environment Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│ Docker host (Linux)                                                 │
│                                                                     │
│   optional TLS reverse proxy (nginx, Caddy) ── 443                  │
│        │                                                            │
│        ▼  127.0.0.1:2909  (OPENARTIFACT_BIND : PUBLISHED_PORT)      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ openartifact container (UID 1000, read-only root fs,          │  │
│  │   cap_drop ALL, no-new-privileges, pids 256, memory limit)    │  │
│  │                                                               │  │
│  │   docker-entrypoint.sh: alembic upgrade head                  │  │
│  │   → openartifact (uvicorn, one process, port 2909)            │  │
│  │        │  sh / python -I child processes of Execute Command nodes        │  │
│  │        │  (own process group, rlimits, same user)             │  │
│  │        ▼                                                      │  │
│  │   outbound: HTTP nodes (checked addresses), Execute Command nodes (any)  │  │
│  │                                                               │  │
│  │   writable: /data (volume) and /tmp (tmpfs, in RAM)           │  │
│  └──────────────┬────────────────────────────────────────────────┘  │
│                 ▼                                                   │
│  volume openartifact-data → /data: openartifact.db (+ -wal, -shm)   │
└─────────────────────────────────────────────────────────────────────┘
```

One container per volume: the application keeps the event bus, the run engine and the caps in memory of one
process (chapter 11). Execute Command nodes run *inside* the container as child processes of the application, with the same
user; the container is their only boundary ([8.5](08-cross-cutting-concepts/08.05-execution-nodes-safety.md)).

## 7.2 Development Environment

- Local Python 3.12+ with `uv` or `pip` (CI uses pip); SQLite, a local file, no server
- The default data directory `/data` is usually not writable on a workstation: set `OPENARTIFACT_DATA_DIR=./.data`
  (for example in `.env` at the repository root), run `alembic upgrade head`, then `openartifact`
- `docker compose -f deploy/docker-compose.yml up --build` for integration testing

The commands are in the [README](../../../README.md#development) and the [testing guide](../../guides/testing.md).

## 7.3 Deployment Environment

The deployment is defined by files, not copied here, so that it cannot drift:

| What | File |
|------|------|
| Service, volume, hardening, health check, port mapping | [`deploy/docker-compose.yml`](../../../deploy/docker-compose.yml) |
| Settings (copy to `deploy/.env`, required) | [`deploy/.env.example`](../../../deploy/.env.example) |
| Image build (multi-stage, `python:3.12-slim`, non-root user) | [`Dockerfile`](../../../Dockerfile) and the allow-list [`.dockerignore`](../../../.dockerignore) |
| Start: migrations, then the server | [`scripts/docker-entrypoint.sh`](../../../scripts/docker-entrypoint.sh) |

| Aspect | Configuration |
|--------|---------------|
| Image | built from source (`build:`) or `ghcr.io/michaoro/openartifact:${OPENARTIFACT_TAG:-latest}` ([CI/CD guide](../../guides/CI-CD.md)) |
| Runtime user | `openartifact` (UID 1000, non-root); `/app` and the installed package belong to root |
| Container hardening | `read_only: true`, tmpfs `/tmp`, `cap_drop: ALL`, `no-new-privileges`, `pids_limit: 256`, `mem_limit` (see below) |
| Port | the application listens on `OPENARTIFACT_PORT` (2909); published as `OPENARTIFACT_BIND:OPENARTIFACT_PUBLISHED_PORT` (default `127.0.0.1:2909`, local only) |
| Volume | `openartifact-data` at `/data`, the only persistent state (named `deploy_openartifact-data` under the default compose project name) |
| Health check | `GET /health` through Python's `urllib` (no `curl` in the image), every 30 s, 30 s start period |
| Restart | `restart: unless-stopped` |
| Configuration | `deploy/.env` (all `OPENARTIFACT_*` settings, [reference](../../guides/configuration.md)) |
| TLS | not in the application; a reverse proxy ([guide](../../guides/reverse-proxy.md)) |

The commands for start, update, health, backup and restore are in the [operations guide](../../guides/operations.md):
`docker compose -f deploy/docker-compose.yml ps` shows the health state, an update from source is
`git pull && docker compose -f deploy/docker-compose.yml up -d --build`, and a backup uses SQLite's backup API (the
database runs in WAL mode, so copying the file is not safe). `docker compose down` keeps the volume; `down -v` deletes it.

### 7.4 Resource limits and Execute Command nodes in the container

| Limit | Where | Effect |
|-------|-------|--------|
| `mem_limit` (1g in the compose file) | container (cgroup) | The kernel kills the container's biggest process when the total is exceeded. Counts everything: the application (roughly 150 to 250 MB), Code-node processes **and** the files in the tmpfs `/tmp` |
| `pids_limit: 256` | container | All processes and threads of the container, the application's threads included |
| `OPENARTIFACT_CODE_MEMORY_LIMIT_MB` (default 512) | per Code-node process | `RLIMIT_AS`, an address-space limit that makes the process fail with a memory error; it is not a cgroup and not a guarantee of the real memory used |
| `OPENARTIFACT_CODE_PROCESS_LIMIT` (default 64) | Execute Command nodes, per user | `RLIMIT_NPROC`: the user's current count plus this number |
| other `OPENARTIFACT_CODE_*` limits | per Code-node process | file size, open files, output size; CPU time follows the node's timeout |

The memory limit of the container must stay clearly above one Execute Command node's address-space limit plus the application,
otherwise a node at its limit lets the kernel kill the whole container instead of only the node; raise both together
(the comment in the compose file says the same). `/tmp` is a tmpfs: an Execute Command node's temp directory and everything it
writes there (up to the file-size limit per file) live in RAM and count against the memory limit. An Execute Command node cannot
write anywhere else except `/data` (writable for the application's user, so a node can reach the database file:
[8.5](08-cross-cutting-concepts/08.05-execution-nodes-safety.md)). The registry of started Code processes also lives
in `/tmp`; when the container restarts, the processes are gone with it and `/tmp` is empty, so cleanup after a hard kill
matters for a bare-metal run rather than for the container ([6.7](06-runtime-view/06.07-code-node-execution.md)).
Settings reference: [configuration guide](../../guides/configuration.md).

### 7.5 Data, backup and the secret key

All state is in `/data/openartifact.db`: artifacts, pipelines, runs, the execution history (including the frozen
snapshots and step outputs, so the file grows with use, see the retention setting) and the stored credentials
(encrypted). Back up with SQLite's backup API as shown in the header of
[`deploy/docker-compose.yml`](../../../deploy/docker-compose.yml) and in the [operations guide](../../guides/operations.md#backup);
copying the live file in WAL mode is not safe. Credentials in the backup are readable only with the same
`OPENARTIFACT_SECRET_KEY`: keep the key with the backup (in a different place than the database file), because without
it every stored credential is lost; there is no key rotation ([8.6](08-cross-cutting-concepts/08.06-credential-store.md)).
Nothing schedules backups.
