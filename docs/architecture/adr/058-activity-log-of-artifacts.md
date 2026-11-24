# ADR-058: The activity of artifacts: what changed, who did it, and what a deleted execution leaves behind

**Status:** Accepted  
**Date:** 2026-11-24  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-025](025-execution-history-and-retention.md) (a deleted execution leaves a trace), [ADR-055](055-comments-on-artifacts.md) (the identity rules are reused for changes)  
**Implemented in:** migration 0044 (`task_activity`, backfilled with one `created` entry per artifact); `openartifact/activity/` (`recorder.py`, `service.py`, `schemas.py`), `models/board.py` (`TaskActivity`), `tasks/service.py` (`create`, `update` record changes under an `actor`), `engine/history.py` (`remove` writes the trace), `api/activity.py`, `api/tasks.py`, `api/v1.py`, `api/mcp.py` (`list_activity`), `api/hardening.py` (pages are revalidated); `static/js/tasks/activity-model.js`, `activity-rows.js`, `activity-api.js`, `history-tab.js`, `templates/components/history_panel.html`; tests `tests/test_activity.py`, `tests/e2e/test_activity.py`, `tests/js/activity-model.test.mjs`  
**Affected chapters:** guides [concepts](../../guides/concepts.md), [execution history](../../guides/execution-history.md), [API reference](../../guides/api-reference.md), [integration](../../guides/integration.md), [operations](../../guides/operations.md); arc42 [05.01](../arc42/05-building-block-view/05.01-domain-model.md), [05.05](../arc42/05-building-block-view/05.05-interfaces.md), [08.07](../arc42/08-cross-cutting-concepts/08.07-history-and-retention.md)

## 1. Context

The History tab showed executions only. What happened to the artifact itself (moved to another lane, renamed, given a
parent, a field changed, a pipeline assigned) was not kept anywhere, so nobody could say afterwards who had done it, and
because executions are deleted by retention, by *Clear finished* and by hand, the record of what ran was just as
perishable. n8n shows both in one place; the owner asked for the same: a history that is more than an execution list,
where a deleted execution still leaves its minimum (time, pipeline, duration, status).

## 2. Decision

- **One table, `task_activity`.** A row is `kind`, the actor (`actor_kind`, `actor_name`, as for comments, ADR-055), an
  optional `execution_id` (no foreign key, the execution may be gone), a small JSON `data` and `created_at`. Rows go with
  their artifact (`ON DELETE CASCADE`). Plain `CREATE TABLE`; no existing table is rebuilt (the collations of other tables
  stay).
- **What is recorded** (one row per real change; the same value again writes nothing, a move inside a lane writes
  nothing): `created` (with the lane), `lane` (the lane *titles* at that time), `title` (from, to; cut to 80
  characters), `description` (that it changed, never the text), `parent` (titles), `field` (name, label, from, to; values cut to
  80 characters), `pipeline`, `stage`, `action` (names), and `run`. Names are copied, not ids, so the entry stays
  readable after a rename or a delete, as for executions (ADR-025).
- **A deleted execution leaves a `run` trace.** Every deletion path ends in `ExecutionHistory.remove` (the delete button,
  *Clear finished*, the bulk delete of the Executions page, the retention rules, the operator's guard), so that is
  where the trace is written, in the same transaction: number, pipeline name, status, start, end, duration and step count; `created_at`
  is the *start* of the execution, so the timeline puts it where the run happened. An execution that still exists
  writes nothing: the timeline shows it from the `executions` table (interactive: it opens the flow, it can be deleted).
  So a run appears once, as a live row or as a trace, never both. (The first design wrote a row when an execution
  finished and de-duplicated; writing at deletion needs no de-duplication and no backfill of executions.)
- **Who.** The service methods take an `actor`; the API layers pass `author_of(channel)` (ADR-055): the browser is `user`
  "You", a managed token its own name, the environment token the channel's name, a trace the way the execution was
  started (`started_by`). No actor given (the engine, tests) is `system`.
- **A cap.** At most 500 entries per artifact; writing one removes the oldest beyond that. Old entries are not a promise.
- **Backfill.** The migration writes one `created` entry per existing artifact at its `created_at` with the creator it
  has on record. Nothing older is known, so nothing is invented (no lane moves).
- **API.** `GET /api/tasks/{ref}/activity` and `GET /api/v1/artifacts/{ref}/activity` (`limit` 1 to 200, default 50;
  `before` is the opaque `next` cursor of the previous page; newest first), the MCP tool `list_activity`, the event
  `activity.created`. Read only. The activity does not repeat executions that still exist (`.../executions` has them).
- **UI.** The History tab is one timeline, newest first: execution rows and change rows by time, with the actor as an avatar
  and name, a filter *All / Executions / Changes*, the count of entries on the tab, and a quiet dashed line (no buttons, no link) for
  a deleted execution. *Clear finished* stays; the traces stay. The tabs are Details, Comments, History.
- **Pages are revalidated.** HTML answers carry `Cache-Control: no-cache` (static files already did): a browser must ask again
  instead of showing the page of the build before, with the markup, language and dictionary of another version.

## 3. Alternatives considered

- *Comments as the one stream* (a system comment for every change): mixes what people said with what the system
  recorded, makes comments editable records of facts, and hides the actor kinds. Kept separate; the owner may still
  want both in one view later (a filter, not a table).
- *Writing the run row at finish and de-duplicating:* more moving parts (a row that must not show while the live row
  exists, a backfill for old executions) for the same result.
- *Event sourcing the whole artifact:* far more than a timeline needs.

## 4. Consequences

- Positive: who changed what is answerable; a run leaves a minimum after retention; the same identity rules everywhere.
- Negative: one more write per change (small, in the same transaction); the cap loses very old entries; nothing before the
  migration is known; an artifact deleted takes its activity with it.
- Neutral: comments are not part of the timeline (their own tab). Not recorded: position within a lane, comments, the
  text of a description, the values of long fields beyond 80 characters.
