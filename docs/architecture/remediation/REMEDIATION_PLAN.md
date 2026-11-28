# Remediation plan

Basis: [FINDING_REGISTER.md](FINDING_REGISTER.md). Tracking: [WORK_PACKAGE_TRACKER.md](WORK_PACKAGE_TRACKER.md).

## 1. Target state

- The architecture stays a **modular monolith** with one composition root (`app.py`), one process, SQLite, vanilla ES modules
  without a build. Neither source document names a requirement against it, and the import graph confirms the packages are sound
  (acyclic at import time, two misplaced edges).
- **Contracts that cross a boundary are checked by a test**, not by a guide step: the event names between server and browser
  (WP-01), the import direction into `api/`/`web/` and the absence of import-time cycles (WP-05), node kinds against the database
  constraint and the executor registry (WP-09), colour tokens (WP-08).
- **Invariants the deployment relies on are enforced**, not only documented: one process per data directory (WP-03).
- **Builds are reproducible** in development, CI and the image from one lock file (WP-07).
- **Documentation that serves as instructions is true** (WP-02 and the docs part of every WP).
- **No refactoring for size or metrics.** The large classes (`RunEngine`, `ArtifactService`, `GraphRepository`, `editor.js`) stay;
  their decisions are in the register (F-18 – F-21, F-30).

## 2. Baseline (2026-11-27, commit `a2f2d72`, before any change)

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check .` | clean |
| Format | `ruff format --check .` | 473 files formatted |
| Types | `mypy .` (strict) | 0 errors in 473 files |
| JS unit tests | `node --test 'tests/js/*.test.mjs'` | 676 / 676 pass, 2.4 s |
| i18n | `python tools/check_i18n.py` | 1 833 / 1 833 keys |
| Markdown links | `python tools/check_links.py` | 162 files, 0 broken |
| Quarantine | `python tools/check_quarantine.py` | ok (4 entries, day 2–4 of 14; an earlier note said 2 because the output was cut) |
| ESLint `recommended` (outside the repo) | see register §1 | 21 findings |
| Python suite | `pytest -n auto` | **partial**: stopped at about 74 % on the owner's instruction (full runs only at closure); no failure, error or skip up to that point. Not a pass claim |
| Coverage, e2e | – | **not run** at baseline (owner rule: full and browser runs at closure) |

## 3. Rules for every work package

- Smallest change that satisfies the acceptance criteria; public interfaces unchanged unless the WP says so.
- **Tests (owner instruction 2026-11-27):** run only the individual tests a change makes relevant; the full suite and coverage run
  once at closure. **Existing tests are not changed** unless the source or the documentation proves the test wrong, and the
  evidence is stated in the report. New tests assert their reason (`match=` on expected errors) and must fail without the fix.
- UI changes follow `docs/guides/ui-catalog.md` (binding rules) and i18n in `en` and `de`.
- Nothing about unreleased product ideas goes into docs, code, tests or commit messages.
- Workers work in their own git worktree and commit there; the coordinator reviews the diff and integrates by cherry-pick onto the
  local branch `chore/architecture-remediation` (from `a2f2d72`). Nothing is pushed.
- The live container on this host is not touched (no rebuild or restart of it); a test image gets its own tag.

## 4. Work packages and order

| WP | Findings | Objective | Size | Depends on | Round |
|---|---|---|---|---|---|
| WP-01 | F-01, F-02, F-03, F-06 (events) | Deliver the four missing events, avoid double loads, three-way contract test, event docs | S | – | 1 |
| WP-03 | F-09 | Exclusive non-blocking lock on the data directory before recovery; ADR, arc42, operations guide | S–M | – | 1 |
| WP-05 | F-10–F-13, F-57 | Move `board_tool_names` out of `api/`; import-structure test (no module-level cycle; api/web imported only from the composition root and themselves) | S | – | 1 |
| WP-07 | F-38 | `uv.lock`; CI and Dockerfile install from it; base image by digest; Dependabot ecosystem; docs | M | – | 1 |
| WP-06 | F-25, F-27 | `Limits.board` without `Any`; keyword call in `app.py`; warning in `api/graphs.py` | XS | – | 1 (coordinator) |
| WP-02 | F-04–F-08, F-48 | README, arc42 §4.3, extending guide (node kinds), API reference, status-popup comment, testing guide | S | WP-01, WP-07 (README, extending guide) | 2 |
| WP-04 | F-33 (a–c), F-37 | i18n for since/until, ADR-056 alignment, one date helper, ESLint dead code | S | WP-01 (`archive-view.js`) | 2 |
| WP-08 | F-40, F-41 | Token for `#fff`, `999px` → `--radius-pill` where identical, widen the colour guard | XS–S | – | 2 |
| WP-09 | F-45, F-46 | Constraint test for every `NodeKind`; executor for every executable kind | XS–S | – | 2 |

