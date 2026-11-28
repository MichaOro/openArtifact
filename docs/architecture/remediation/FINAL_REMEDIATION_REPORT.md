# Final remediation report

| | |
|---|---|
| Date | 2026-11-27 / 28 |
| Basis | `ARCHITECTURE_AUDIT.md` (AUD), `ARCHITECTURE_AUDIT_REVIEW.md` (REV), `ARCHITECTURE_REMEDIATION_MANDATE.md` — local files of the owner at the repository root, kept out of git by the owner (the two audits through `.git/info/exclude`; the mandate untracked and left as it was found) |
| Start | branch `feat/core-pipeline-functions`, commit `a2f2d72`, clean apart from the untracked mandate |
| Result | local branch `chore/architecture-remediation`: the remediation commits on `a2f2d72`, final code at `b760e38`, these records after it; pushed with the owner's OK and opened as **PR #9 into `main`** (CI green, §5); merging is the owner's (§7) |
| Records | [FINDING_REGISTER.md](FINDING_REGISTER.md) (78 findings, M01–M22, R1–R11) · [REMEDIATION_PLAN.md](REMEDIATION_PLAN.md) · [WORK_PACKAGE_TRACKER.md](WORK_PACKAGE_TRACKER.md) (WP-01 – WP-13) |

## 1. What the original audit identified

A modular monolith in good health (strict typing, clean lint, 95 % coverage gate, arc42 + 92 ADRs, fitness tests) with one confirmed
defect (server events the browser never receives) and 22 measures, most of them structural: splitting `RunEngine`, `ArtifactService`
and `GraphRepository`, sub-packages for `engine/`, a `references.py` against a 12-module import cycle, the board tools out of `api/`,
a popup controller, a date formatter, ESLint, a lock file, design-token scales.

## 2. What the independent review corrected or added

It reproduced the measurements and rejected the step from size to defect: the "bottleneck" claim is false (45 of 229 `feat`
commits), M05 would not break the cycle, M06 would not remove the late-binding lambda, M11 mostly exists, the date "defect" is the
documented ADR-056 decision. It corrected the event defect and added `storage.cleaned`, an 8-module SCC, the unenforced
single-process invariant, a stale extension guide and the missing look at run-time behaviour, with a lost-update hypothesis.

