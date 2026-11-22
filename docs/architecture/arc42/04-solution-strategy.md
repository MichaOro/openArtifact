# 4. Solution Strategy

## 4.1 Technology Decisions

| Layer | Technology | Reference |
|-------|------------|-----------|
| Application Language | Python 3.12+ | [ADR-002](../adr/002-application-language.md) |
| Backend Framework | FastAPI + Pydantic v2 | [ADR-003](../adr/003-backend-framework.md) |
| Frontend | Jinja2 + CSS design tokens + vanilla JS | [ADR-010](../adr/010-frontend-without-htmx.md) (supersedes ADR-004) |
| Dialogs | Native `<dialog>`, one class hierarchy, ARIA tabs | [ADR-029](../adr/029-dialog-system.md) |
| Database | SQLite (WAL mode), for good | [ADR-005](../adr/005-database-persistence.md), [ADR-020](../adr/020-sqlite-stays-postgres-as-data-source.md) |
| Migration | Alembic | [ADR-005](../adr/005-database-persistence.md) |
| API | REST + OpenAPI + SSE for live updates | [ADR-006](../adr/006-api-design.md), [ADR-011](../adr/011-board-interactions-sse-and-pointer-dnd.md) |
| Deployment | Docker + Docker Compose | [ADR-007](../adr/007-docker-distribution.md) |
| Access and hardening | One token, signed sessions, request hardening | [ADR-016](../adr/016-access-protection-integration-api-and-mcp.md), [ADR-017](../adr/017-request-hardening-and-signed-sessions.md) |
| Execution | In-process `asyncio` run engine | [ADR-013](../adr/013-execution-engine-and-runs.md), [ADR-018](../adr/018-typed-runs-one-error-one-persistence-rule.md) |
| Execution nodes | Executor registry: Code and HTTP nodes; settings as JSON `config` | [ADR-021](../adr/021-execution-nodes-as-executors.md), [ADR-022](../adr/022-node-settings-as-json-config.md) |
| Safety of execution nodes | Resource-limited child processes, SSRF guard; no sandbox | [ADR-023](../adr/023-safety-model-of-execution-nodes.md) |
| Credentials | `secrets` table, AES-256-GCM, references `${secret:NAME}`, masking by value | [ADR-024](../adr/024-credential-store.md) |
| History | `executions` and `run_node_results`, retention per artifact, origin `started_by`, replayed flow, global list with keyset paging | [ADR-025](../adr/025-execution-history-and-retention.md), [ADR-026](../adr/026-origin-of-a-run-started-by.md), [ADR-027](../adr/027-execution-flow-by-replay-over-the-frozen-snapshot.md), [ADR-028](../adr/028-global-executions-page-and-keyset-paging.md) |
| Accessibility | Known scope and limits | [ADR-030](../adr/030-accessibility-scope.md) |
| Licence | Apache-2.0 | [ADR-031](../adr/031-licence-apache-2-0.md) |
| Unused workspace model removed | `Project`/`WorkItem` and `repositories/` gone (migration 0026) | [ADR-032](../adr/032-removal-of-the-unused-workspace-model.md) |

## 4.2 Feature Location

```
┌───────────────────────────────────────────────────────────────────────┐
│                           OpenArtifact                                │
│                                                                       │
│  ┌─────────────┐  ┌─────────────────────────┐  ┌───────────────────┐  │
│  │ HTTP Layer  │  │      Run engine         │  │  Stores           │  │
│  │ FastAPI     │  │ walk · executors        │  │ tasks, graphs     │  │
│  │ REST · /mcp │  │ (Code, HTTP, timer)     │  │ executions, steps │  │
│  │ SSE · pages │  │ history · flow replay   │  │ secrets (AES-GCM) │  │
│  └──────┬──────┘  └────────────┬────────────┘  └─────────┬─────────┘  │
│         │                      │                         │            │
│  ┌──────▼──────────────────────▼─────────────────────────▼─────────┐  │
│  │                      Application Core                           │  │
│  │   Config · Logging · Lifecycle · Event bus · Alembic migrations │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
```

- **HTTP Layer** — FastAPI routes: server-rendered Jinja2 pages, static assets, the browser API, the integration API, the MCP server and the SSE stream
- **Run engine** — asyncio tasks that walk a pipeline; executors for Code, HTTP and timer nodes; recording of executions and steps; retention; replay of the walked path for the flow view
- **Stores** — artifacts and graphs, the execution history, and the credential store (SQLAlchemy over SQLite, WAL)
- **Application Core** — configuration, logging, lifecycle, event bus, migrations
- **Docker Layer** — Multi-stage build, entrypoint script (runs `alembic upgrade head`), compose config

