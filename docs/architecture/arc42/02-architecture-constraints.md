# 2. Architecture Constraints

## 2.1 Technical Constraints

- **Language:** Python 3.12+ (ADR-002)
- **Backend:** FastAPI + Pydantic v2 (ADR-003)
- **Frontend:** Jinja2 templates + hand-written CSS (design tokens) + vanilla JavaScript (ADR-010)
- **Database:** SQLite (WAL mode) with Alembic migrations; PostgreSQL upgrade path (ADR-005)
- **API:** REST with OpenAPI (ADR-006); WebSocket/SSE for real-time is planned, not implemented
- **Packaging:** Multi-stage Docker build + Docker Compose (ADR-007)
- **Port:** Default 2909, configurable via `PORT` environment variable
- **Host:** Default 0.0.0.0, configurable via `HOST` environment variable
- **No build step for frontend** — templates and static assets served directly by FastAPI
- **No external runtime assets** — no CDN scripts or stylesheets; everything is served from `/static`
- **Colours only via design tokens** — raw colour values exist only in `static/css/tokens.css`; Light and Dark theme share one component structure

## 2.2 Organizational Constraints

- Multiple AI coding agents may work on the codebase concurrently
- Architecture documentation (arc42 + ADRs) must evolve with implementation
- Technology decisions must be documented before implementation

## 2.3 Contractual Constraints

- MIT License
- Open-source distribution
- Self-hosted deployment (no cloud dependency)

## 2.4 Platform Constraints

- **Runtime:** Docker (Linux containers)
- **Database:** SQLite file-based (local to container)
- **Operating system:** Linux (Debian-slim or Alpine base)
- **Memory:** Minimal footprint for single-instance deployment

---

*This chapter follows the arc42 template. TBD fields are limited to constraints identified during later Work Packages.*