This remediation **revalidated both on `a2f2d72`** (own import graph, own ESLint run, own publish/handler scan) and found, beyond
both documents: a fifth undelivered event (`credentials.changed`); README / arc42 contradictions (credentials page, lane reordering,
tool counts, in eleven places); the colour guard's blind spot for `#fff`; a node kind without executor being passed silently; the
image migrating outside the new lock (F-63); the read-only lock file defeating `flock` on NFS (F-67); and — through the full browser
suite — **a confirmed lost update** when two settings of a node are saved at once (F-76, REV's hypothesis made concrete), an
announcement race on the executions page (F-77) and an isolation gap of the e2e fixture (F-75).

## 3. What was implemented

| WP | Findings | Change | Commits |
|---|---|---|---|
| WP-01 | F-01–F-03, F-06 | The four missing names in `EVENT_TYPES`; one board load per operation; the open archive coalesces a burst; `tests/test_event_contract.py` (handled ⊆ listened ⊆ published ⊆ listened ∪ `SERVER_ONLY`); e2e for the archive after a sweep; event docs | `edb5bdd`, `1637e2a`, `37c897b` |
| WP-02 | F-04–F-08, F-48, F-61, F-64 | README, arc42 ch. 1, 3, 4.3, 5.3, 8.1, 8.6, 9, extending guide, API reference, credentials and CI/CD guides, ADR index, a stale comment — each checked against the code | `0addb97`, `2db2046` |
| WP-03 | F-09, F-63, F-67, F-73 | `openartifact/process_lock.py`: exclusive non-blocking `flock` on `<data_dir>/openartifact.lock` before recovery, held for the app's life, released in `finally`, read-write for NFS, warning where locks are unsupported; the image's migrations run under the same lock; ADR-094, arc42 ch. 7 / 11, operations guide | `c14522a`, `b2addad`, `8ae96ae`, `a5151f2` |
| WP-04 | F-33 (a–c), F-37 | "since/until" through i18n; the one date deviating from ADR-056 aligned; one shared date helper; ESLint dead code removed | `cefd230`, `c78770a`, `b6ff3cb`, `333d4cf` |
| WP-05 | F-10–F-13, F-57 | `board_tool_names` from `api/` to `agents/`; `tests/test_import_structure.py` (no module-level cycle; `api`/`web` imported only by themselves and `app.py`) | `4d0f134`, `b287197`, `1297b0c` |
| WP-06 | F-25, F-27 | Failing secret store logged; `Limits.board` without `Any`; keyword call | `bcc0b24` |
| WP-07 | F-38, F-71 | `uv.lock` installed by CI (`--frozen`, checked current) and by the image (hashed export); base images by digest; Dependabot `uv`; audit of the locked set | `6e819f4`, `289d1e3`, `a5151f2` |
| WP-08 | F-40, F-41, F-59 | Colour literals to tokens; the colour guard sees every hex form | `d79c060` |
| WP-09 | F-45, F-46, F-58 | Every `NodeKind` passes the DB constraint; every kind on a definition's path has an executor | `dfd162d` |
| closing | F-67–F-74 | Fixes from the independent closing review (§6) | `a5151f2` |
| WP-10 | F-75 | The e2e reset deletes agents, as its docstring says | `8ecee52` |
| WP-11 | F-76, F-53 | Changes to the nodes of one graph run one after the other (in-process lock, sufficient under ADR-094); test reproduced the loss in 25 of 25 rounds before the fix | `0099a11` |
| WP-12 | F-77 | A deletion arriving as an event no longer overwrites the page's announcement | `6b62d20` |
| WP-13 | F-78 | A tool-connection e2e test waits for the server's delete | `b760e38` |

Every worker result was reviewed as a diff and re-verified on the integration branch, never accepted on the worker's word. Six
worker results needed a correction (tracker): a JS test the worker did not run, the migration outside the lock, idiomatic code
rewritten for a linter default, a test pinning line numbers, stale statements left in six further documents, and a wrong claim about
a conflicting owner commit (F-62, refuted). The worker worktrees were removed after a patch-id check that every commit is integrated.

## 4. What was deliberately rejected or deferred, and why

| Measure / finding | Decision | Reason |
|---|---|---|
| M15, M16, M17 | Rejected | No defect, no change-frequency evidence; `RunEngine`'s atomicity depends on the order of `await`s; the move would break path references across 95 ADRs and the guides |
| M05 | Rejected as designed | Verified that it would not break the cycle (`RunView`); the import test guards the real risk |
| M09, M10 | Rejected | No behaviour gain; transaction rule documented; residuals done (WP-06) |
| M03, M13, M18, M19, M20 | Deferred | Duplication or naming without a shown defect; the owner does not want unasked UI refactor passes |
| M02 (ESLint gate in CI) | Deferred — the owner decided on 2026-11-28 to do it later | Needs the repository's first Node dev dependency; the code is clean (2 intentional findings) |
| M12/M22 scales, M21 Swagger, F-49, F-50, F-60, F-66 | Deferred | Bounded impact; each a small separate decision |
| F-53 beyond graph nodes | Deferred | The node inspector is the place where several controls write one row at once (fixed); other services were not audited one by one |
| F-78 (two of three flaky e2e tests) | Deferred | Load-only, no proven cause; the same class occurs on the untouched baseline; see §5 |

Each of the 78 findings and all 22 measures has one decision with its reason in the register.

## 5. Evidence

| Check | Result |
|---|---|
| `ruff check .`, `ruff format --check .` | clean, 479 files (final tree) |
| `mypy .` (strict) | 0 errors in 479 files |
| `coverage run -m pytest` (the CI command, serial) at `0099a11` | **2 718 passed**, 0 failed, 58 min; **coverage 95.38 %** (gate 95 %). The two later commits change only JS and one e2e test; the Python tests that read JS (`test_event_contract.py`, `test_web.py`) were re-run on them: 48 passed |
| `pytest -m e2e -n 4` on the final code `b760e38` | **806 passed, 0 failed** |
| Earlier e2e runs and their outcome | at `a5151f2` 804 / 806 → F-75, F-76 found and fixed; at `0099a11` 805 / 806 → F-77 fixed; at `6b62d20` two runs with 1 and 2 load-only failures → F-78 |
| Baseline `a2f2d72`, same `pytest -m e2e -n 4`, three runs | 1, 1 and 2 failures: the F-75 test each time, and once `test_window_areas…` (never touched here) — the load-only failures predate the remediation |
| `node --test 'tests/js/*.test.mjs'` | 677 / 677 |
| `node --check` over `static/js` | 0 errors |
| ESLint `recommended` (+ `ignoreRestSiblings`) | 21 → 2, both intentional |
| `check_i18n`, `check_links`, `check_quarantine` | 1 836 / 1 836; 0 broken links; ok |
| Import graph | no module-level cycle; 0 edges into `api`/`web` from outside |
| `uv lock --check` (uv 0.13.9) | passes; `setup-uv@v10.4.0` and uv 0.13.9 confirmed on GitHub |
| Image on `b760e38` (own tag, removed afterwards) | builds; `tools/smoke_container.sh` passed |
| Lock in containers on `b760e38` | A healthy; B on the same volume exits 3 at the migration step, A unaffected (also checked earlier: after A stops, C starts) |
| Planted violations | event contract, import rule, node kinds, colour guard, mock warning, lock mode, concurrent node saves: each failed for its named reason before the fix |
| Live deployment | `deploy-openartifact-1` never rebuilt, restarted or retagged; healthy throughout |
| **GitHub Actions, PR #9 into `main`** (head `651d9f6`, the final code plus these records) | all 8 checks passed: Ruff (incl. `uv lock --check`, `uv sync --frozen`), mypy strict, JavaScript syntax + Markdown links, pip-audit of the locked set, **pytest with a real Postgres: 2 718 passed, coverage 95 %** (46 min), **browser tests serial: 806 / 806** (25 min), Docker build + smoke test, Docker build (PR preview) — the first remote run of the uv-based workflows |

## 6. Final independent review

A fresh reviewer read the whole diff without the coordinator's conclusions. Of nine points, five led to changes (F-67 NFS lock mode,
F-68–F-71, F-73), two were intentional and recorded (F-74), one does not apply in the container (F-72). It confirmed lock lifetime
and ordering, exit statuses, the entrypoint under `set -e`, the Docker hardening, every CI job, the event fix, the import and
node-kind tests, the dead-code removals, and that no secret is exposed. The later fixes (WP-10 – WP-13) were reviewed by the
coordinator against the same criteria and verified by the full suites above.

