# ADR-018: Typed runs, one refusal error, one persistence rule

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-013](013-execution-engine-and-runs.md)  
**Amended by:** —

## 1. Title

One way to describe a run, one way to refuse a request, one way to open and commit a database session.

## 2. Context

The browser API, the integration API and MCP all go through `ArtifactService` and the `RunEngine`
(ADR-016). Each layer had grown its own habits: the runs were plain dictionaries with an inconsistent
timestamp format, the services and routes translated errors per route, a separate `RunError` existed next to
`HTTPException`, a request session was committed automatically while services opened their own, and the
start of a run was a check followed by writes that two concurrent calls could both pass.

## 3. Decision

### 3.1 One refusal: `ArtifactError`

`ArtifactError(OpenArtifactError)` carries an HTTP `status` and a `message` (`exceptions.py`). The services and the
engine raise it; one application-level handler answers `{"detail": message}` with that status. Routes do not
translate errors, there is no `RunError`, and MCP turns the same error into the tool's error text. Other errors:
a bare `OpenArtifactError` is answered `400` and logged as a warning, `ConfigurationError` `503`, request
validation `422` (without echoing the input), and everything else `500` with a generic body (the message only
in debug mode) and one ERROR log line naming exception class, method and path. `PipelineError` and
`DatabaseError` exist but nothing raises them; they are quarantined (`quarantine.json`). A raw database error
therefore ends in the `500` handler, not in a `503`.

### 3.2 Typed runs

A run is `RunRead` with `RunStageRead` (`engine/schemas.py`). `/api/runs`, `POST /api/tasks/{id}/run[/stop]`,
`/api/v1/artifacts/{ref}/run` and the `run.updated` event return the same schema, and OpenAPI shows it. Same fields
as before; `updated_at` is always ISO-8601 UTC with a `Z` suffix, like the artifact timestamps
(`schemas_common.py`).

### 3.3 One persistence rule

One engine and one session maker per process (`database.py`). Services and the engine open sessions through
`database.new_session()`; the request dependency `get_db_session` (`SessionDep`, `api/deps.py`) yields a session
that is **not** committed automatically: whoever changes data commits, and a session closed without a commit
discards its changes. `build_engine` creates the shared engine; `create_engine_for(settings, pragmas=...)` is shared
with `alembic/env.py` (the migrations switch the pragmas off because table rebuilds rely on foreign keys being
off). The test helper `db_session_context` lives in the tests only.

### 3.4 Models match migrations

The SQLAlchemy models declare every index and constraint the migrations create, plus a `TaskNumberSeq` model for
`task_number_seq`, and `tests/test_migrations.py` runs `alembic check`, which fails on drift. Database-level server
defaults are deliberately not compared (the ORM uses Python-side defaults).

### 3.5 Atomic start

`RunEngine` claims an artifact in process before the first `await`, changes the artifact with a conditional `UPDATE`
and inserts the run with `INSERT ... ON CONFLICT DO NOTHING` on `pipeline_runs.task_id`. A lost race is `409`,
a stop during a start is `409`, and more than `OPENARTIFACT_MAX_CONCURRENT_RUNS` active runs is `429`.

## 4. Consequences

- A rule about refusing a request is written once, in the service, and is the same for browser, API and agents.
- A new service method commits explicitly; forgetting it loses the change instead of half-saving it.
- The in-process claim is not shared between processes; the database guards still refuse a double start, but caps and event delivery assume one process (arc42 chapter 11).
- Anything that wants a `503` for database failures needs a handler that is not built.
