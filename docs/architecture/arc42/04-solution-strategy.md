# 4. Solution Strategy

## 4.1 Technology Decisions

| Layer | Technology | Reference |
|-------|------------|-----------|
| Application Language | Python 3.12+ | [ADR-002](../adr/002-application-language.md) |
| Backend Framework | FastAPI + Pydantic v2 | [ADR-003](../adr/003-backend-framework.md) |
| Frontend | Jinja2 + CSS design tokens + vanilla JS | [ADR-010](../adr/010-frontend-without-htmx.md) (supersedes ADR-004) |
| Database | SQLite (WAL mode), for good | [ADR-005](../adr/005-database-persistence.md), [ADR-020](../adr/020-sqlite-stays-postgres-as-data-source.md) |
| Migration | Alembic | [ADR-005](../adr/005-database-persistence.md) |
| API | REST + OpenAPI + SSE for live updates | [ADR-006](../adr/006-api-design.md) |
| Deployment | Docker + Docker Compose | [ADR-007](../adr/007-docker-distribution.md) |
| Access and hardening | One token, signed sessions, request hardening | [ADR-016](../adr/016-access-protection-integration-api-and-mcp.md), [ADR-017](../adr/017-request-hardening-and-signed-sessions.md) |
| Execution | In-process `asyncio` run engine | [ADR-013](../adr/013-execution-engine-and-runs.md), [ADR-018](../adr/018-typed-runs-one-error-one-persistence-rule.md) |

## 4.2 Feature Location

```
┌─────────────────────────────────────────────────────────────┐
│                  OpenArtifact                               │
│                                                             │
│  ┌─────────────┐ ┌─────────────┐ ┌───────────────────────┐ │
│  │  HTTP Layer │ │  Pipeline   │ │     Artifact Store    │ │
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
- **Pipeline Engine** — Asyncio-based concurrent pipeline execution
- **Artifact Store** — Pydantic models persisted to SQLite (WAL)
- **Application Core** — Configuration, logging, lifecycle, migrations
- **Migration Layer** — Alembic versioned schema management
- **Docker Layer** — Multi-stage build, entrypoint script, compose config

## 4.3 Built and planned

This is the one place that says what exists. The bootstrap work packages (WP-00 to WP-05, git tag
`bootstrap-complete`) are history; the numbering is not maintained and the work-package list is not repeated here.

| Area | State |
|------|-------|
| Repository, documentation, tooling, runtime, migrations, Docker deployment | Built |
| Artifact model (cards, numbers, parents, pipeline target, `created_by`) | Built (chapter 5.1) |
| Pipelines and action definitions as graphs, canvas editor, node kinds as registry | Built (ADR-012, ADR-014, ADR-015) |
| Run engine: start, stop, jump, sub-pipelines, timer node, recovery on restart | Built (ADR-013, ADR-018) |
| Integration API (`/api/v1`) and MCP server (`/mcp`) | Built (ADR-016) |
| Access protection and request hardening | Built (ADR-016, ADR-017) |
| Execution history per artifact (a run per start) | Planned |
| Settings area: loop protection, wall-clock deadlines, separate tokens | Planned |
| Human-in-the-loop (a `waiting` status), automatic starts by the system | Planned |
| Real business logic in actions (AI agents, Git, webhooks), connector layer, PostgreSQL as a data source | Planned (ADR-020) |
| Third-party extensions (manifest, contract version, pages) | Planned (ADR-014 §3.5) |
| Keyboard and screen-reader use of the graph editor (connections), rate limiting, per-session revocation | Planned, see chapter 11 |

## 4.4 Frontend Status (as of 2026-11-22)

| Area | State |
|------|-------|
| App shell (sidebar, header, theme toggle) | ✅ Implemented — Jinja2 + CSS tokens + vanilla JS |
| Sign-in page (`/login`) and *Sign out* | ✅ With an API token set the whole UI asks for it; signed, expiring session cookie (ADR-016, ADR-017) |
| Light / Dark theme | ✅ Implemented, persisted in `localStorage`, follows system on first visit |
| Kanban board (3 lanes, counters, empty states) | ✅ Implemented; tasks are loaded from `GET /api/tasks` and rendered client-side |
| Task creation (+ per lane, glass modal) | ✅ Implemented — `POST /api/tasks`, table `tasks` (migration 0003), persisted in SQLite |
| Drag & drop of cards between lanes (mouse, touch; keyboard through Alt+arrows) | ✅ Implemented — Pointer Events, optimistic with rollback ([ADR-011](../adr/011-board-interactions-sse-and-pointer-dnd.md)) |
| Deleting tasks (confirmation dialog) | ✅ Implemented — `DELETE /api/tasks/{id}` |
| Viewing and editing artifacts | ✅ A card opens a read-only view; *Edit* switches to the form, *Save* returns to the view; `PATCH /api/tasks/{id}` (partial update) |
| Priorities, tags, due dates, assignees | ⏳ Planned, not implemented |
| Projects (`Project`/`WorkItem` models) | ❌ Models and migration 0002 exist but nothing uses them; quarantined in `quarantine.json` (the board uses `tasks`) |
| Real-time updates | ✅ Implemented as SSE (`GET /api/events`) with an in-process event bus; all tabs stay in sync, resync on reconnect. WebSocket is not used |
| Responsive layouts | ✅ Narrow (horizontal snap board) and narrow landscape (compact); sidebar auto-collapses and overlays on narrow screens |
| Card navigation (right rail in the task dialog) | ✅ Collapsible, collapsed by default; fields *Lane* and *Parent*, action *Delete*; expands to the right, form and toggle keep their position |
| Order of cards inside a lane | ✅ Drag within a lane or across lanes at a given place; Alt+↑/↓; stored as fractional `position` (migration 0004) |
| Parent / child artifacts | ✅ Tree: one parent, any number of children, cycle check, foreign key with `ON DELETE SET NULL` (migrations 0005, 0007) |
| Artifact numbers | ✅ `#n`, never reused (migration 0006); shown quietly in the dialog header; typing `#` in the body offers the board's artifacts ; in the read view `#n` is a link to that artifact, unknown numbers are struck through |
| Pipeline and action definitions | ✅ List and canvas editor: trigger, stages with one start and end, actions, connections by dragging (curved, straight or elbow lines; three attachment points per stage side; tight or backward connections routed around nodes); saved at once (ADR-012). Action definitions have their own list and canvas (trigger, output with On Pass / optional On Fail); actions in a stage are shells linked to a definition (ADR-012 §2.17); a timer node is the first logic in a definition (ADR-012 §2.19); specialised nodes and versions are planned |
| Pipeline runs | ✅ Start / stop an artifact in a pipeline at a chosen stage and action, earlier stages count as done, the artifact is locked while it runs, state is saved and pushed by SSE (ADR-013). Pipeline nodes call another pipeline like a sub-pipeline (ADR-013 §2.2). Runs are typed and capped (ADR-018). Planned: execution history per artifact, settings with a global loop protection |
| Lane colours | ✅ Palette tokens, lane N = hue N |
| Lane switch in the dialog | ✅ Click the lane chip (hidden feature) or the rail's *Lane* field |
| Lanes as configuration | ✅ `BOARD_LANES` is the single definition; user-defined lanes are planned, not implemented |
| Light theme | ✅ Sand Dune (warm cream/sand), dark theme Midnight Purple |
| HTMX, Tailwind CSS, Alpine.js | ❌ Never used; HTMX removed (ADR-010) |

