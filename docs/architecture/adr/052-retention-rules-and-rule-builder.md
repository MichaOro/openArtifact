# ADR-052: Retention rules for executions, and a rule builder that other lists can use

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-039](039-run-limits.md) (settings storage is reused), the history retention of the execution history guide  
**Implemented in:** `engine/retention.py`, `engine/history.py` (`apply_rules`), `engine/runner.py` (the two call sites), `api/settings.py` (`/settings/retention`, `/settings/retention/preview`, also under `/api/v1`), `api/executions.py` (`POST /api/executions/delete`); `static/js/components/rule-model.js`, `rule-builder.js`, `selection.js`, `bulk-bar.js`, `static/js/executions/retention-dialog.js`, `css/rule-builder.css`  
**Affected chapters:** guide [execution history](../../guides/execution-history.md), [API reference](../../guides/api-reference.md)

## 1. Context

Executions were kept per artifact (*keep the last N*, *keep for N hours*) and could be deleted one at a time. The owner
wanted to say, for all artifacts together, which executions to keep (n8n's model: deleted is deleted, no archive), and
to select several rows and delete them at once.

## 2. Decision

- **Rules are a tree** of groups (*all* / *any*) holding conditions and inner groups. A condition tests `status` (done,
  failed, stopped), `started_by`, `pipeline` (is / is not / contains, ignoring case) or `age` (older than N seconds, from
  the start) or `position` (beyond the newest N executions of the same artifact, which is *keep the last N*). The tree is compiled to one SQL condition (`engine/retention.py`); text is bound, `%` and `_` in a pipeline
  name are text. At most 4 levels and 50 conditions. One row of `app_settings` (`history.rules`, JSON): no migration.
- **A match is deleted for good** with its steps. A running execution is never deleted (and cannot be named by a rule).
  An empty rule deletes nothing; an empty inner group is ignored.
- **Push driven, no timer:** the rules are applied when an execution is added, when one finishes, and when the rules are
  saved. Saving says first (a live preview, `POST .../preview`) how many executions it deletes now.
- **The rules can say what the per-artifact policy says:** *keep the last N* is `position` beyond N (counted per
  artifact), *keep for N hours* is `age`. The per-artifact policy (its fields, its dialog, `execution_history_default_keep`)
  still exists next to the rules; replacing it needs an *artifact* field for rules (to say it for one artifact) and a
  migration of the stored policies, and is left for a later step.
- **Reusable UI:** `RuleBuilder` + `rule-model.js` take a *schema* (fields, operators, how a value is entered) and know
  nothing about executions, so lane rules (hide after N days, colour by time in the lane) can use them with another
  schema. `Selection` and `BulkBar` are the same for any list with a bulk action; `input.check` is the one checkbox look.
- **Several at once:** `POST /api/executions/delete` takes up to 500 ids of any artifacts and reports `deleted` and
  `skipped_running`; the page batches *select all N* over the filters.

## 3. Consequences

A rule that is too wide deletes quickly and irreversibly, which is why saving shows the count and the button says
*Save and delete N*. Every start and every finish runs one extra indexed query when rules exist.
