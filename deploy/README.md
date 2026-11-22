# deploy

Docker Compose deployment (SQLite in a named volume).

- `docker-compose.yml` — the service, its hardening (read-only root file system, no capabilities) and the health check
- `.env.example` — the settings; copy it to `deploy/.env`

The `Dockerfile` and `.dockerignore` are at the repository root (the build context) and
`scripts/docker-entrypoint.sh` (migrations, then the server) is copied into the image. The header of
`docker-compose.yml` lists the commands for start, update, health and backup.

## Access protection

Set `OPENARTIFACT_API_TOKEN` in `deploy/.env`. With a token the whole application asks for it: browsers
get a sign-in page, scripts and agents send `Authorization: Bearer <token>` (also for `/api/v1` and
`/mcp`). Without a token the application is open and `/api/v1` and `/mcp` are closed. See ADR-016.
