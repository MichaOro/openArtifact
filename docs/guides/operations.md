# Operate the Docker deployment

All commands run from the repository root and use the compose file
[`deploy/docker-compose.yml`](../../deploy/docker-compose.yml). Its service is called `openartifact`;
no `container_name` is set, so address the container through `docker compose`, not `docker inspect openartifact`.

```bash
alias oa='docker compose -f deploy/docker-compose.yml'   # shorthand for this page
```

## Reaching another container (LiteLLM, a local model server)

A provider at `http://litellm:4000/v1` works only when OpenArtifact and that container share a Docker network; the
connection test otherwise says *The host name could not be resolved*. Copy
[`deploy/docker-compose.network.example.yml`](../../deploy/docker-compose.network.example.yml) to
`deploy/docker-compose.override.yml` (git-ignored), set the network's name (`docker network ls`) and start with both files:

```bash
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.override.yml up -d --build
```

A command with only `-f deploy/docker-compose.yml` (the `oa` alias above) **leaves the override out**, and the container loses
the network on its next recreate. A service on the host itself needs no network: use `http://host.docker.internal:PORT/v1`.

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

### Reaching a loopback-only instance from another machine

With the default `OPENARTIFACT_BIND=127.0.0.1` nothing else on the network can connect. Without a
reverse proxy, an SSH port forward gives you access from your workstation and needs no open port:

```bash
ssh -L 2909:127.0.0.1:2909 user@server      # then open http://localhost:2909 locally
```

Setting `OPENARTIFACT_BIND=0.0.0.0` is the alternative; it requires a token and, outside a trusted
network, TLS ([Reverse proxy](reverse-proxy.md)). Docker's published ports bypass host firewalls that
filter in the `INPUT` chain; do not rely on such a firewall to protect a `0.0.0.0` binding.

## Token rotation and key rotation

The token and the secret key are different secrets with different consequences. See
[Security](security.md) and [Credentials](credentials.md).

**Rotate the token** (leak, a person leaves, periodic):

1. `openssl rand -hex 32`, put the result into `OPENARTIFACT_API_TOKEN` in `deploy/.env`.
2. `oa up -d` (recreates the container with the new environment; a plain restart does not re-read `deploy/.env`).
3. Every browser session ends (the cookie signature covers the token) and must sign in again; update every
   script, agent and MCP client that sends the old token.

There is one token and no per-session revocation: the old token stops working at step 2, immediately.

**Do not rotate `OPENARTIFACT_SECRET_KEY` once credentials are stored.** The credential store encrypts
with a key derived from it. A different secret key signs every browser out *and makes every stored
credential unreadable*: nodes that use one fail with "Secret NAME cannot be read: the secret key changed".
There is no re-encryption and no migration of the old key. If you must change it, list the credentials
first (`GET /api/v1/secrets`), change the key, and store every value again with `PUT /api/v1/secrets/{name}`
([Credentials](credentials.md)). Keep the backup of the database together with the key that belongs to it.

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

