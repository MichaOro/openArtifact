# 4. Solution Strategy

## 4.1 Technology Decisions

| Layer | Technology | Reference |
|-------|------------|-----------|
| Application Language | Python 3.12+ | [ADR-002](../adr/002-application-language.md) |
| Backend Framework | FastAPI + Pydantic v2 | [ADR-003](../adr/003-backend-framework.md) |
| Frontend | Jinja2 + CSS design tokens + vanilla JS | [ADR-010](../adr/010-frontend-without-htmx.md) (supersedes ADR-004) |
| Database | SQLite (WAL mode) | [ADR-005](../adr/005-database-persistence.md) |
| Migration | Alembic | [ADR-005](../adr/005-database-persistence.md) |
| API | REST + OpenAPI (WebSocket/SSE planned) | [ADR-006](../adr/006-api-design.md) |
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

- **HTTP Layer** — FastAPI routes serving server-rendered Jinja2 pages, static assets and REST API
- **Workflow Engine** — Asyncio-based concurrent workflow execution
- **Artifact Store** — Pydantic models persisted to SQLite (WAL)
- **Application Core** — Configuration, logging, lifecycle, migrations
- **Migration Layer** — Alembic versioned schema management
- **Docker Layer** — Multi-stage build, entrypoint script, compose config

## 4.3 Implementation Progress

> The bootstrap phase (WP-00 … WP-05) is complete (git tag `bootstrap-complete`). Feature work continues on feature branches; see 4.4 for the current frontend state.

| Phase | Work Package | Status |
|-------|--------------|--------|
| WP-00 | Repository bootstrap, architecture documentation | ✅ Done |
| WP-01 | Define technical foundation and technology decisions | ✅ Done |
| WP-02 | Python project foundation (pyproject.toml, ruff, mypy, pytest) | ✅ Done |
| WP-03 | Application runtime (FastAPI server, health, web shell) | ✅ Done |
| WP-04 | Persistent storage and database migrations | ✅ Done |
| WP-05 | Docker deployment and all-in-one distribution | ✅ Done |
| WP-06 | Core artifact model and domain types | ⏳ Planned |
| WP-07 | Workflow orchestration engine | ⏳ Planned |
| WP-08 | AI agent integration framework | ⏳ Planned |
| WP-09 | Human oversight and review mechanisms | ⏳ Planned |
| WP-10 | External integrations | ⏳ Planned |

## 4.4 Frontend Status (as of 2026-11-20)

| Area | State |
|------|-------|
| App shell (sidebar, header, theme toggle) | ✅ Implemented — Jinja2 + CSS tokens + vanilla JS |
| Light / Dark theme | ✅ Implemented, persisted in `localStorage`, follows system on first visit |
| Kanban board (3 lanes, counters, empty states) | ✅ Implemented; tasks are loaded from `GET /api/tasks` and rendered client-side |
| Task creation (+ per lane, glass modal) | ✅ Implemented — `POST /api/tasks`, table `tasks` (migration 0003), persisted in SQLite |
| Drag & drop of cards | ⏳ Planned (mechanism open, see ADR-010 §3) |
| Editing/deleting tasks, priorities, tags, due dates, assignees | ⏳ Planned, not implemented |
| Projects (`Project`/`WorkItem` models) | ⏳ Models + migration 0002 exist; no API/UI, **not connected to the board** (the board uses `tasks`) |
| Real-time updates (WebSocket/SSE) | ⏳ Planned, not implemented |
| HTMX, Tailwind CSS, Alpine.js | ❌ Never used; HTMX removed (ADR-010) |

---

*This chapter follows the arc42 template. Implementation progress updated per WP completion.*
