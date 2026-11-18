# 11. Risks and Technical Debt

## 11.1 Current Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| 1 | SQLite write contention under heavy concurrent workflow execution | Low | Medium | WAL mode; async execution serialization; upgrade to PostgreSQL if needed |
| 2 | HTMX insufficient for complex interactive dashboards | Medium | Medium | Add React incrementally for specific views if needed |
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
| HTMX vs. SPA frontend | HTMX for simplicity | Ongoing — add React for complex views if needed |
| No auth in foundation | Defer authentication | WP-06 — implement JWT auth for multi-user |
| No background task queue | Asyncio tasks only | WP-03 — evaluate Celery/arq for workflow scale |

---

*This chapter follows the arc42 template. TBD fields are limited to risks introduced in later Work Packages.*
