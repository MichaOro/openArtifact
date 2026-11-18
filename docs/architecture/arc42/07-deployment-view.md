# 7. Deployment View

## 7.1 Runtime-Environment Overview

```
┌─────────────────────────────────────────────┐
│           Docker Host (Linux)               │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │  OpenArtifact Container             │    │
│  │                                     │    │
│  │  ┌─────────────┐  ┌──────────────┐  │    │
│  │  │  FastAPI    │  │   SQLite     │  │    │
│  │  │  (Port 2909)│  │  (WAL mode)  │  │    │
│  │  └─────────────┘  └──────────────┘  │    │
│  │           ▲                         │    │
│  │  USER: 1000, READ-ONLY where        │    │
│  │  possible, Distroless base image    │    │
│  └──────────┬──────────────────────────┘    │
│             │                               │
│  ┌──────────▼──────────────────────────┐    │
│  │  Docker Volume: /data               │    │
│  │  (SQLite database, persistent)      │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

## 7.2 Development Environment

- Local Python 3.12+ with `uv` for package management
- SQLite (local file, no server)
- `docker compose up -d` for integration testing
- Alembic for schema migrations

## 7.3 Deployment Environment

| Aspect | Configuration |
|--------|---------------|
| Image | Multi-stage build, Python slim base |
| User | Non-root (UID 1000) |
| Port | 2909 (configurable) |
| Volume | `/data` — persistent application data |
| Health check | `/health` endpoint |
| Restart | `restart: unless-stopped` |
| Env config | `.env` file or Docker env |

Default docker-compose.yml (SQLite):

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

volumes:
  openartifact-data:
```

---

*This chapter follows the arc42 template. TBD fields are limited to deployment changes introduced in later Work Packages.*
