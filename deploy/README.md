# deploy

Deployment configurations.

- `docker-compose.yml` — Default Docker Compose (SQLite, port 2909)
- `docker-compose.postgres.yml` — Optional PostgreSQL override
- `Dockerfile` — Multi-stage Python build
- `scripts/docker-entrypoint.sh` — Container entrypoint with migrations

## Note

Docker configurations will be finalized in WP-06 (Deployment and Operational Tooling). Placeholder files may be added as needed.
