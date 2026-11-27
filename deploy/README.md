# deploy

Docker Compose deployment: one container, SQLite in a named volume.

- `docker-compose.yml` — the service, its hardening (see below), the volume and the health check
- `.env.example` — every setting with a comment; copy it to `deploy/.env` (required, next to the compose file; never commit it)

The `Dockerfile` and `.dockerignore` are at the repository root (the build context), and `scripts/docker-entrypoint.sh`
(migrations, then `exec openartifact`) is copied into the image. There is no PostgreSQL variant: openArtifact's own data stays
in SQLite for good (ADR-020). PostgreSQL may later appear as a *data source* behind a connector layer, not as the application's
database.

Run every command from the repository root:

```bash
cp deploy/.env.example deploy/.env       # then set the token and the secret key
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps
```

## Access protection

Set `OPENARTIFACT_API_TOKEN` (at least 32 characters, `openssl rand -hex 32`) and a secret key of your own in `deploy/.env`.
With a token the whole application asks for it: browsers get a sign-in page, scripts and agents send
`Authorization: Bearer <token>` (also for `/api/v1` and `/mcp`). Without a token the application is open, `/api/v1` and
`/mcp` are closed, and Execute Command nodes and credentials are unavailable. The application refuses to start with a short token, or with a token
and a secret key that is missing, the default or shorter than 32 characters. Do not change the secret key later: it encrypts the stored
credentials, which become unreadable. See [Security](../docs/guides/security.md), [Credentials](../docs/guides/credentials.md),
ADR-016, ADR-017, [SECURITY.md](../SECURITY.md) and the [guide](../docs/guides/integration.md).

## Published address

The container is published on `127.0.0.1:2909` (`OPENARTIFACT_BIND`, `OPENARTIFACT_PUBLISHED_PORT`). `OPENARTIFACT_PORT` is the
port inside the container; the mapping and the health check follow it. `0.0.0.0` opens the network: set a token and put a TLS
proxy in front ([reverse proxy guide](../docs/guides/reverse-proxy.md)).

## Compose variables

Read by the compose file (from `deploy/.env` or the shell), not by the application:

| Variable | Default | Meaning |
|----------|---------|---------|
| `OPENARTIFACT_BIND` | `127.0.0.1` | Host address the port is published on; from another machine use an SSH port forward (`ssh -L 2909:127.0.0.1:2909 host`) or a proxy |
| `OPENARTIFACT_PUBLISHED_PORT` | `2909` | Host port |
| `OPENARTIFACT_TAG` | `latest` | Image tag when you pull a released image |

Everything else in `deploy/.env` is an `OPENARTIFACT_*` application setting ([configuration reference](../docs/guides/configuration.md)).

## Hardening in the compose file

| Setting | Effect |
|---------|--------|
| `read_only: true` and `tmpfs: /tmp` | the root file system is read-only; only the volume `/data` and a memory-backed `/tmp` (Execute Command nodes work there) are writable |
| `cap_drop: ALL` | no Linux capabilities |
| `security_opt: no-new-privileges` | a process cannot gain privileges |
| `pids_limit: 256` | at most 256 processes and threads in the container |
| `mem_limit: 1g` | memory limit of the container (`/tmp` counts against it) |
| user `1000` (Dockerfile) | the application and the Execute Command nodes it starts run unprivileged |
| published on `127.0.0.1` | not reachable from the network unless `OPENARTIFACT_BIND` says so |

This is the reference: a `docker run` of the image should pass the same flags. Execute Command nodes run inside this
container with the rights of the application and are no sandbox; see
[Operate the Docker deployment](../docs/guides/operations.md#execute-command-nodes-in-the-container) and
[Execution nodes](../docs/guides/execution-nodes.md).

## Where to read on

| Topic | Document |
|-------|----------|
| Every setting | [Configuration reference](../docs/guides/configuration.md) |
| Update, backup, restore, key and token rotation, database size, the volume | [Operate the Docker deployment](../docs/guides/operations.md) |
| TLS, `Host`, forwarded headers, cookie | [Run behind a reverse proxy](../docs/guides/reverse-proxy.md) |
| Image name, tags, release | [CI/CD and releases](../docs/guides/CI-CD.md) |
| Deployment architecture | [arc42 chapter 7](../docs/architecture/arc42/07-deployment-view.md) |