## 4.3 Built and planned

This is the one place that says what exists. The bootstrap work packages (WP-00 to WP-05, git tag
`bootstrap-complete`) are history and are not repeated here. "Not built" means there is no code for it.

| Area | State | Reference |
|------|-------|-----------|
| Repository, documentation, tooling, runtime, migrations, Docker deployment | Built | [ch. 7](07-deployment-view.md) |
| Artifact model (cards, numbers, parents, pipeline target, `created_by`) | Built | [5.1](05-building-block-view/05.01-domain-model.md) |
| Pipelines and action definitions as graphs, canvas editor, node kinds as a registry | Built | ADR-012, ADR-014, ADR-015 |
| Run engine: start, stop, jump, sub-pipelines, timer node, recovery on restart | Built | ADR-013, ADR-018 |
| Code node (`sh`, `python`), resource limits, leftover cleanup | Built; no sandbox, needs an API token (or an explicit development switch) | ADR-021, ADR-023 |
| HTTP node with SSRF guard | Built | ADR-021, ADR-023 |
| Credential store | Built as API only; no UI | ADR-024 |
| Execution history per artifact with retention policy | Built | ADR-025 |
| Flow view of an execution (read-only, frozen snapshot) | Built | ADR-027 |
| Global executions page and API | Built | ADR-028 |
| Integration API (`/api/v1`) and MCP server (14 tools) | Built | ADR-016 |
| Access protection and request hardening | Built | ADR-016, ADR-017 |
| Settings area in the UI: loop protection, wall-clock deadlines, separate tokens | Not built (a run is cut off at 1000 steps; limits are environment variables) | |
| Human-in-the-loop (a `waiting` status), automatic starts by the system | Not built (`started_by` knows `system`, nothing sets it) | |
| Agent nodes (AI model providers), Git, notifications, PostgreSQL as a data source, connector layer | Not built | ADR-020 |
| Node versions, reordering and colouring of lanes, priorities, tags, due dates, assignees | Not built | |
| Third-party extensions (manifest, contract version, pages) | Not built | ADR-014 §3.5 |
| Keyboard creation of graph connections, screen-reader use of the editor | Not built; known limitation | ADR-030, chapter 11 |
| Rate limiting, per-session revocation, key rotation for secrets | Not built | chapter 11 |

## 4.4 Frontend Status

| Area | State |
|------|-------|
| App shell (sidebar, header, theme toggle) | Jinja2 + CSS tokens + vanilla JS; narrow screens collapse the sidebar to an overlay |
| Sign-in (`/login`), sign out | With an API token set the whole UI asks for it; signed, expiring session cookie (ADR-016, ADR-017) |
| Themes | Light "Sand Dune" and dark "Midnight Purple"; persisted in `localStorage`, follows the system on first visit |
| Kanban board | User-defined lanes (three at the start; add, rename, delete when empty; at most 12), counters, cards loaded from `GET /api/tasks`, rendered client-side; responsive (horizontal snap board on phones) |
| Cards | Create, view, edit, delete; fractional `position` for the order in a lane; parent/child tree; numbers `#n` never reused; `#n` in the text is a link, unknown numbers are struck through; `/?artifact=N` opens a card |
| Drag and drop | Mouse, touch and keyboard (Alt+arrows); Pointer Events, optimistic with rollback (ADR-011) |
| Live updates | SSE (`GET /api/events`), all tabs stay in sync, resync on reconnect; no WebSocket |
| Artifact dialog | Tabs Details and History; card navigation rail (lane, parent, pipeline, stage, action, start/stop, delete); sizing rule in [5.7](05-building-block-view/05.07-frontend-dialogs-tabs-and-flow-viewer.md) (ADR-029) |
| Pipeline and action editor | List and canvas: trigger, stages with one start and end, actions, connections by dragging (curved, straight or elbow; three attachment points per stage side); changes saved at once; inspector with settings per node kind including Code and HTTP (ADR-012, ADR-014, ADR-022) |
| Processing | Start and stop at a chosen pipeline, stage and action; the card is locked while it runs; state pushed by SSE (ADR-013) |
| History tab, flow page, executions page | List, detail with steps, retention editor, delete and clear; read-only flow on the editor canvas with drill-in; global list with filters and summary |
| Not implemented | Priorities, tags, due dates, assignees; reordering lanes; UI for credentials; keyboard creation of graph connections |
| Never used | HTMX, Tailwind CSS, Alpine.js (ADR-010) |
