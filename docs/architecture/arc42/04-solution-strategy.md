# 4. Solution Strategy

## 4.1 Technology Decisions

| Layer | Technology | Reference |
|-------|------------|-----------|
| Application Language | Python 3.12+ | [ADR-002](../adr/002-application-language.md) |
| Backend Framework | FastAPI + Pydantic v2 | [ADR-003](../adr/003-backend-framework.md) |
| Frontend | HTMX + Jinja2 + Tailwind CSS | [ADR-004](../adr/004-frontend-approach.md) |
| Database | SQLite (WAL mode) | [ADR-005](../adr/005-database-persistence.md) |
| Migration | Alembic | [ADR-005](../adr/005-database-persistence.md) |
| API | REST + OpenAPI + WebSocket | [ADR-006](../adr/006-api-design.md) |
| Deployment | Docker + Docker Compose | [ADR-007](../adr/007-docker-distribution.md) |

## 4.2 Feature Location

```
┌─────────────────────────────────────────────────────────────┐
│                  OpenArtifact                               │
│                                                             │
│  ┌─────────────┐ ┌─────────────┐ ┌───────────────────────┐ │
│  │  HTTP Layer │ │  Workflow   │ │     Artifact Store    │ │
│  │             │ │   Engine    │ │                       │ │
│  │ FastAPI     │ │ Asyncio     │ │ Pydantic Models       │ │
│  │ Routes      │ │ Task Mgmt   │ │ SQLite (WAL mode)     │ │
│  └──────┬──────┘ └──────┬──────┘ └──────────┬────────────┘ │
│         │               │                    │              │
│  ┌──────▼───────────────▼────────────────────▼────────────┐ │
│  │              Application Core                          │ │
│  │  Config · Logging · Lifecycle · Alembic Migrations    │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

- **HTTP Layer** — FastAPI routes serving HTMX templates and REST API
- **Workflow Engine** — Asyncio-based concurrent workflow execution
- **Artifact Store** — Pydantic models persisted to SQLite (WAL)
- **Application Core** — Configuration, logging, lifecycle, migrations
- **Migration Layer** — Alembic versioned schema management

## 4.3 Implementation Progress

| Phase | Work Package | Status |
|-------|--------------|--------|
| WP-00 | Repository bootstrap, architecture documentation | ✅ Done |
| WP-01 | Define technical foundation and technology decisions | ✅ Done |
| WP-02 | Python project foundation (pyproject.toml, ruff, mypy, pytest) | ✅ Done |
| WP-03 | Application runtime (FastAPI server, health, web shell) | ✅ Done |
| WP-04 | Persistent storage and database migrations | ✅ Done |
| WP-05 | Core artifact model and domain types | ⏳ Planned |
| WP-06 | Workflow orchestration engine | ⏳ Planned |
| WP-07 | Agent integration framework | ⏳ Planned |
| WP-08 | Human oversight and review mechanisms | ⏳ Planned |
| WP-09 | Docker distribution and operational tooling | ⏳ Planned |
| WP-10 | External integrations | ⏳ Planned |

---

*This chapter follows the arc42 template. Implementation progress updated per WP completion.*
