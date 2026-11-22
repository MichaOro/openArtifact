# ADR-028: Global executions page and keyset paging

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-025](025-execution-history-and-retention.md)  
**Amended by:** —  
**Implemented in:** migration 0025 (indexes `ix_executions_started_at`, `ix_executions_status_started_at`); `engine/history_query.py`, `api/executions.py`, `/api/v1/executions`, MCP `list_all_executions`, page `/executions` (`static/js/executions/`)  
**Affected chapters:** [05.05](../arc42/05-building-block-view/05.05-interfaces.md), [05.04](../arc42/05-building-block-view/05.04-frontend-components.md); guides [execution history](../../guides/execution-history.md), [API reference](../../guides/api-reference.md)

## 1. Title

One list of all executions, paged by a keyset cursor.

## 2. Context

The history per artifact (ADR-025) does not show failures across artifacts. An offset page of a growing,
changing table repeats or skips rows.

## 3. Decision

- `GET /api/executions` (also `/api/v1/executions` and the MCP tool `list_all_executions`) lists executions newest
  first with filters (`status`, `started_by`, `pipeline`, `q`, `since`, `until`), combined with AND, a summary and
  a total.
- Paging uses a keyset cursor over `(started_at, id)`. Migration 0025 adds indexes on `(started_at, id)` and
  `(status, started_at, id)`.
- The page `/executions` shows list, filters and summary and follows live updates; it links to the board with
  `/?artifact=N` and to the flow page (ADR-027).

## 4. Consequences

- Pages are stable while executions are added or pruned, and each costs the same.
- Filters by pipeline, origin and text are not indexed; `q` is a substring match. The retention policy keeps the
  table small enough.
