# deploy

Docker Compose deployment: one container, SQLite in a named volume.

- `docker-compose.yml` — the service, its hardening (read-only root file system, no capabilities), the volume and the health check
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
`Authorization: Bearer <token>` (also for `/api/v1` and `/mcp`). Without a token the application is open and `/api/v1` and
`/mcp` are closed. The application refuses to start with a short token or without a secret key. See ADR-016, ADR-017 and the
[guide](../docs/guides/integration.md).

## Published address

The container is published on `127.0.0.1:2909` (`OPENARTIFACT_BIND`, `OPENARTIFACT_PUBLISHED_PORT`). `OPENARTIFACT_PORT` is the
port inside the container; the mapping and the health check follow it. `0.0.0.0` opens the network: set a token and put a TLS
proxy in front ([reverse proxy guide](../docs/guides/reverse-proxy.md)).

## Where to read on

| Topic | Document |
|-------|----------|
| Every setting | [Configuration reference](../docs/guides/configuration.md) |
| Update, backup, restore, the volume | [Operate the Docker deployment](../docs/guides/operations.md) |
| TLS, `Host`, forwarded headers, cookie | [Run behind a reverse proxy](../docs/guides/reverse-proxy.md) |
| Image name, tags, release | [CI/CD and releases](../docs/guides/CI-CD.md) |
| Deployment architecture | [arc42 chapter 7](../docs/architecture/arc42/07-deployment-view.md) |
