# Operate the Docker deployment

All commands run from the repository root and use the compose file
[`deploy/docker-compose.yml`](../../deploy/docker-compose.yml). Its service is called `openartifact`;
no `container_name` is set, so address the container through `docker compose`, not `docker inspect openartifact`.

```bash
alias oa='docker compose -f deploy/docker-compose.yml'   # shorthand for this page
```

## First start

```bash
cp deploy/.env.example deploy/.env      # required: the compose file reads deploy/.env
# edit deploy/.env: set OPENARTIFACT_API_TOKEN and OPENARTIFACT_SECRET_KEY (see integration.md)
oa up -d --build
oa ps                                   # STATUS shows (healthy) after the start period (30 s)
curl http://localhost:2909/health
```

The container is published on `127.0.0.1:2909` only. See the [configuration reference](configuration.md)
for `OPENARTIFACT_BIND` and `OPENARTIFACT_PUBLISHED_PORT`, and [Reverse proxy](reverse-proxy.md) for
reaching it from other machines.

## Everyday commands

| Action | Command |
|--------|---------|
| Start | `oa up -d` |
| Stop (data stays) | `oa down` |
| Status and health | `oa ps` |
| Logs | `oa logs -f` |
| Shell in the container | `oa exec openartifact sh` |
| Delete the data | `oa down -v` (irreversible) |

## Update

Back up first ([below](#backup)). A downgrade is not supported for data: migrations only run forward on
start, and some rename tables.

```bash
# from source
git pull && oa up -d --build

# a released image (tags: see CI-CD.md); set OPENARTIFACT_TAG in deploy/.env to pin one
oa pull && oa up -d
```

The entrypoint runs `alembic upgrade head` before the server starts and aborts the start when a
migration fails: the container exits (and, with `restart: unless-stopped`, is restarted); `oa logs` shows why.

## Backup

The database runs in WAL mode, so copying `openartifact.db` while the application runs can lose committed
changes that still sit in `openartifact.db-wal`. Use SQLite's backup API, which gives a consistent file
without stopping anything:

```bash
oa exec openartifact python -c 'import sqlite3; d = sqlite3.connect("/data/backup.db"); sqlite3.connect("/data/openartifact.db").backup(d); d.close()'
oa cp openartifact:/data/backup.db ./openartifact-$(date +%F).db
oa exec openartifact rm /data/backup.db
```

The result is one self-contained SQLite file. Keep it away from the volume it protects, and treat it like
the data it holds. `deploy/.env` (token, secret key) is not part of it: store it separately.

## Restore

Restoring replaces the whole database with the backup; changes since the backup are lost. The backup
file must come from the same or an older version of the application (the start migrates it forward).

```bash
oa down                                  # stops the container, the volume stays
oa run --rm --no-deps -v "$PWD":/backup:ro --entrypoint sh openartifact -c \
  'rm -f /data/openartifact.db-wal /data/openartifact.db-shm && cp /backup/openartifact-2026-11-22.db /data/openartifact.db'
oa up -d
oa ps
```

The first command stops the application so nothing writes during the copy. The second one starts a
throw-away container with the same volume and the backup folder mounted read-only, deletes any leftover
`-wal` and `-shm` files (they belong to the old database and would corrupt the restored one) and copies the
backup in. `oa up -d` starts the application, which migrates the file to the current schema.

To restore into a fresh installation, run the first start (`oa up -d`), then `oa down` and the steps above.

## The volume

The data lives in the named volume `openartifact-data`; compose prefixes it with the project name, so under
the default project name (the folder `deploy`) it is `deploy_openartifact-data`. `docker volume inspect
deploy_openartifact-data` shows where it is on the host. Always use the compose commands above instead
of mounting the volume by hand: the name differs with the project name.

## The container

The container runs as an unprivileged user (UID 1000) on a read-only root file system; only `/data` and a
tmpfs `/tmp` are writable. All Linux capabilities are dropped, `no-new-privileges` is set, and there are
limits of 256 processes and 512 MB of memory. Raise `mem_limit` in the compose file only with a reason.

## One process, one volume

The application keeps its live-update bus, its run engine and its guards in memory of one process. Run
exactly one container per volume. Starting a second one against the same volume breaks SSE fan-out and the
run limits and risks write conflicts.
