# ADR-057: The per-artifact history policy is removed

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-025](025-execution-history-and-retention.md) (retention is no longer per artifact), [ADR-052](052-retention-rules-and-rule-builder.md) (the rules are now the only user-facing retention)  
**Implemented in:** migration 0043 (drops `tasks.history_keep_last`, `tasks.history_keep_hours`); `engine/history.py` (`prune` is the operator's guard only; `policy_of` gone), `engine/schemas.py` (`HistoryPolicy*` gone, `ExecutionList` has no `policy`), `tasks/service.py`, `api/tasks.py`, `api/v1.py` (the `history-policy` routes gone); `templates/components/history_panel.html`, `static/js/tasks/history-tab.js`, `history-api.js` (`retention-editor.js` removed); tests `tests/test_history.py`, `tests/test_migrations.py`, `tests/e2e/test_history.py`  
**Affected chapters:** guides [execution history](../../guides/execution-history.md), [API reference](../../guides/api-reference.md), [integration](../../guides/integration.md), [configuration](../../guides/configuration.md), [operations](../../guides/operations.md); arc42 [05.01](../arc42/05-building-block-view/05.01-domain-model.md), [05.05](../arc42/05-building-block-view/05.05-interfaces.md), [05.06](../arc42/05-building-block-view/05.06-execution-engine-internals.md), [06.09](../arc42/06-runtime-view/06.09-history-retention-and-flow.md), [08.07](../arc42/08-cross-cutting-concepts/08.07-history-and-retention.md)

## 1. Context

Two ways to say what to keep existed side by side: the artifact's own policy (ADR-025: keep the newest N and/or for H
hours, set in a "Keep history" panel of the History tab or with `PUT .../history-policy`) and the global retention rules
(ADR-052), which can say the same (*Position beyond N*, *Age older than H hours*) and much more. Two places for one
decision confused which one applied, and the per-artifact panel took room in a tab that is about executions. The owner
decided that the rules replace the policy.

## 2. Decision

- **Removed:** the "Keep history" panel and its JavaScript, the routes `PUT /api/tasks/{id}/history-policy` and
  `PUT /api/v1/artifacts/{ref}/history-policy`, the `policy` object of the executions listings and the schemas
  `HistoryPolicy`, `HistoryPolicyWrite`, `HistoryPolicyResult`, the columns `tasks.history_keep_last` and
  `tasks.history_keep_hours` (plain `ALTER TABLE ... DROP COLUMN`; a batch rebuild would lose the collations and was not
  needed). There was no MCP tool for it.
- **Kept:** *Clear finished* (a different function: it deletes now, by hand); the global rules and their application
  at start, end and save (ADR-052); and **the operator's guard** `OPENARTIFACT_EXECUTION_HISTORY_DEFAULT_KEEP` (default
  50, `0` = unlimited): at most that many executions per artifact, applied at the start and the end of an execution, as a
  protection against unbounded growth. It is an operator setting; the UI no longer shows it as a per-artifact default.
  The newest and running executions are still never removed by retention.
- **Stored policies are discarded.** Before the migration the running installation had none set (0 of 86 artifacts); the
  downgrade re-adds the two columns empty.

## 3. Consequences

- Positive: one place decides what is kept; a smaller History tab and API; one rule builder to learn.
- Negative: retention cannot differ per artifact any more (rules apply to all alike, with conditions on status, pipeline,
  origin, age and position). A client that called the removed route gets `404`; `GET .../executions` no longer returns
  `policy`.
- Neutral: the guard still bounds growth when no rule is defined.
