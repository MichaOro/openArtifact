# ADR-060: Guards: scoped, event or interval driven specialised actions

**Status:** Accepted  
**Date:** 2026-11-24  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-052](052-retention-rules-and-rule-builder.md) (one rule system), [ADR-058](058-activity-log-of-artifacts.md) (the `guard` entry), [ADR-039](039-edit-fields-switch-rules-and-run-limits.md) (limits of a run)  
**Implemented in:** `rules/tree.py`, `rules/catalog.py`, `api/rules.py`; `guards/schemas.py`, `guards/monitor.py`, `guards/service.py`, `guards/templates/*.json`, `api/guards.py`, `api/mcp.py`; `engine/runner.py` (the monitor in the walk, `_GuardHooks`, `heartbeat`, `preview_guard`), `engine/snapshot.py` (`freeze_guards`), `engine/flow.py`; `models/guards.py`, migration `0046`; `static/js/editor/guards.js`, `components/rule-model.js`, `components/rule-builder.js`, `tasks/activity-model.js`, `execution/flow-page.js`  
**Affected chapters:** guide [Guards](../../guides/guards.md), [API reference](../../guides/api-reference.md), [integration](../../guides/integration.md), [execution history](../../guides/execution-history.md), [configuration](../../guides/configuration.md); arc42 5.3, 5.6

## 1. Context

Pipelines loop (a stage whose actions lead back to its entry action), agents can work for a long time, and a Code node
can hang. The owner wanted something that *watches* a part of the process and steps in: stop a run that makes no
progress, abort one that runs too long, and every few rounds of a loop ask an agent whether more rounds are still worth
it. That is business logic like an action's, but it is not part of the process flow: it is triggered by what happens to
a scope, or by time.

## 2. Decision

### 2.1 Vocabulary

- An **action** holds execution logic and runs in the flow; a **stage** holds actions and the flow between them (no
  logic of its own); a **pipeline** holds stages (and called pipelines). A **gate** is an action's On Pass / On Error.
- A **guard** is a specialised action that is *not* triggered by the flow but by an **event** of its scope or by an
  **interval**, and is attached to a pipeline, a stage or an action. Only the coupling differs from an action: its own
  logic is an ordinary action definition, edited in the action editor.
- A guard watches only while its scope is active. There is no global idle timer.

### 2.2 Entry and counters

- Every scope has an **entry**: the moment before its first execution. A pipeline: after its trigger (trigger nodes are
  excluded); a stage: before its entry action starts, and *again* every time a loop brings the flow back to the entry
  action; an action: before it runs.
- Per scope instance and per run the engine counts `runs` (entries), `passes`, `errors` (an action in it left by On Pass
  / On Error; a pipeline and a stage count what their actions did), the last action's status and when the scope was
  entered. Per guard on that scope it counts `guard.runs` (times it fired) and when and at which round it fired last.
- Counters are **per run** (a called pipeline per call: its scopes are keyed by the path of pipeline nodes leading to
  it) and **never reset** within the run, so escalation steps can build on them.
- **Persistence:** the counters, the last heartbeat and the firings (each with its facts) are one JSON column,
  `executions.guard_state` (migration 0046), written when they change. A column rather than a table: they belong to one
  execution, are read with it (the flow view) and go with it (retention, delete) without a join or a second cascade; a
  JSON column on the existing row is a plain `ADD COLUMN`. Not the run context: that is what nodes read and its size is
  bounded for them.
- **After a restart** no run is running (`RunEngine.recover` stops them, ADR-021): there is no watch to rebuild. The
  counters of the interrupted execution stay in its row; a new start is a new run with new counters.

### 2.3 Triggers

- **Event** (`enter`, `pass`, `error`, `leave`, `fail`): evaluated in the flow, which **waits** for the verdict. `fail`
  is told to the guards of every active scope (innermost first) when the run fails; the run fails whatever they say.
- **Interval** (`every_seconds`, `for_seconds`, `cooldown_seconds`): a watch (an `asyncio` task) is registered when the
  scope is entered and cancelled when it is left. The running action keeps running while the guard checks; a firing
  that pauses or aborts **interrupts** it through the existing stop mechanism (the job is cancelled, a Code node's
  process group is killed). The interval is at least `OPENARTIFACT_GUARD_MIN_INTERVAL_SECONDS` (default 30 s): shorter
  is refused with 422. Intervals only, no cron.
