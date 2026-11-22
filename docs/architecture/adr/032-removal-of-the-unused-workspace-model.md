# ADR-032: Removal of the unused workspace model (Project/WorkItem) and repositories

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-018](018-typed-runs-one-error-one-persistence-rule.md) §3.1, [ADR-019](019-module-boundaries-and-single-sources.md) §4  
**Amended by:** —  
**Implemented in:** migration 0026 (drops the tables `work_items` and `projects`); removal of `repositories/`, the `Project`, `WorkItem` and `WorkItemStatus` models, `BOARD_STATUSES`, `PipelineError` and `DatabaseError`  
**Affected chapters:** [05.01](../arc42/05-building-block-view/05.01-domain-model.md), [05.03](../arc42/05-building-block-view/05.03-backend-components.md), [08.02](../arc42/08-cross-cutting-concepts/08.02-error-handling.md)

## 1. Title

The first iteration's project workspace was never used; it is removed instead of kept.

## 2. Context

The bootstrap created tables and models for projects and work items, with repositories for them. The product went
another way: artifacts are `tasks`, with pipelines and executions around them. No production code used the old
model; only `repositories/` and tests did. ADR-019 §4 put it in quarantine (ADR-014 §3.6) until it could be
removed together with its migration and tests. `PipelineError` and `DatabaseError` were in the same state: defined,
never raised.

## 3. Decision

The quarantined code is removed: the `Project` and `WorkItem` models with `WorkItemStatus`, the `repositories/`
package and its tests, `BOARD_STATUSES`, `PipelineError` and `DatabaseError` (with the handler that only it
could trigger). Migration 0026 drops the tables `work_items` and `projects`. The persistence convention is the
one of `tasks/repository.py` and `graph/repository.py`. The vocabulary rule of ADR-015 is unaffected.

## 4. Consequences

- The domain model has no unused entities; the models match the migrations (ADR-018 §3.4) without carrying
  tables nothing reads.
- A raw database error still ends in the generic `500` handler (ADR-018 §3.1).
- The old ADR texts that mention `work_items`, `Project` or `WorkItem` (ADR-001 to ADR-010) stay as history.
- A workspace or project concept, should it come back, is designed anew.
