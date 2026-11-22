# 2. Architecture Constraints

## 2.1 Technical Constraints

- **Language:** Python 3.12+ (ADR-002)
- **Backend:** FastAPI + Pydantic v2 (ADR-003)
- **Frontend:** Jinja2 templates + hand-written CSS (design tokens) + vanilla JavaScript (ADR-010)
- **Database:** SQLite (WAL mode) with Alembic migrations, for good: the application's own data stays in one SQLite file. PostgreSQL is not an upgrade path; it may later appear as a data source behind a connector layer (ADR-020)
- **API:** REST with OpenAPI (ADR-006); server-sent events (`GET /api/events`) for live updates, no WebSocket (ADR-011)
- **Packaging:** Multi-stage Docker build + Docker Compose (ADR-007)
- **Settings:** environment variables with the prefix `OPENARTIFACT_` (for example `OPENARTIFACT_PORT`, default 2909, and `OPENARTIFACT_HOST`, default `0.0.0.0`); the complete list is in the [configuration reference](../../guides/configuration.md)
- **One process:** the event bus, the run engine, the run and stream caps and the child processes of Code nodes live in one process; one container per volume (chapter 11)
- **Runtime libraries beyond the web stack:** `cryptography` (AES-GCM for the credential store, ADR-024) and `httpx` (HTTP nodes, ADR-021); the MCP SDK (`mcp`) serves `/mcp`
- **Code nodes need Linux:** the limits and the cleanup use `resource`, `/proc` and `PR_SET_PDEATHSIG`; where `resource` is missing the code runs without limits and the step says so. Code files are written to the system temp directory (the container mounts a tmpfs on `/tmp`)
- **No build step for frontend** — templates and static assets served directly by FastAPI
- **No external runtime assets** — no CDN scripts or stylesheets; everything is served from `/static` (the Swagger UI at `/api/docs` is the one exception and has its own policy)
- **Content-Security-Policy `script-src 'self'`** — templates carry no inline scripts (ADR-017)
- **Colours only via design tokens** — raw colour values exist only in `static/css/tokens.css`; Light and Dark theme share one component structure

## 2.2 Organizational Constraints

- Multiple AI coding agents may work on the codebase concurrently
- Architecture documentation (arc42 + ADRs) must evolve with implementation
- Technology decisions must be documented before implementation
- Release tags equal `openartifact/version.py`; tests run under coverage in CI (see the [CI/CD guide](../../guides/CI-CD.md))

## 2.3 Contractual Constraints

- Apache License 2.0 (ADR-031); dependencies must be compatible with it
- Open-source distribution
- Self-hosted deployment (no cloud dependency)

## 2.4 Platform Constraints

- **Runtime:** Docker (Linux containers)
- **Database:** SQLite file-based (local to container)
- **Operating system:** Linux (the image is `python:3.12-slim`; read-only root file system, `/data` the only volume, a tmpfs on `/tmp`)
- **Memory:** Minimal footprint for single-instance deployment; the container has a memory limit, and each Code node has its own limits (see [8.1](08-cross-cutting-concepts/08.01-security.md))
- **Accessibility:** keyboard-only creation of graph connections and screen-reader use of the editor are a later goal and a known limitation (ADR-030); the board, dialogs and the execution flow page are built for keyboard use