## 7. Left to the owner

- **Pushing and remote CI: done** with the owner's OK on 2026-11-28 (PR #9 into `main`, which also carries the commits of
  `feat/core-pipeline-functions` not yet on `main`); all checks passed (§5).
- **Merging PR #9** is the owner's.
- **The ESLint gate** (M02): decided by the owner on 2026-11-28 — later, as a separate step (the code is clean, so it starts at zero).

## 8. Remaining risks

- The lock covers the application and the image's migrations; `alembic` run by hand does not take it; a file system without lock
  support only warns.
- The build backend of the image (hatchling) is unpinned (F-60); the shipped dependencies are locked with hashes.
- Two e2e tests can fail under heavy parallel load (F-78); CI runs serially.
- Other read-merge-write paths were not audited one by one (F-53).
- The deferred structural items carry no known defect.

## 9. Does the result meet the mission?

Yes. Every confirmed defect — the original one and the seven found on the way, including a real loss of user input — is fixed and
guarded by a test that failed for its reason before the fix. The invariant the deployment relies on is enforced end to end and
verified with real containers; builds install a hashed lock; the documentation that serves as instructions matches the code; and the
architecture keeps its shape: no new layer, no framework, no class split for its size. What was not done is recorded with its
reason, and what only the owner can do is named in §7.
