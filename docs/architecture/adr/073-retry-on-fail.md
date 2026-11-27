# ADR-073: Retry on fail

**Status:** Accepted  
**Date:** 2026-11-26  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-061](061-what-a-failure-does.md) (a failure comes after the last try), [ADR-053](053-canonical-node-configuration.md) and [ADR-054](054-node-kinds-as-yaml-manifests.md) (a shared optional setting with a setting type of its own: `retry`)  
**Implemented in:** `engine/retry.py`, `engine/runner.py` (`_run_definition`, `_run_actions`), `graph/node_types.py` (`retry_error`, the bounds), `graph/nodes/_shared.yaml` (`retry`), `models/runs.py` (`attempts`), migration `0059`, `static/js/editor/setting-controls.js` (`RetryControl`), `static/js/tasks/history-step.js`, `tests/test_retry.py`, `tests/e2e/test_retry_setting.py`, `tests/e2e/test_retry_run.py`  
**Affected chapters:** guides [execution-nodes](../../guides/execution-nodes.md#retry-on-fail), [api-reference](../../guides/api-reference.md)

## 1. Context

A node that fails once on a flaky network or a busy database ends the action, and the run. The owner wants what n8n offers: *Retry on
fail* with *Max. tries* and *Wait between tries*, on every node that runs something, read or write, and on an action in a pipeline
(an action can fail, a stage does not).

## 2. Decision

- **One optional setting, once, in the shared snippets** (`_shared.yaml`, `use: retry`): level *optional*, section *behaviour*, type
  `retry`, stored in `config.retry` as `{"enabled", "max_tries", "wait_ms"}`. Not set means no retry (the default is `null`, so a node
  that never asked for it is not retried). *Off* keeps the numbers; the bin takes the setting away.
- **Which kinds:** Code, HTTP, Agent, Postgres, SQLite, GitHub, Artifact and the Action node (the kinds with *If the node fails*, minus
  Edit Fields). Not the Timer, Trigger, Output, stages, nor If, Switch and Edit Fields: they only look at the context, so a second try
  gives the same answer.
- **Bounds, checked on save in plain words (`retry_error`, `422`):** *Max. tries* 2 to 10 (the first try counts), *Wait between tries* 0 to
  10 minutes (default 1 sec), all the waits of one node together at most 30 minutes. They keep a node from holding a run for hours.
- **Engine:** `tried()` runs the node until it passes or the tries are used up, waiting with `asyncio.sleep`: the loop is not blocked and
  a Stop (the task is cancelled) ends the wait at once. A cancellation is never caught, so neither a user's Stop nor a guard that stops
  the node is retried. A node's own timeout is a failed try like any other. Only the node is run again, not the run; after the last
  failed try the node leaves as before (On Fail, or as *If the node fails* says; *Continue* comes after the last try). A node whose
  executor chooses its port itself (Timer, If, Switch) is never retried.
- **An action is run again as a whole** (its definition from the trigger, each run with its steps in the history); after the last try
  it fails with "(after N tries)".
- **How a try is recorded:** one step per node, not one per try, so the flow, the step limit and the guards' counters keep counting
  nodes. The step has `attempts` (column `run_node_results.attempts`, migration `0059`, 1 for every older step) and the failed tries
  before the last in `detail.tries` (`{try, reason, duration_ms}`, read with the single step). The result contract carries `attempts` and
  `duration_ms` (ADR-072); `v_guard_steps` has `attempts`.
- **The Agent node's own retry** for the model request (ADR-037) is unchanged and independent.
- **The setting row** is the shared one of ADR-074: switch on the line of the label, the bin at the end, *Max. tries* and the wait (a
  number with a unit) below while it is on; an added setting starts On with the defaults and is stored at once.

## 3. Consequences

- Retrying a write can repeat it. The setting is off until it is added and its help says so; idempotency is the author's business.
- While a node waits, the flow shows it as still running; the tries appear when the step is written. A wait of minutes is a
  long-running node as far as the run's time limit and the guards are concerned.
- A list of tries per step is the cheapest honest record; nothing else in the engine had to learn about retries.
