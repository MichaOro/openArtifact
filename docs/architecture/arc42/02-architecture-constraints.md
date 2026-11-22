# 2. Architecture Constraints

## 2.1 Technical Constraints

- **Language:** Python 3.12+ (ADR-002)
- **Backend:** FastAPI + Pydantic v2 (ADR-003)
- **Frontend:** Jinja2 templates + hand-written CSS (design tokens) + vanilla JavaScript (ADR-010)
- **Database:** SQLite (WAL mode) with Alembic migrations, for good: the application's own data stays in one SQLite file. PostgreSQL is not an upgrade path; it may later appear as a data source behind a connector layer (ADR-020)
- **API:** REST with OpenAPI (ADR-006); server-sent events (`GET /api/events`) for live board updates, no WebSocket (ADR-011)
- **Packaging:** Multi-stage Docker build + Docker Compose (ADR-007)
- **Settings:** environment variables with the prefix `OPENARTIFACT_` (for example `OPENARTIFACT_PORT`, default 2909, and `OPENARTIFACT_HOST`, default `0.0.0.0`); the complete list is in the [configuration reference](../../guides/configuration.md)
- **One process:** the event bus, the run engine and the run and stream caps live in the memory of one process; one container per volume (chapter 11)
- **No build step for frontend** — templates and static assets served directly by FastAPI
- **No external runtime assets** — no CDN scripts or stylesheets; everything is served from `/static` (the Swagger UI at `/api/docs` is the one exception and has its own policy)
- **Content-Security-Policy `script-src 'self'`** — templates carry no inline scripts (ADR-017)
- **Colours only via design tokens** — raw colour values exist only in `static/css/tokens.css`; Light and Dark theme share one component structure

## 2.2 Organizational Constraints

- Multiple AI coding agents may work on the codebase concurrently
- Architecture documentation (arc42 + ADRs) must evolve with implementation
- Technology decisions must be documented before implementation

## 2.3 Contractual Constraints

- Apache License 2.0
- Open-source distribution
- Self-hosted deployment (no cloud dependency)

## 2.4 Platform Constraints

- **Runtime:** Docker (Linux containers)
- **Database:** SQLite file-based (local to container)
- **Operating system:** Linux (the image is `python:3.12-slim`; read-only root file system, `/data` the only volume)
- **Memory:** Minimal footprint for single-instance deployment

