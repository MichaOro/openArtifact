# ADR-025: Execution history and retention

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-013](013-execution-engine-and-runs.md) §3, §4  
**Amended by:** [ADR-027](027-execution-flow-by-replay-over-the-frozen-snapshot.md), [ADR-028](028-global-executions-page-and-keyset-paging.md), [ADR-033](033-run-context.md)  
**Implemented in:** migration 0023 (table `executions`, `run_node_results.execution_id`, `pipeline_runs.execution_id`, `tasks.history_keep_last`, `history_keep_hours`, `execution_seq`); `engine/history.py`, `engine/schemas.py`, `api/tasks.py`, `static/js/tasks/history-*.js`  
**Affected chapters:** [05.01](../arc42/05-building-block-view/05.01-domain-model.md), [06.09](../arc42/06-runtime-view/06.09-history-retention-and-flow.md), [08.07](../arc42/08-cross-cutting-concepts/08.07-history-and-retention.md); guide [execution history](../../guides/execution-history.md)

## 1. Title

Every start of an artifact leaves an execution that can be read later, and old ones are pruned by a policy.

## 2. Context

ADR-013 kept one run row per artifact: starting again overwrote it, and nothing remained of an earlier run.
With Code and HTTP nodes (ADR-021) there is output worth keeping and failures worth finding.

## 3. Decision

- `pipeline_runs` stays the current state of an artifact's processing. `executions` has one row per start with a
  number per artifact (`tasks.execution_seq`), copies of the pipeline, stage and action names (they survive
  renaming and deletion), the origin (ADR-026), status, note, step count and the frozen snapshot. Steps
  (`run_node_results`) belong to the execution.
- The engine opens the execution in the transaction that claims the run and closes it when the run stops, fails or
  ends. `execution.updated` and `execution.deleted` are published after the commit.
- **Retention** is per artifact: `history_keep_last` (1 to 1000) and `history_keep_hours` (1 to 8760); an execution
  is kept only if it satisfies every limit that is set. With neither set, `OPENARTIFACT_EXECUTION_HISTORY_DEFAULT_KEEP`
  (default 50, `0` unlimited) acts as `keep_last`. A running execution is never deleted but counts toward
  `keep_last`; the newest is never deleted by retention. Pruning runs when an execution is opened, when it closes and when the policy
  changes. Executions can also be deleted by hand, one or all.
- Migration 0023 turns every existing run into execution number 1; where it started is unknown for those.

## 4. Consequences

- The database grows with snapshots and outputs, bounded by the policy; deleted rows give their pages back to the
  file system because the database runs with `auto_vacuum = FULL` (ADR-005, update of 2026-11-22).
- Deleting an artifact deletes its executions (cascade).
- A policy change applies at once, which can delete executions the previous policy kept.
