# 4. Solution Strategy

## 4.1 Technology Decisions

| Layer | Technology | Reference |
|-------|------------|-----------|
| Application Language | Python 3.12+ | [ADR-002](../adr/002-application-language.md) |
| Backend Framework | FastAPI + Pydantic v2 | [ADR-003](../adr/003-backend-framework.md) |
| Frontend | HTMX + Jinja2 + Tailwind CSS | [ADR-004](../adr/004-frontend-approach.md) |
| Database | SQLite (WAL mode) | [ADR-005](../adr/005-database-persistence.md) |
| API | REST + OpenAPI + WebSocket | [ADR-006](../adr/006-api-design.md) |
| Deployment | Docker + Docker Compose | [ADR-007](../adr/007-docker-distribution.md) |

## 4.2 Feature Location

```
┌─────────────────────────────────────────────────────┐
│                  OpenArtifact                       │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │   HTTP   │  │ Workflow │  │  Artifact Store   │  │
│  │  (FastAPI│  │  Engine  │  │  (SQLite/Pydantic│  │
│  │  Routes) │  │ (Asyncio)│  │   Models)         │  │
│  └────┬─────┘  └────┬─────┘  └────────┬─────────┘  │
│       │             │                  │             │
│  ┌────▼─────────────▼──────────────────▼─────────┐  │
│  │           Application Core                    │  │
│  │  (Configuration, Logging, Lifecycle)           │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

- **HTTP Layer** — FastAPI routes serving HTMX templates and REST API
- **Workflow Engine** — Asyncio-based concurrent workflow execution
- **Artifact Store** — Pydantic models persisted to SQLite
- **Application Core** — Configuration, logging, lifecycle management

## 4.3 Migration Strategy

From bootstrap to implementation:

1. WP-02: Repository structure and development tooling
2. WP-03: Core artifact model implementation
3. WP-04: Workflow engine and background execution
4. WP-05: Agent integration framework
5. WP-06: Human oversight and deployment hardening
6. WP-07: External integrations

---

*This chapter follows the arc42 template. TBD fields are limited to strategy changes introduced in later Work Packages.*
