# deploy

Deployment configurations.

- `docker-compose.yml` — Default Docker Compose (SQLite, port 2909)
- `docker-compose.postgres.yml` — Optional PostgreSQL override
- `Dockerfile` — Multi-stage Python build
- `scripts/docker-entrypoint.sh` — Container entrypoint with migrations

## Access protection

Set `OPENARTIFACT_API_TOKEN` in `deploy/.env` (see `.env.example`). With a token the whole application
asks for it: browsers get a sign-in page, scripts and agents send `Authorization: Bearer <token>`
(also for `/api/v1` and `/mcp`). Without a token the application is open and `/api/v1` and `/mcp` are
closed. See ADR-016.

## Note

Docker configurations will be finalized in WP-06 (Deployment and Operational Tooling). Placeholder files may be added as needed.