Parallelism: round 1 runs WP-01, WP-03, WP-05 and WP-07 at the same time; their files do not overlap (WP-03 and WP-06 both touch
`app.py` in different functions and are integrated one after the other). Round 2 starts after round 1 is integrated.

**Adapted on new evidence** (2026-11-28): the full browser suite and the independent closing review found defects outside the
original packages; they were added as WP-10 (F-75, e2e reset), WP-11 (F-76 / F-53, lost update of node settings), WP-12 (F-77,
announcement race) and WP-13 (F-78, a test without a wait), each with its own evidence in the tracker.

## 5. Risks

| Risk | Mitigation |
|---|---|
| WP-03 lock blocks legitimate starts (tests that build several apps on one data directory, CLI tools) | Lock taken in the lifespan only, released in a `finally`; check test fixtures before choosing the scope; the OS drops a `flock` on any exit, so a crash leaves no stale lock; filesystems without lock support log a warning instead of refusing |
| WP-07 changes every CI job and the image | Build the image locally under a separate tag and run the container smoke script; keep `pip` usable for contributors without `uv` |
| WP-01 changes live-update behaviour | Unit test for the coalescing, targeted e2e for the archive after a sweep; full e2e at closure |
| Parallel worktrees diverge | Disjoint file sets; cherry-pick in a fixed order; coordinator resolves conflicts |
| Docs drift again | Contract tests replace guide steps where possible (events, imports, node kinds) |

## 6. Rejected and deferred measures

All in [FINDING_REGISTER.md §3](FINDING_REGISTER.md#3-original-measures-m01m22) with reasons. In short: **rejected** M05 (as designed),
M09, M10, M15, M16, M17 and the C901 gate; **deferred** M02 (CI gate, owner decision), M03, M13, M18, M19 (`run_turns`), M20, the
typography/layer scales of M12/M22, Swagger assets of M21.

## 7. Phase 1 quality gate

| Criterion | Status |
|---|---|
| Both source documents fully read and considered | yes (AUD 718 lines, REV 724 lines, mandate 879 lines) |
| Every relevant finding accounted for | yes: 57 register entries incl. 5 NEW; R1–R11 mapped |
| Conflicts resolved or marked | yes: each AUD/REV conflict decided on current code (F-01, F-10, F-13, F-14, F-18, F-19, F-21, F-25, F-33, F-45) |
| M01–M22 each decided | yes (register §3) |
| No WP based solely on size or complexity | yes: every WP fixes a confirmed defect, a doc contradiction, an unenforced invariant, a reproducibility gap or a hole in an existing rule |
| WPs bounded with acceptance criteria | yes (tracker) |
| Dependencies and risks understood | yes (§4, §5) |
| Working-tree changes protected | yes: only untracked `ARCHITECTURE_REMEDIATION_MANDATE.md` (and the git-excluded audits) existed; none is modified; work happens on a new branch |

**Gate passed on 2026-11-27.** Phase 2 may start.
