# 11. Risks and Technical Debt

## 11.1 Current Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| 1 | SQLite write contention under heavy concurrent workflow execution | Low | Medium | WAL mode; async execution serialization; upgrade to PostgreSQL if needed |
| 2 | Hand-written vanilla JS becomes unstructured as board interactions grow | Medium | Medium | ES modules per feature, one state owner per concern, UI tests; reconsider a framework only if needed (ADR-010) |
| 3 | GIL limiting concurrent Python execution for CPU-bound tasks | Low | Low | Async-first architecture; multiprocessing for CPU-bound work if needed |
| 4 | Docker image size (~200MB Python) | Low | Low | Distroless base image; multi-stage builds |
| 5 | SQLite backup during active writes | Medium | Low | WAL mode enables safe file-copy backup; document procedure |
| 6 | Secret exposure via logs or env vars in logs | Medium | High | Structured logging with explicit secret masking; no logging of sensitive fields |

## 11.2 Technical Debt

No intentional technical debt has been introduced at this stage.

**Known trade-offs to revisit:**

| Trade-off | Decision | Review Point |
|-----------|----------|--------------|
| SQLite vs. PostgreSQL | SQLite for simplicity | WP-06 — evaluate PostgreSQL if write contention emerges |
| Frontend stack | Jinja2 shell + vanilla JS, no HTMX (ADR-010) | When drag & drop / board API is built — decide DnD mechanism and rendering model |
| Docs drifted from reality | ADR-004 described a stack that was never built; corrected 2026-11-20 | Verify arc42/ADRs against code at each WP completion |
| No auth in foundation | Defer authentication | WP-06 — implement JWT auth for multi-user |
| No background task queue | Asyncio tasks only | WP-03 — evaluate Celery/arq for workflow scale |

---

*This chapter follows the arc42 template. TBD fields are limited to risks introduced in later Work Packages.*
