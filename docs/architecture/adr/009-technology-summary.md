# ADR-009: Technology Summary and Implementation Roadmap

**Status:** Accepted  
**Date:** 2026-11-18  
**Supersedes:** —  
**Superseded by:** —

## 1. Title

Technology Stack Summary and WP Implementation Roadmap

## 2. Context

This ADR consolidates all technology decisions from ADR-002 through ADR-008 and provides implementation recommendations for subsequent Work Packages.

## 3. Technology Stack

| Layer | Decision | Rationale |
|-------|----------|-----------|
| **Language** | Python 3.12+ | AI ecosystem, async support, development productivity |
| **Backend** | FastAPI + Pydantic v2 | Auto OpenAPI, validation, async-first |
| **Frontend** | HTMX + Jinja2 + Tailwind | No build step, server-driven, simple deployment |
| **Database** | SQLite (WAL mode) | Zero-config, single-container, upgradeable to PostgreSQL |
| **API** | REST + OpenAPI + WebSocket | HTMX-native, real-time via SSE/WebSocket |
| **Packaging** | Docker + Docker Compose | Self-hosted distribution, port 2909 |
| **Task Queue** | Deferred to WP-03 | Celery or arq when workflow engine is built |

## 4. Docker Deployment

| Aspect | Decision |
|--------|----------|
| Port | 2909 (configurable via `PORT` env var) |
| Host | 0.0.0.0 (configurable via `HOST` env var) |
| Database | SQLite in `/data` volume |
| Health check | `/health` endpoint |
| Restart | `restart: unless-stopped` |
| Default image | Python slim base, multi-stage build |
| User | Non-root (UID 1000) |

## 5. Arc42 Updates

The following arc42 chapters have been updated:

- **Chapter 1** — Goals refined with technology context
- **Chapter 2** — Constraints documented (port, language, database, Docker)
- **Chapter 3** — Context defined (self-hosted user, Docker Compose)
- **Chapter 4** — Solution strategy with technology recommendations
- **Chapter 8** — Security and operations approach
- **Chapter 9** — 9 ADRs covering all significant decisions
- **Chapter 10** — Quality requirements identified
- **Chapter 11** — Risks and mitigation strategies

## 6. Risks and Open Questions

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| SQLite write contention under heavy load | Low (initial scope) | WAL mode; upgrade to PostgreSQL in WP-06 if needed |
| HTMX insufficient for complex dashboards | Medium | Add React incrementally if needed |
| GIL limiting concurrent Python execution | Low (async architecture) | Async-first design; multiprocessing if CPU-bound tasks emerge |
| Docker image size (~200MB Python) | Low (acceptable for server) | Distroless base image to reduce |

## 7. Open Questions

1. What is the exact artifact schema (WP-02)?
2. Which AI agent providers will be supported first (WP-04)?
3. What is the deployment target architecture — single-server or multi-server (WP-06)?
