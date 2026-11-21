# 11. Risks and Technical Debt

## 11.1 Current Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| 1 | SQLite write contention under heavy concurrent workflow execution | Low | Medium | WAL mode; async execution serialization; upgrade to PostgreSQL if needed |
| 2 | Hand-written vanilla JS becomes unstructured as board interactions grow | Medium | Medium | ES modules per feature, one state owner per concern, UI tests; reconsider a framework only if needed (ADR-010) |
| 3a | In-process event bus: with more than one worker process, SSE clients only see events of their own worker | Low | Medium | Single `uvicorn` process today; for scale-out put a shared broker (e.g. Redis pub/sub) behind the `EventBus` interface (ADR-011) |
| 3 | GIL limiting concurrent Python execution for CPU-bound tasks | Low | Low | Async-first architecture; multiprocessing for CPU-bound work if needed |
| 4 | Docker image size (~200MB Python) | Low | Low | Distroless base image; multi-stage builds |
| 5 | SQLite backup during active writes | Medium | Low | WAL mode enables safe file-copy backup; document procedure |
| 6 | Secret exposure via logs or env vars in logs | Medium | High | Structured logging with explicit secret masking; no logging of sensitive fields |

## 11.2 Technical Debt

No intentional technical debt has been introduced at this stage.

**Known gaps and trade-offs (deliberate):**

| Item | State |
|------|-------|
| `#12` references are resolved at display time | Not validated on save (a body may contain `#5` as plain text); no back-references ("referenced by") yet |
| Parent picker without search | Becomes necessary with many artifacts |
| `Project`/`WorkItem` models not connected to the board | To be reconciled with the artifact model in WP-06 |
| Workflow editor: stages only grow, no undo, no live sync between tabs, edges without routing | See ADR-012 §2.4 |
| Workflow editor: stages only grow, no undo, no live sync between tabs, edges routed only for loops | See ADR-012 §2.4 |
| Runs can loop for ever (an On Error routed back to its own action, a loop between actions): only a fixed limit of 1000 steps ends them | Planned: a *Settings* area with a global loop protection (limits, behaviour), reconsidered together with pipeline blocks; see ADR-013 §4 |
| One run per artifact: an earlier run is overwritten when the artifact starts again | Planned: executions (a run per start) as a tab on the artifact; ADR-013 §4 |
| Pushed `fix:` history from the bootstrap phase | Kept as is; no history rewrite on `main` |

**Trade-offs to revisit:**

| Trade-off | Decision | Review Point |
|-----------|----------|--------------|
| SQLite vs. PostgreSQL | SQLite for simplicity | WP-06 — evaluate PostgreSQL if write contention emerges |
| Frontend stack | Jinja2 shell + vanilla JS, no HTMX (ADR-010) | Decided in ADR-011 (Pointer Events, client-side rendering); revisit if the board needs virtualisation or many more interactions |
| Docs drifted from reality | ADR-004 described a stack that was never built; corrected 2026-11-20 | Verify arc42/ADRs against code at each WP completion |
| No auth in foundation | Defer authentication | WP-06 — implement JWT auth for multi-user |
| No background task queue | Asyncio tasks only | WP-03 — evaluate Celery/arq for workflow scale |

---

*This chapter follows the arc42 template. TBD fields are limited to risks introduced in later Work Packages.*