Back up first ([below](#backup)). The application only migrates forward on start.

> **Execute Command nodes are off by default** (ADR-075). The node that used to be called *Code* (shell or Python as the
> application's user, no sandbox) now needs `OPENARTIFACT_CODE_NODES_ENABLED=true` in `deploy/.env`. An installation that
> used Code nodes and updates without it keeps its actions, but every such node fails with "Execute Command nodes are
> switched off on this instance" until the variable is set and the container restarted. The stored data does not change. Older migrations
do have a `downgrade()`, but it loses data on purpose (for example Code and HTTP nodes, all stored
credentials, or all but the newest execution per run), so a rollback means restoring the backup made
before the update, together with the older image.

```bash
# from source
git pull && oa up -d --build

# a released image (tags: see CI-CD.md); set OPENARTIFACT_TAG in deploy/.env to pin one
oa pull && oa up -d
```

The entrypoint runs `alembic upgrade head` before the server starts and aborts the start when a
migration fails: the container exits (and, with `restart: unless-stopped`, is restarted); `oa logs` shows why.
The pages (HTML) are sent with `Cache-Control: no-cache` and the static files revalidate with their ETag, so a browser shows the new build after a reload, not the old one from its cache.
After the update check `oa ps` (healthy), `curl http://localhost:2909/health` (the answer carries the
version) and the start of the log (below).

## Stopping all execution (STOP)

When a run, an agent or a script goes wrong, the **STOP switch** ([execution history](execution-history.md#the-stop-switch)) aborts every
running execution and refuses every start until it is switched off; the state is kept in the database, so a restart of the container keeps
it. It is a personal setting (*Settings > Personal > Show the STOP switch*, off by default) and can be set from the browser, with
`PUT /api/v1/settings/stop` (`{"active": true}`) or through MCP; whoever holds a token can switch it, like any other write. Switching it **on**
needs the setting, switching it **off** never does. To stop in the middle of the night from outside: `curl -X PUT -H "Authorization: Bearer
$TOKEN" -H "Content-Type: application/json" -d '{"active": true}' http://127.0.0.1:2909/api/v1/settings/stop`.

## Health, logs and log levels

`GET /health` is open (no token, no `Host` check) and answers `200` while the process serves requests;
the compose health check calls it every 30 s (3 retries, 30 s start period). It does not test the
database beyond the process being up: a failed migration shows as a container that exits, not as
`unhealthy`.

`OPENARTIFACT_LOG_LEVEL` sets the level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). `INFO` logs the start
(version, environment, data directory), warnings for an open instance (no token) or the default secret
key, and, after a hard stop, `Cleaned up N leftover code process(es)`. `DEBUG` is verbose; use it for a
short investigation. The configured token and key and the values of credentials a node is using are masked
in log lines; do not rely on that for anything you paste into a ticket without reading it.

```bash
oa logs -f --tail 100
```

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
the data it holds: **it contains the stored credentials, encrypted, and the executions' step outputs in
clear text**. `deploy/.env` (token, secret key) is not part of it: store it separately, **but keep the
`OPENARTIFACT_SECRET_KEY` that belongs to the backup**: without exactly that key the credentials in the
file are unreadable. Check the file once in a while:

```bash
python3 -c 'import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute("pragma integrity_check").fetchone())' openartifact-2026-11-22.db
```

Schedule it with cron or a systemd timer on the host, and test a restore (below) on a copy before you need it.

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

To restore into a fresh installation, run the first start (`oa up -d`), then `oa down` and the steps above,
with the same `OPENARTIFACT_SECRET_KEY` as the one that wrote the backup.

After the start, check that the data is there and intact:

```bash
oa exec openartifact python -c 'import sqlite3; print(sqlite3.connect("/data/openartifact.db").execute("pragma integrity_check").fetchone())'   # ('ok',)
curl -H "Authorization: Bearer <token>" http://localhost:2909/api/v1/secrets      # names are listed; a node that uses one still runs
```

The copy-and-remove-`-wal` logic was verified with a SQLite database in WAL mode: a backup taken with the
backup API while the database was open contained exactly the committed state at that moment, and the
restored file passed `integrity_check`. The compose commands themselves are not run against a live volume
by this documentation; try them first on a throwaway project (`oa -p restore-test ...` with its own volume
and `OPENARTIFACT_PUBLISHED_PORT` set to a free port).

## The volume

The data lives in the named volume `openartifact-data`; compose prefixes it with the project name, so under
the default project name (the folder `deploy`) it is `deploy_openartifact-data`. `docker volume inspect
deploy_openartifact-data` shows where it is on the host. Always use the compose commands above instead
of mounting the volume by hand: the name differs with the project name.

## The container

The container runs as an unprivileged user (UID 1000) on a read-only root file system; only `/data` and a
tmpfs `/tmp` are writable. All Linux capabilities are dropped, `no-new-privileges` is set, and the container
is limited to 256 processes and 1 GiB of memory. The published address is `127.0.0.1` unless you change
`OPENARTIFACT_BIND`. These flags are the reference hardening; if you start the image with `docker run`,
pass the same ones (see [deploy/README.md](../../deploy/README.md)). Raise a limit only with a reason.

### Execute Command nodes in the container

Execute Command nodes run inside this container as children of the application, as the same unprivileged user, so
they see what the application sees: `/data` (the database), the network, and `/tmp`. They are bounded by
`OPENARTIFACT_CODE_*` limits (address space 512 MiB, 64 added processes, 64 MiB per file, 256 files, the
node's timeout) and are hardened against reading the parent's environment, but are no sandbox
([Execution nodes](execution-nodes.md), [Security](security.md)). The limits interact:

- `mem_limit: 1g` is for the whole container; the Code memory limit (512 MiB) is address space of one
  process. `/tmp` is a tmpfs and counts against the container memory; Code directories and the process
  registry live there. Several parallel Execute Command nodes can still exhaust the container: lower
  `OPENARTIFACT_MAX_CONCURRENT_RUNS` or the memory limit of Execute Command nodes rather than raising `mem_limit` blindly.
- `pids_limit: 256` applies to the container in addition to `OPENARTIFACT_CODE_PROCESS_LIMIT` (64, counted per user).
- Runtimes that reserve a lot of address space (Java, Node.js, Go) need a higher
  `OPENARTIFACT_CODE_MEMORY_LIMIT_MB` and then a higher `mem_limit`.

Safety switches, from strongest to weakest: `OPENARTIFACT_CODE_NODES_ENABLED` unset or `false`, the default (no Execute Command node runs; set `true` to switch them on);
no token (open mode refuses Execute Command nodes unless `OPENARTIFACT_CODE_NODES_WITHOUT_TOKEN=true`, for local
development only); the limits above. Whoever may edit pipelines and holds the token may run code with the
rights of the application: treat the token like shell access to the container.

## Database size and history retention

Every start of an artifact is an execution that stores a frozen snapshot of the graphs it ran (JSON) and
every step with its output (up to 1 MiB each). By default the 50 newest executions per artifact are kept
(`OPENARTIFACT_EXECUTION_HISTORY_DEFAULT_KEEP`; `0` keeps everything and lets the file grow with every run);
the retention rules (*Executions → Retention*) decide the rest ([Execution history](execution-history.md)).
The database runs with `auto_vacuum = FULL`: deleting rows (an execution, its artifact, retention) returns the freed
pages to the file system when the change is committed, so the file shrinks again (after the next WAL checkpoint,
which the application does regularly and on shutdown). A new database is created in this mode. A database from an
earlier version is converted **once** at the next start: the start-up migration step runs a single `VACUUM`, which
rewrites the file, needs free space about the size of the database during the run and holds the file for that time
(seconds for a small one). Take a [backup](#backup) before the first start of a new version if the database is large.

The setting is a property of the file: a restore of an old backup that was not converted is converted again at the
next start. Deleting rows costs a little more CPU than before because the file is truncated; with a history of
normal size this is not noticeable.

## One process, one volume

The application keeps its live-update bus, its run engine and its guards in memory of one process. Run
exactly one container per volume. Starting a second one against the same volume breaks SSE fan-out and the
run limits and risks write conflicts.
