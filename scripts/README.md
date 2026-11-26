# scripts

- `docker-entrypoint.sh` — container entrypoint: runs `alembic upgrade head` (the container stops if a migration fails), then `exec openartifact`, the same command that starts the server outside Docker. It sets no defaults; the settings and their defaults live in `openartifact/config.py` and are described in the [configuration reference](../docs/guides/configuration.md). Behind a TLS proxy set `FORWARDED_ALLOW_IPS` (read by uvicorn). The container itself (read-only file system, dropped capabilities, limits) is described in [deploy/README.md](../deploy/README.md).
