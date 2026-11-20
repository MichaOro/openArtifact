# 5. Building Block View

## 5.1 Domain Model

> TBD — Domain entities (Project, Artifact, Workflow, Execution) to be defined in WP-06.

## 5.2 Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                  Docker Container                            │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  ┌─────────────┐ ┌─────────────┐ ┌───────────────┐  │    │
│  │  │  HTTP Layer │ │  Workflow   │ │ Artifact Store│  │    │
│  │  │             │ │   Engine    │ │               │  │    │
│  │  │ FastAPI     │ │ Asyncio     │ │ Pydantic      │  │    │
│  │  │ Routes      │ │ Task Mgmt   │ │ SQLite (WAL)  │  │    │
│  │  └──────┬──────┘ └──────┬──────┘ └───────┬───────┘  │    │
│  │         │               │                 │          │    │
│  │  ┌──────▼───────────────▼─────────────────▼─────────┐ │    │
│  │  │           Application Core                       │ │    │
│  │  │  Config · Logging · Lifecycle · Alembic Migrations│ │    │
│  │  └──────────────────────────────────────────────────┘ │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  docker-entrypoint.sh                                │    │
│  │  └─ Alembic upgrade → uvicorn --factory              │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

Implemented (WP-03/04/05): Docker deployment, HTTP layer, database, entrypoint.
Planned (WP-06+): Workflow engine, artifact store, domain models.

## 5.3 Component View

### Implemented Components (WP-03/04/05)

| Component | Location | Description |
|-----------|----------|-------------|
| `app` | `openartifact/app.py` | FastAPI factory, lifespan hooks, exception handlers |
| `api.routes` | `openartifact/api/routes.py` | `/api/health`, `/api/info` endpoints |
| `web.routes` | `openartifact/web/routes.py` | `/` HTML template rendering |
| `config` | `openartifact/config.py` | pydantic-settings, env-based configuration |
| `cli` | `openartifact/cli.py` | uvicorn entry point |
| `logging_config` | `openartifact/logging_config.py` | Structured logging with secret masking |
| `database` | `openartifact/database.py` | Engine, session, WAL mode, context managers |
| `alembic/` | `alembic.ini` | Migration configuration and scripts |
| `Dockerfile` | `Dockerfile` | Multi-stage build (builder + runtime) |
| `scripts/entrypoint` | `scripts/docker-entrypoint.sh` | Migration + server start |
| `deploy/compose` | `deploy/docker-compose.yml` | Single-container deployment |

### Planned Components (WP-06+)

| Component | Location | Description |
|-----------|----------|-------------|
| `models/` | `openartifact/models/` | Domain models (Project, Artifact, Workflow) |
| `workflow/` | `openartifact/workflow/` | Workflow execution engine |
| `templates/` | `openartifact/templates/` | Jinja2 HTML templates |
| `static/` | `openartifact/static/` | `css/` (tokens, base, components), `js/` (theme/sidebar state, UI wiring) |

## 5.4 Interface View

| Component | Interface | Protocol | Status |
|-----------|-----------|----------|--------|
| HTTP Layer | REST API | HTTP/1.1 | ✅ WP-03 |
| HTTP Layer | Server-rendered pages (Jinja2) + `/static` assets | HTTP/1.1 + HTML | ✅ WP-03 |
| HTTP Layer | Tasks API (`GET`/`POST /api/tasks`) | HTTP/1.1 + JSON | ✅ |
| HTTP Layer | OpenAPI/Swagger | /api/docs | ✅ WP-03 |
| HTTP Layer | Live board updates (`GET /api/events`) | SSE (text/event-stream) | ✅ |
| HTTP Layer | Workflow progress streaming | SSE | ⏳ WP-07 |
| Artifact Store | SQLite database | SQLite (WAL mode) | ✅ WP-04 |
| External | AI Agent APIs | HTTP/HTTPS | ⏳ WP-08 |
| Docker | Health check | HTTP GET /health | ✅ WP-05 |

---

*This chapter follows the arc42 template. TBD fields are limited to components introduced in later Work Packages.*
