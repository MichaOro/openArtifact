# scripts

- `docker-entrypoint.sh` — container entrypoint: runs `alembic upgrade head` (the container stops if a migration fails), then `exec openartifact`, the same command that starts the server outside Docker. It sets no defaults; the settings and their defaults live in `apps/backend/openartifact/config.py`. Behind a TLS proxy set `FORWARDED_ALLOW_IPS` (read by uvicorn).