- `for` and `cooldown` come from alerting systems (Prometheus alerting rules' `for`, Alertmanager's repeat interval,
  Kubernetes probes' period and failure threshold): a condition must have held at every check for `for_seconds` before
  the guard fires (no firing on one unlucky sample), and after firing it is quiet for `cooldown_seconds`.

### 2.4 Condition: one rule system

ADR-052's rules (a condition tree with all/any groups) became the rule system of the application (`rules/`): a rule is
a trigger, a condition tree and a consequence. The tree format is one; there are two evaluators, the SQL compiler of the
retention rules (`engine/retention.py`) and an in-memory evaluator over a mapping of facts (`rules/tree.py`), and a test
proves they agree on the same trees. The fields are **schemas per purpose** (`rules/catalog.py`, `GET
/api/rules/schemas`): `retention` (unchanged fields, checks and stored format), `guard` and the planned `lane` (documented,
not used). The guard schema's facts: `runs`, `elapsed` (seconds in the scope), `idle` (seconds since the last progress),
`errors`, `passes`, `guard.runs`, `last_status`, `cost` (only when a node reports one; none does yet) and result fields
`var.NAME` (numeric run variables, e.g. a Code node's declared `gain`). A missing fact makes every condition on it false.

**Escalation:** a table of steps "from the guard's k-th firing on, every N rounds (or every N seconds)". The step that
applies to the next firing is the last whose `from_firing` it has reached; it fires when the distance from its last
firing (rounds or seconds; before the first firing: from the entry) reaches the step's interval. Example: `[{1, every 5
rounds}, {2, every 3 rounds}]` with `runs ≥ 1` fires at round 5, 8, 11, …

### 2.5 Consequences

One registry (`CONSEQUENCES` in `guards/monitor.py`, declared with labels and availability in `rules/catalog.py`, like
`ACTIONS` of the retention rules):

- `pause`: the run ends **stopped** with the reason as its note (`Paused by guard …`); the card shows it; resuming is
  starting it again (a new run). No human-input check yet. A run status `paused` was not added: `stopped` already means
  "stays where it is and can be started again", and a new status would touch every list, filter and rule.
- `abort`: the run **fails** with the reason (`Aborted by guard …`); a running action is stopped.
- `continue`: only recorded.
- `run_action`: the guard's own action runs as a **child** of the run, with a copy of the run context whose variables
  hold the facts (`guard_runs`, `guard_idle`, `guard_elapsed`, `guard_errors`, `guard_passes`, `guard_last_status`,
  `guard_firing`, `guard_name`); its On Pass continues, its On Error does the guard's `fallback` (pause, abort or
  continue). Its steps are not steps of the execution and not progress, what it does to the copy is not kept, and it is
  never watched by a guard.
- `notify` (MVP 25, card #93) and `handover` (MVP 27, card #95) are declared `available: false`: shown disabled with what
  they need, refused with 422, and a stored one never stops a run. They plug in at the registry.

### 2.6 Progress and heartbeat

The stall clock (`idle`) starts again with every step the engine records (a node's result, an agent node, a tool call
inside an agent counts when its node ends) and with a **heartbeat**: `POST /api/v1/executions/{id}/heartbeat` (optional
`note`, 200 characters; token-authenticated like `/api/v1`; at most one per `OPENARTIFACT_HEARTBEAT_MIN_SPACING_SECONDS`,
else 429) and the MCP tool `heartbeat`. The last heartbeat and a count are kept in `guard_state`, not in the activity.
A change in the workspace is not a signal: the runners do not expose one cheaply.

### 2.7 Safety

- No guards on guards (`scope_type: guard` is refused with 422); a guard's own action is not watched and its events do
  not trigger guards (loop detection by construction, plus the cap below and the run's step limit).
- A cap of firings per guard, scope and run (`OPENARTIFACT_GUARD_MAX_FIRINGS`, default 20): the next firing is skipped
  and the cap is recorded once.
- **Fail open:** a guard that raises or does not answer within `OPENARTIFACT_GUARD_TIMEOUT_SECONDS` (default 600) is
  recorded as failed and the flow goes on.
- Switching a guard off acts on running executions at once (checked when it would fire); the other settings of a guard
  are frozen with the run's snapshot (`snapshot.guards`, its own actions in `snapshot.guard_definitions`, apart from the
  run's definitions so their node names never clash with references).

### 2.8 Visibility

Every firing is an activity entry of the artifact (ADR-058): kind `guard`, actor `system` with the guard's name, the
execution, and `data` with the scope, trigger, event, consequence, outcome (`continue`, `pause`, `abort`, `failed`,
`capped`, `unavailable`) and the **facts snapshot** ("round 10, 14 min without progress"). The History timeline shows it
with a shield marker under *Executions*; the flow view lists the firings of the execution. The editor shows guards as
shield chips (pipeline: tool bar; stage: its header; action: its settings), never as canvas nodes, and opens the Guard
window from them or from the *Guard* entries (the "+" menu, the "+" of a stage, the menu of an action node). The window
has a live preview: how many running scopes the condition holds for now, with their facts.

## 3. Consequences

- A guard on a hot loop costs one evaluation per event and one small `UPDATE` of `guard_state` per change; an interval
  guard one task per active scope.
- An event guard with `run_action` blocks the flow for as long as its action runs (bounded by the timeout).
- Guard templates (Stall, Runtime, Health) ship as JSON in `guards/templates/` and are created through `POST
  /api/guards/from-template`; the global JSON import layer (cards MUST 31-33) does not exist yet and can take them over.
- `notify` and `handover` wait for cards #93 and #95.
