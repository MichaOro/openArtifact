# 11. Risks and Technical Debt

## 11.1 Current Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| 1 | SQLite write contention under heavy concurrent pipeline execution | Low | Medium | WAL mode, short writes, the run cap (`OPENARTIFACT_MAX_CONCURRENT_RUNS`); SQLite is kept for good (ADR-020), so the limit is real: heavy external data goes through a future connector layer, not into the application's database |
| 2 | Hand-written vanilla JS becomes unstructured as interactions grow | Medium | Medium | ES modules per feature, one state owner per concern, browser tests; reconsider a framework only if needed (ADR-010) |
| 3 | **Single-process invariant.** The event bus, the run engine (its in-process claim, the active run tasks), the run cap and the stream cap live in the memory of one process. A second process or container on the same volume sees none of them: SSE clients miss each other's events, the caps do not add up, a stop reaches only the process that runs the task, and run recovery at start would mark the other process's running runs `stopped` (the conditional `UPDATE` and the unique run row still refuse a double start) | Low (one container is the supported setup) | High | One `uvicorn` process, one container per volume (documented in the [operations guide](../../guides/operations.md)); scale-out would need a shared broker behind `EventBus` and run ownership in the database (ADR-011, ADR-018) |
| 4 | GIL limiting concurrent Python execution for CPU-bound tasks | Low | Low | Async-first architecture; no CPU-bound work exists yet |
| 5 | SQLite backup during active writes | Medium | Medium | The documented backup uses SQLite's backup API; restore steps are written ([operations guide](../../guides/operations.md)); backups are manual, nothing schedules them |
| 6 | Secret exposure via logs | Medium | High | A logging filter masks the configured token and secret key and values after secret-looking names; it works on text, so a secret in an unusual format is not caught (chapter 8.3). No test can prove the absence of all leaks |
| 7 | **No rate limiting.** Only a half-second delay on a wrong sign-in; a reachable instance can be brute-forced or flooded within the body, run and stream caps | Medium (if exposed) | Medium | A 32-character minimum token; local-only publishing by default; add rate limiting at the reverse proxy; planned in the application |
| 8 | **No wall-clock deadline for runs.** Only the 1000-step limit and a timer's one-day bound end a run; a long timer or a loop of timers holds a run slot for hours | Medium | Low | The run cap (8) bounds the number; *Stop* works; planned with the settings area (ADR-013) |
| 9 | One shared token, no revocation of a single session | Medium | Medium | Rotate the token or the secret key (ends all sessions); separate tokens and scopes are planned (ADR-016) |
| 10 | Pre-release schema: migrations rename tables and cannot be downgraded for data | Medium | Medium | Back up before every upgrade; migrations run forward on start |

## 11.2 Technical Debt

No intentional technical debt has been introduced beyond the items below, which are known and deliberate.

| Item | State |
|------|-------|
| **Accessibility / keyboard use of the graph editor.** Connections between nodes can only be made by dragging; the routing select that was the keyboard path was removed (ADR-014). Other parts of the editor are only partly operable by keyboard and screen reader | Known limitation; the board has keyboard alternatives. Planned as a whole (board card OPT 12) |
| `#12` references are resolved at display time | Not validated on save (a body may contain `#5` as plain text); no back-references yet |
| Parent picker without search | Becomes necessary with many artifacts |
| `Project` / `WorkItem` models and `repositories/`, `BOARD_STATUSES`, `PipelineError`, `DatabaseError` are unused | Quarantined in `quarantine.json`; removal needs a migration that drops `work_items` and `projects` and takes their tests with it |
| Pipeline editor: stages only grow, no undo, no live sync between tabs, edges routed only for loops | See ADR-012 §2.4 |
| Runs can loop until the step limit (1000), an On Error routed back to its own action included | Planned: a *Settings* area with a global loop protection and a wall-clock deadline (ADR-013 §4) |
| One run per artifact: an earlier run is overwritten when the artifact starts again | Planned: executions (a run per start) as a tab on the artifact (ADR-013 §4) |
| Access is one shared token; no scopes, no per-client tokens, no audit log beyond `created_by` / `started_by` | Planned with the settings area (ADR-016 §3.5) |
| `style-src` allows `'unsafe-inline'` (inline `style` attributes) | Tighten when the UI no longer sets them |
| `release.yml` does not compare the tag with `version.py`; Python dependencies are not locked | Open (CI/CD guide) |
| Pushed `fix:` history from the bootstrap phase | Kept as is; no history rewrite on `main` |

**Trade-offs that stand:**

| Trade-off | Decision | Review Point |
|-----------|----------|--------------|
| SQLite vs. PostgreSQL | SQLite for good (ADR-020); PostgreSQL only as a data source behind a connector layer (board card OPT 11) | When the connector layer is designed |
| Frontend stack | Jinja2 shell + vanilla JS, no HTMX (ADR-010, ADR-011) | If the board needs virtualisation or many more interactions |
| Authentication | One token (ADR-016) instead of accounts | When more than one team shares an instance |
| No background task queue | `asyncio` tasks in the process (ADR-013) | If runs must survive a restart or run on other machines |
| Docs vs. code | Verify arc42 and ADRs against the code at each larger change; the ADR history is kept and corrected through dated Update sections | Every change |
