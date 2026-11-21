# 4. Solution Strategy

## 4.1 Technology Decisions

| Layer | Technology | Reference |
|-------|------------|-----------|
| Application Language | Python 3.12+ | [ADR-002](../adr/002-application-language.md) |
| Backend Framework | FastAPI + Pydantic v2 | [ADR-003](../adr/003-backend-framework.md) |
| Frontend | Jinja2 + CSS design tokens + vanilla JS | [ADR-010](../adr/010-frontend-without-htmx.md) (supersedes ADR-004) |
| Database | SQLite (WAL mode) | [ADR-005](../adr/005-database-persistence.md) |
| Migration | Alembic | [ADR-005](../adr/005-database-persistence.md) |
| API | REST + OpenAPI + SSE for live updates | [ADR-006](../adr/006-api-design.md) |
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

## 4.4 Frontend Status (as of 2026-11-21)

| Area | State |
|------|-------|
| App shell (sidebar, header, theme toggle) | ✅ Implemented — Jinja2 + CSS tokens + vanilla JS |
| Light / Dark theme | ✅ Implemented, persisted in `localStorage`, follows system on first visit |
| Kanban board (3 lanes, counters, empty states) | ✅ Implemented; tasks are loaded from `GET /api/tasks` and rendered client-side |
| Task creation (+ per lane, glass modal) | ✅ Implemented — `POST /api/tasks`, table `tasks` (migration 0003), persisted in SQLite |
| Drag & drop of cards between lanes (mouse, touch, keyboard) | ✅ Implemented — Pointer Events, optimistic with rollback ([ADR-011](../adr/011-board-interactions-sse-and-pointer-dnd.md)) |
| Deleting tasks (confirmation dialog) | ✅ Implemented — `DELETE /api/tasks/{id}` |
| Viewing and editing artifacts | ✅ A card opens a read-only view; *Edit* switches to the form, *Save* returns to the view; `PATCH /api/tasks/{id}` (partial update) |
| Priorities, tags, due dates, assignees | ⏳ Planned, not implemented |
| Projects (`Project`/`WorkItem` models) | ⏳ Models + migration 0002 exist; no API/UI, **not connected to the board** (the board uses `tasks`) |
| Real-time updates | ✅ Implemented as SSE (`GET /api/events`) with an in-process event bus; all tabs stay in sync, resync on reconnect. WebSocket is not used |
| Responsive layouts | ✅ Narrow (horizontal snap board) and narrow landscape (compact); sidebar auto-collapses and overlays on narrow screens |
| Card navigation (right rail in the task dialog) | ✅ Collapsible, collapsed by default; fields *Lane* and *Parent*, action *Delete*; expands to the right, form and toggle keep their position |
| Order of cards inside a lane | ✅ Drag within a lane or across lanes at a given place; Alt+↑/↓; stored as fractional `position` (migration 0004) |
| Parent / child artifacts | ✅ Tree: one parent, any number of children, cycle check, foreign key with `ON DELETE SET NULL` (migrations 0005, 0007) |
| Artifact numbers | ✅ `#n`, never reused (migration 0006); shown quietly in the dialog header; typing `#` in the body offers the board's artifacts ; in the read view `#n` is a link to that artifact, unknown numbers are struck through |
| Workflow definitions | ✅ List and canvas editor: trigger, stages with one start and end, actions, connections by dragging or through a routing select (curved, straight or elbow lines; three attachment points per stage side; tight or backward connections routed around nodes); saved at once (ADR-012). Action definitions have their own list and canvas (trigger, output with On Pass / optional On Fail); actions in a stage are shells linked to a definition (ADR-012 §2.17); a timer node is the first logic in a definition (ADR-012 §2.19); specialised nodes and versions are planned |
| Pipeline runs | ✅ Start / stop an artifact in a pipeline at a chosen stage and action, earlier stages count as done, the artifact is locked while it runs, state is saved and pushed by SSE (ADR-013). Pipeline nodes call another pipeline like a sub-workflow (ADR-013 §2.2). Planned: execution history per artifact, settings with a global loop protection |
| Lane colours | ✅ Palette tokens, lane N = hue N |
| Lane switch in the dialog | ✅ Click the lane chip (hidden feature) or the rail's *Lane* field |
| Lanes as configuration | ✅ `BOARD_LANES` is the single definition; user-defined lanes are planned, not implemented |
| Light theme | ✅ Sand Dune (warm cream/sand), dark theme Midnight Purple |
| HTMX, Tailwind CSS, Alpine.js | ❌ Never used; HTMX removed (ADR-010) |

---

*This chapter follows the arc42 template. Implementation progress updated per WP completion.*
