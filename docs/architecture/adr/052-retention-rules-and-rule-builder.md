# ADR-052: Retention rules for executions, and a rule builder that other lists can use

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amended by:** [ADR-060](060-guards.md) (one rule system)  
**Amends:** [ADR-039](039-edit-fields-switch-rules-and-run-limits.md) (settings storage is reused), the history retention of the execution history guide  
**Implemented in:** `engine/retention.py`, `engine/history.py` (`apply_rules`), `engine/runner.py` (the two call sites), `api/settings.py` (`/settings/retention`, `/settings/retention/preview`, also under `/api/v1`), `api/executions.py` (`POST /api/executions/delete`); `static/js/components/rule-model.js`, `rule-builder.js`, `selection.js`, `bulk-bar.js`, `static/js/executions/retention-dialog.js`, `css/rule-builder.css`  
**Affected chapters:** guide [execution history](../../guides/execution-history.md), [API reference](../../guides/api-reference.md)

## 1. Context

Executions were kept per artifact (*keep the last N*, *keep for N hours*) and could be deleted one at a time. The owner
wanted to say, for all artifacts together, which executions to keep (n8n's model: deleted is deleted, no archive), and
to select several rows and delete them at once.

## 2. Decision

- **A rule is when / then:** the settings hold a list of rules, each with a condition tree (`when`) and an `action`. The
  only action is `delete` (`ACTIONS` in `engine/retention.py` is where another, such as archive or notify, would be added
  with a branch where the rules are applied). The UI is a list of rules (`RuleList`) that opens one rule in a `RuleEditor` (a rule builder and a choice of action).
  Rules stored as one tree before this are read as one rule that deletes.
- **The condition tree** is a tree of groups (*all* / *any*) holding conditions and inner groups. A condition tests `status` (done,
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

## Update 2026-11-24: one rule system (ADR-060)

The rules are now the rule system of the application (`rules/`): a rule is a trigger, a condition tree and a
consequence. The tree models and their bounds are `rules/tree.py`, which also evaluates a tree in memory over a mapping
of facts (the guards use it); the fields, operators and checks of the retention rules are the `retention` schema of
`rules/catalog.py` (their wording, their stored format and this ADR's behaviour are unchanged, the existing tests prove
it) and `GET /api/rules/schemas` hands every schema to the rule builder. This module keeps the SQL compiler; a test shows
that both evaluators agree on the same trees. The rule builder takes a field's `units` (seconds for guards), `number`
values and result fields (`var.NAME`). Lane rules are the documented, planned `lane` schema.

## Update 2026-11-24: a name and a switch for each rule

The dialog is a small management in front of the rule builder. A rule has an optional `name` (at most 80 characters, blank
is none) and a switch `enabled` (default on); a rule stored before them reads as unnamed and on, so nothing changes for
existing rules. **A rule that is off stays stored and is never applied**: not when an execution starts or finishes, not
when the rules are saved, and the preview counts nothing for it. Its structure is still validated, so a half-finished
rule cannot be saved. The dialog opens on the **list**: one row per rule with its switch, its name (or *Rule N*) and one
line about what it does; a click opens the rule in the same frame (the rule builder as before, with a name field and the
switch), *Done*, the back button and Escape return to the list (Escape closes the dialog only from the list). Taking a
rule out marks the row ("Will be removed when you save", with Undo) until *Save*; *Cancel* drops all changes. The footer
line and the *Save and delete N* count cover the rules that are on. The list is a component of its own
(`components/rule-list.js`, data in `rule-list-model.js`; the one-rule editor is `rule-editor.js`, which replaced
`rule-set.js`) so that other rule sets (guards, the planned lane rules) can use the same front door.
