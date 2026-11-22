# 7. Deployment View

## 7.1 Runtime-Environment Overview

```
┌───────────────────────────────────────────────────────────────┐
│ Docker host (Linux)                                           │
│                                                               │
│   optional TLS reverse proxy (nginx, Caddy) ── 443            │
│        │                                                      │
│        ▼  127.0.0.1:2909 (OPENARTIFACT_BIND : PUBLISHED_PORT) │
│  ┌───────────────────────────────────────────────────────┐    │
│  │ openartifact container (UID 1000, read-only root fs)  │    │
│  │   docker-entrypoint.sh: alembic upgrade head          │    │
│  │   → openartifact (uvicorn, one process, port 2909)    │    │
│  │   writable: /data (volume) and /tmp (tmpfs)           │    │
│  └──────────────┬────────────────────────────────────────┘    │
│                 ▼                                              │
│  volume openartifact-data → /data: openartifact.db (+ -wal, -shm)
└───────────────────────────────────────────────────────────────┘
```

One container per volume: the application keeps the event bus, the run engine and the caps in memory of one
process (chapter 11).

## 7.2 Development Environment

- Local Python 3.12+ with `uv` or `pip` (CI uses pip); SQLite, a local file, no server
- The default data directory `/data` is usually not writable on a workstation: set `OPENARTIFACT_DATA_DIR=./.data`
  (for example in `apps/backend/.env`), run `alembic upgrade head`, then `openartifact`
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
| Container hardening | read-only root file system, tmpfs `/tmp`, `cap_drop: ALL`, `no-new-privileges`, 256 processes, 512 MB |
| Port | the application listens on `OPENARTIFACT_PORT` (2909); published as `OPENARTIFACT_BIND:OPENARTIFACT_PUBLISHED_PORT` (default `127.0.0.1:2909`, local only) |
| Volume | `openartifact-data` at `/data` (named `deploy_openartifact-data` under the default compose project name) |
| Health check | `GET /health` through Python's `urllib` (no `curl` in the image), every 30 s, 30 s start period |
| Restart | `restart: unless-stopped` |
| Configuration | `deploy/.env` (all `OPENARTIFACT_*` settings, [reference](../../guides/configuration.md)) |
| TLS | not in the application; a reverse proxy ([guide](../../guides/reverse-proxy.md)) |

The commands for start, update, health, backup and restore are in the [operations guide](../../guides/operations.md):
`docker compose -f deploy/docker-compose.yml ps` shows the health state, an update from source is
`git pull && docker compose -f deploy/docker-compose.yml up -d --build`, and a backup uses SQLite's backup API (the
database runs in WAL mode, so copying the file is not safe). `docker compose down` keeps the volume; `down -v` deletes it.
