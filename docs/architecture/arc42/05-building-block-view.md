# 5. Building Block View

## 5.1 Domain Model

> TBD — Domain entities (Project, Artifact, Workflow, Execution) to be defined in WP-05.

## 5.2 Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      OpenArtifact                           │
│                                                             │
│  ┌─────────────┐ ┌─────────────┐ ┌───────────────────────┐ │
│  │  HTTP Layer │ │  Workflow   │ │     Artifact Store    │ │
│  │             │ │   Engine    │ │                       │ │
│  │ FastAPI     │ │ Asyncio     │ │ Pydantic Models       │ │
│  │ Routes      │ │ Task Mgmt   │ │ SQLite Persistence    │ │
│  └──────┬──────┘ └──────┬──────┘ └──────────┬────────────┘ │
│         │               │                    │              │
│  ┌──────▼───────────────▼────────────────────▼────────────┐ │
│  │              Application Core                          │ │
│  │  Config · Logging · Lifecycle · Database Migrations    │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

Implemented (WP-03): HTTP layer, application core.
Planned (WP-04+): Workflow engine, artifact store.

## 5.3 Component View

### Implemented Components (WP-03)

| Component | Location | Description |
|-----------|----------|-------------|
| `app` | `openartifact/app.py` | FastAPI factory, lifespan hooks, exception handlers |
| `api.routes` | `openartifact/api/routes.py` | `/api/health`, `/api/info` endpoints |
| `web.routes` | `openartifact/web/routes.py` | `/` HTML template rendering |
| `config` | `openartifact/config.py` | pydantic-settings, env-based configuration |
| `cli` | `openartifact/cli.py` | uvicorn entry point |
| `logging_config` | `openartifact/logging_config.py` | Structured logging with secret masking |

### Planned Components (WP-04+)

| Component | Location | Description |
|-----------|----------|-------------|
| `models/` | `openartifact/models/` | Domain models (Project, Artifact, Workflow) |
| `database` | `openartifact/database.py` | SQLAlchemy engine, Alembic migrations |
| `workflow/` | `openartifact/workflow/` | Workflow execution engine |
| `templates/` | `openartifact/templates/` | Jinja2 HTML templates |
| `static/` | `openartifact/static/` | CSS, JS, image assets |

## 5.4 Interface View

| Component | Interface | Protocol | Status |
|-----------|-----------|----------|--------|
| HTTP Layer | REST API | HTTP/1.1 | ✅ WP-03 |
| HTTP Layer | HTMX templates | HTTP/1.1 + HTML | ✅ WP-03 |
| HTTP Layer | OpenAPI/Swagger | /api/docs | ✅ WP-03 |
| HTTP Layer | Real-time progress | WebSocket / SSE | ⏳ WP-06 |
| Artifact Store | SQLite database | SQLite (file) | ⏳ WP-04 |
| External | AI Agent APIs | HTTP/HTTPS | ⏳ WP-07 |

---

*This chapter follows the arc42 template. TBD fields are limited to components introduced in later Work Packages.*
