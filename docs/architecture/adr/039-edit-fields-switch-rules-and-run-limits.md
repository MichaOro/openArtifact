# ADR-039: Edit Fields node, a rule per Switch case, run limits as settings

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-013](013-execution-engine-and-runs.md) §4, [ADR-033](033-run-context.md), [ADR-034](034-branching-nodes-and-reference-suggestions.md)  
**Amended by:** —  
**Implemented in:** migration 0034 (kind `set`, table `app_settings`); `engine/fields.py`, `engine/branching.py`
(`evaluate_switch`), `engine/limits.py`, `engine/runner.py` (`_Walk.limits`, the time limit in `_execute`), `engine/flow.py`
(`MAX_ACTIONS`), `graph/node_types.py` (`SetType`, `switch_case_used`, the case settings), `graph/repository.py`,
`api/settings.py`, `models/settings.py`; `static/js/editor/node-types.js` (`SetView`, `switchCaseUsed`),
`reference-completion.js`, `static/js/settings/run-limits-page.js`  
**Affected chapters:** [04](../arc42/04-solution-strategy.md), [05.03](../arc42/05-building-block-view/05.03-backend-components.md), [11](../arc42/11-risks-and-technical-debt.md); guides [execution nodes](../../guides/execution-nodes.md), [API reference](../../guides/api-reference.md), [configuration](../../guides/configuration.md)

## 1. Title

Variables without code, a Switch whose cases are rules, and the limits of an execution as settings users change.

## 2. Context

Only a Code node could set a variable, so preparing values for a branch or an agent meant writing a script. The Switch
compared one value for equality only; routing by "greater than 90" or "contains urgent" needed a chain of If nodes. The
step limit of a run (1000) was a constant, a time limit did not exist, and ADR-013 §4 had promised both on a settings
area that now exists (*Settings*, ADR-037).

## 3. Decision

- **Edit Fields (`set`).** An execution node of action definitions (On Pass / On Fail, `on_failure`). `fields`: one
  `name = value` per line (at most 100), names as variables (`[a-z][a-z0-9_]{0,63}`); values are filled from the run
  context in one pass like an HTTP body (ADR-033); `${secret:...}` is refused when saved and never replaced: a variable
  is plain data. `value_types`: `text` (default) or `detect` (a JSON number, boolean, null, object or list is stored as
  that; a quoted JSON string stays as written). The variables pass the run context's checks (`check_vars`) and are
  set only when the node passes. Output: the fields as compact JSON; data: their names. The editor suggests them as
  `${var.name}`.
- **A rule per Switch case.** Every case has `case_operator_N` (the If node's operators, default `equals`) and its value
  (`case_N`, references allowed, secrets refused), compared with the node's value by the If node's `compare`. A case is
  in use when it has a value or an operator that needs none (`switch_case_used`, mirrored in the editor): only a case in
  use has an output. The first case that holds wins; a case that cannot be resolved or compared sends the node to Else
  with outcome `fail`. The step's data gains `cases` (what was checked). Existing Switches have no operator and behave as
  before. Sending to several matching outputs (n8n's "all matching") is not built: the engine follows one port.
- **Run limits.** `app_settings` holds settings changed at run time (key, JSON value); no row means the default.
  `run.max_steps` (10 to 100000, default 1000) and `run.time_limit_minutes` (0 to 10080, default 0 = none). An execution
  reads them when it starts and keeps them in its snapshot (`snapshot["limits"]`); snapshots of before have none and get
  the defaults. The step limit counts actions and the nodes of their definitions as before; the time limit cancels the
  walk like a stop (the running node is ended) and fails the execution with the reason. `GET`/`PUT
  /api/settings/run-limits` and the same under `/api/v1`; event `settings.changed`; page *Settings > Run limits*. The
  number of runs at the same time stays an operator setting (`OPENARTIFACT_MAX_CONCURRENT_RUNS`), shown read-only.
- The flow replay's bound is now the highest step limit (`MAX_STEPS_MAX`): one constant instead of a copy of the
  engine's.

## 4. Consequences

- Preparing values for If, Switch, HTTP and Agent nodes needs no code; a variable can carry a number or an object.
- A changed limit applies to the next executions only, like a published agent.
- The time limit ends a long node from the outside; the nodes' own limits (Code, HTTP, Agent) stay in force.
- Not built: tool calling and tool nodes for agents (ADR-037 follow-up, waiting for the owner's decision on what the
  agent may do on GitHub), Switch "all matching outputs", per-pipeline limits.
