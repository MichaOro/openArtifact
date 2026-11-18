# 7. Deployment View

## 7.1 Runtime-Environment Overview

```
┌───────────────────────────────────────────────────────────┐
│              Docker Host (Linux)                           │
│                                                            │
│  ┌───────────────────────────────────────────────────────┐│
│  │  OpenArtifact Container (UID 1000, non-root)          ││
│  │                                                       ││
│  │  ┌─────────────┐  ┌──────────────┐                   ││
│  │  │  FastAPI    │  │   SQLite     │                   ││
│  │  │  (Port 2909)│  │  (WAL mode)  │                   ││
│  │  │  Uvicorn    │  │  /data/      │                   ││
│  │  └──────┬──────┘  └──────┬───────┘                   ││
│  │         │                │                           ││
│  │  docker-entrypoint.sh                                    ││
│  │    alembic → uvicorn --factory                         ││
│  └──────────┬─────────────────────────────────────────────┘│
│             │                                              │
│  ┌──────────▼─────────────────────────────────────────────┐│
│  │  Docker Volume: openartifact-data                      ││
│  │  /data/                                                ││
│  │    openartifact.db                                     ││
│  │    openartifact.db-wal                                 ││
│  │    openartifact.db-shm                                 ││
│  └───────────────────────────────────────────────────────┘│
└───────────────────────────────────────────────────────────┘
```

## 7.2 Development Environment

- Local Python 3.12+ with `uv` for package management
- SQLite (local file, no server)
- `uv run openartifact` to start
- `uv run alembic upgrade head` for migrations
- `docker compose -f deploy/docker-compose.yml up` for full integration testing

## 7.3 Deployment Environment

### Docker Image

| Aspect | Configuration |
|--------|---------------|
| Build | Multi-stage (builder + runtime) |
| Base Image | python:3.12-slim |
| Runtime User | openartifact (UID 1000, non-root) |
| Port | 2909 (configurable) |
| Volume | `/data` — persistent application data |
| Health check | `curl -f http://localhost:2909/health` |
| Restart | `restart: unless-stopped` |
| Env config | `.env` file or Docker env |

### Dockerfile Structure

```
Stage 1 (builder):
  - python:3.12-slim
  - Install dependencies from pyproject.toml
  - Copy application source

Stage 2 (runtime):
  - python:3.12-slim
  - Copy installed wheels from builder
  - Copy application source + alembic config
  - Create /data with correct ownership
  - USER openartifact (non-root)
  - ENTRYPOINT: docker-entrypoint.sh
```

### Docker Compose

```yaml
services:
  openartifact:
    build: .
    ports:
      - "2909:2909"
    volumes:
      - openartifact-data:/data
    env_file: .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:2909/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

volumes:
  openartifact-data:
```

### User Commands

| Action | Command |
|--------|---------|
| Build & start | `docker compose -f deploy/docker-compose.yml up -d` |
| Stop | `docker compose -f deploy/docker-compose.yml down` |
| Logs | `docker compose -f deploy/docker-compose.yml logs -f` |
| Health | `docker inspect --format='{{.State.Health.Status}}' openartifact` |
| Update | `docker compose pull && docker compose up -d` |
| Backup | `docker run --rm -v openartifact-data:/data -v $(pwd):/backup alpine cp /data/openartifact.db /backup/` |

**Important:** `docker compose down` does NOT delete persistent data. The volume `openartifact-data` survives. Use `docker compose down -v` only to remove persistent data.

---

*This chapter follows the arc42 template. Deployment details documented as WP-05 completed.*
