# ADR-060: Guards: scoped, event or interval driven specialised actions

**Status:** Accepted  
**Date:** 2026-11-24  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-052](052-retention-rules-and-rule-builder.md) (one rule system), [ADR-058](058-activity-log-of-artifacts.md) (the `guard` entry), [ADR-039](039-edit-fields-switch-rules-and-run-limits.md) (limits of a run)  
**Implemented in:** `rules/tree.py`, `rules/catalog.py`, `api/rules.py`; `guards/schemas.py`, `guards/monitor.py`, `guards/service.py`, `api/guards.py`, `api/mcp.py`; `engine/runner.py` (the monitor in the walk, `_GuardHooks`, `heartbeat`, `preview_guard`), `engine/snapshot.py` (`freeze_guards`), `engine/flow.py`; `models/guards.py`, migrations `0046` and `0047` (the library, §4); `static/js/guards/` (`model.js`, `editor-window.js`, `guard-popover.js`, `library-page.js`), `templates/guards.html`, `templates/components/guard_modal.html`, `static/js/editor/guards.js`, `components/rule-model.js`, `components/rule-builder.js`, `tasks/activity-model.js`, `execution/flow-page.js`  
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
shield chips (pipeline: tool bar; stage: its header; action: its settings; since §4: one shield per scope and its popup), never as canvas nodes, and opens the Guard
window from them or from the *Guard* entries (the "+" menu, the "+" of a stage, the menu of an action node). The window
has a live preview: how many running scopes the condition holds for now, with their facts.

## 3. Consequences

- A guard on a hot loop costs one evaluation per event and one small `UPDATE` of `guard_state` per change; an interval
  guard one task per active scope.
- An event guard with `run_action` blocks the flow for as long as its action runs (bounded by the timeout).
- ~~Guard templates (Stall, Runtime, Health) ship as JSON in `guards/templates/`~~ **Removed (2026-11-27), see the last addendum.**
- `notify` and `handover` wait for cards #93 and #95.

## 4. Addendum 2026-11-24: the guard library (definitions and attachments)

### 4.1 Context

A guard was one row per guard *and* place (`guards`, 0046): the same Stall guard on five actions was five copies, a
change had to be made five times, and the editor showed a chip per guard and place. The owner wanted guards to work like
actions: defined once in a library and reused.

### 4.2 Decision

- **Definition** (`guard_definitions`): what a guard is: name (required, not unique, 120 characters), description, the
  scope types it may be attached to (`scope_types`), trigger, condition, escalation, consequence, fallback and its own
  action (`action_id`, an ordinary action definition). It has **no on/off**. A change acts on every place it is attached
  to, at the next start of a run (`used_by` says how many; the editor says "a change affects all of them").
- **Attachment** (`guard_attachments`): a definition on a scope of a pipeline (`pipeline_id`, `scope_type`, `scope_id`)
  and whether it is switched on there. It goes with its pipeline (`ON DELETE CASCADE`) and with its stage or action
  (the graph repository deletes the attachments of a node it deletes, a stage's with its actions'). Attaching a
  definition to a kind of scope it may not watch is refused (422), so is narrowing `scope_types` below where it is
  attached; attaching it twice to one scope is refused (409). A definition cannot be deleted while it is attached
  (409, "detach it first").
- **The engine reads definitions through attachments.** `freeze_guards` joins the switched-on attachments of the
  pipeline (and the pipelines it calls) with their definitions; each frozen guard keeps the shape it had: `id` is the
  attachment's (the counters, the cap and the live on/off check are per place), `guard_id` the definition's,
  `definition_id` its own action. A running execution therefore keeps the definition and the attachments it started
  with; switching an attachment off still acts at once. The monitor did not change.
- **API**: `/api/guards` (and `/api/v1/guards`) are the definitions (list with `used_by` and `attachments`, create,
  from a template, change, delete); `/api/guard-attachments` (and `/api/v1/...`) attach, switch and detach. The old
  routes that created a guard *on* a scope and switched a guard (`PUT /api/guards/{id}/enabled`) were replaced, not
  kept: keeping them would have meant a second way to make a definition per place, the very duplication this removes.
  MCP: `list_guards` returns the definitions with their attachments; `set_guard_enabled` switches an attachment (its
  id, or the guard's name when it is attached in one place, optionally narrowed by `pipeline`).
- **UI**: a *Guards* page under *Pipeline*, next to *Actions* (the library: search, New blank or from a template,
  "Used in N places", Delete refused with the reason while used); the guard editor titled "Guard – NAME" with the name
  renamed in place (ADR-059 addendum 2026-11-24), the parts *Settings* and *Logic* (its action: choose, New, Edit);
  in the pipeline editor the *Guard* entries open "Add a guard" (attach from the library or make a new one) and every
  scope with attachments shows **one shield** (tooltip "N guards configured", never "active") whose popup lists the
  attached guards by name with their switch and Detach. (Templates existed here until 2026-11-27: *New guard* now makes a blank definition, see the last addendum.)

### 4.3 Migration 0047

Every row of `guards` becomes one definition and one attachment, **both with the guard's id** (two tables, so the
same id names both), with the same settings and the same on/off state: a run started after the migration freezes the
same guards with the same ids, so counters and activity entries line up. A guard whose stage or action no longer
existed watched nothing; it becomes a definition without an attachment (nothing written is lost, and the library could
not have detached it). Plain `CREATE TABLE`, `INSERT … SELECT`, `DROP TABLE`. The downgrade rebuilds `guards` from the
attachments joined with their definitions (one row per attachment; a definition without attachments has no place
there).

### 4.4 Not in this step (extension points)

- ~~**Guards on single nodes inside an action**~~: built, see §5.
- **"Applies to" rules and kinds** (attach to every action of a kind): an attachment that names a rule instead of one
  scope; `freeze_guards` is the one place that resolves attachments.
- **Parameters / overrides per attachment** (e.g. another interval on one action): columns or a JSON column on
  `guard_attachments`, merged over the definition in `guard_data`.
- **Runtime colours of the shield** in the execution flow view and its overlay, and **a check before starting a run**
  (which guards will watch): read `snapshot.guards` and `guard_state`.

## 5. Addendum 2026-11-24: guards on an action definition and on its nodes (migration 0049)

The owner wanted a stall guard on an Agent node, and a guard for "this action wherever it is used", not only for the
action card of one stage. Two scopes are added, held by an **action definition** instead of a pipeline:

| Scope | Holder (`graph_id`) | `scope_id` | Meaning |
|-------|---------------------|------------|---------|
| `definition` | the action definition | its own id | the whole action, in every stage of every pipeline that uses it |
| `node` | the action definition | a node of it | one execution node of the action, whose kind says `guardable: true` |

- **The holder is any graph.** `guard_attachments.pipeline_id` is renamed `graph_id` (a plain `RENAME COLUMN`, same
  foreign key and cascade; the index is renamed too; no table is rebuilt, see 0043). The API still takes and shows
  `pipeline_id` (equal to `graph_id` for the three pipeline scopes, `null` for the two new ones), and adds `holder_kind`
  (`pipeline` or `action`), `holder_name` and `scope_name`. A pipeline holds `pipeline`, `stage` and `action`; an action
  definition holds `definition` and `node` (422 otherwise, 409 for a duplicate as before). An attachment goes with its
  graph and with its node (the repository's node delete already removed a node's attachments).
- **`guardable` is a manifest flag** (ADR-054): the kinds that run as a step in an action: Code, HTTP, Timer, If, Switch,
  Agent, Edit Fields, Postgres, GitHub, Artifact. Not the trigger, the output, a stage, an action node, a pipeline node or
  a tool node (a tool is used by an agent, it does not run as a step of its own). `GET /api/node-types` carries it.
- **"Can watch" no longer restricts.** The migration widens every definition that could watch pipeline, stage and action
  to `definition` and `node` as well; a definition that was narrowed (the Health template: stage only) is left alone; a
  new definition may watch all five; the Stall and Runtime templates list all five.
- **Freezing across action definitions.** `freeze_guards` takes the switched-on attachments of the pipeline, of the
  pipelines it calls **and of every action definition the run uses** (the snapshot's `definitions`, resolved at the
  start). A guard attached to a definition after the start does not reach the run, as for any other guard.
- **Counters per use.** A scope of an action definition is keyed by the path of pipeline nodes **and the action node that
  runs it** (`<path>><action node>|node:<id>`): the same definition in two stages counts apart, and a node inside a loop
  counts a new entry each time the flow reaches it (`runs`). Facts are the same as for every scope (runs, elapsed, idle,
  errors, passes, last status, `guard.runs`, result fields).
- **Events.** `definition` behaves like an action: entered when the action starts, `pass` / `error` when it ends, left
  after. `node`: entered before the node runs, `pass` / `error` after it (an error counts whatever *If the node fails*
  does with it, see ADR-061), left after; an **interval** watch runs while the node runs and may stop it through the
  existing stop mechanism (the process group of a Code node is killed), so a Stall guard on an Agent node interrupts it.
  A guard's own action is not watched (no guards on guards) and does not count as steps of the run.
- **Firings** say where: "fired at node 'Summarise' of action 'Analyze epic gaps'" (`scope_label` in the English note of
  a paused or aborted run; the History and the flow view build the sentence from `scope_type`, `scope_name` and
  `scope_parent` in the reader's language).
- **Mirroring in the pipeline.** The card of an action in a pipeline shows its shield when the card has attachments of
  its own **or** its definition has guards (on the definition or on a node); the tooltip counts both. The popup lists the
  card's own guards first (switch, Detach) and under *In the action* the inner ones by name with what they watch (no
  switch and no Detach: they belong to the action), and a link that opens the action. `GET /api/guards` carries every
  attachment, so the editor needs no extra request; `?pipeline_id=…&inner=true` (guards and attachments) is the same
  view for an integration.
- **The popup's two layouts** (UI catalog): the buttons *Attach guard* and *New guard* stack when the popup opens from a
  stage header or a card, which it would cover side by side; from the canvas "+", its shield and the settings they sit
  side by side.
- **Copies carry no attachments.** There is no copy path for a graph; duplicating or pasting nodes in the editor makes
  new nodes, which have no guards. A guard is attached to what it watches, not to its copy.

Not in this step: "applies to" rules and kinds, parameters per attachment, runtime colours of the shield in the flow view,
the check before a start (§4.4).


## Addendum (2026-11-25): facts about agents and the board, templates for the health of an agent

- **New facts** in the guard schema: `agent.turns`, `agent.tool_calls`, `agent.tool_errors`, `agent.repeat` (the same tool with the
  **same arguments** in a row), `agent.same_tool` (the same tool in a row, whatever the arguments), `agent.tokens`, `agent.idle`,
  `agent.since_tool_call`, and `lane.NAME` (artifacts in a lane). The difference between `agent.repeat` and `agent.same_tool` is the point:
  ten calls of an HTTP tool to ten different websites are work, ten calls for the same README are a storm.
- **Where they come from.** The agent loop tells the application what happens (`agent.turn`, `agent.tool_call`, with `args_key`, a hash of the
  arguments); `app.py` passes each event to the event bus and to `Telemetry` (`engine/telemetry.py`), which keeps in memory, per execution,
  what a guard needs. The guards read it through `TelemetrySource`, so the event log written during the run (card #100) can replace it
  without a change in the guards. The monitor takes the facts from a callable (`agent`) and looks up the lanes (`board`, an async
  callable) only when a condition names one.
- **In the guard's action** the facts are variables (`guard_agent_idle`, `guard_lane_backlog`: the dot becomes an underscore), and
  `guard_execution` and `guard_task` name what it is about, so the SQLite node (ADR-068) can read the execution through the views.
- **Templates:** *Agent quiet and storm guard* (rules only) and *Agent health guard* (rules, then a guard action: SQLite node, agent, code
  node). *Healthy* stays the author's definition (rules, code, an agent, or a combination).
- **Not built:** a persisted history of the agent facts (the event log, #100), the consequences "Hint to the agent" and "Wrap up now",
  and the facts in the preview of a guard for lanes (the preview is synchronous and shows the others).

## Addendum (2026-11-25): the shield in the read-only flow of an execution

- The flow page of an execution (Open flow) draws the **shield** of the editor (`components/guard-shield.js`, one component for both: a button
  in the editor, a plain icon with `readOnly` in the flow) on every stage, action or node a guard watches, in the same place as in the editor
  and without its "+" or menu. The guards are those of the frozen run (the snapshot's switched-on attachments, `ExecutionFlow.attached_guards`,
  each with whether it is still switched on now, because the engine checks that live).
- **Active** means: the execution is running, the guards' bookkeeping says the place is being watched right now (the scope is active) and at
  least one guard attached there is still switched on. Active is **green and pulsing** (the pulse follows `prefers-reduced-motion`); every other
  case is **grey**: all guards switched off, the place not running (yet, or any more), the run over. The state is decided without a DOM
  (`execution/flow-guards.js`). The tooltip says "2 guards, 1 active", names the guards and the ones that fired in this run.
- A guard that was not switched on at the start is not in the frozen run and leaves no shield.

## Addendum (2026-11-26): draft and published versions

A definition has a draft and published versions ([ADR-081](081-guard-versions.md)): the sentence above that a change to a definition acts on every place it is attached
to is now true of a **publication**, not of a save. A save changes the draft; only the published version applies, and an execution freezes it when it starts.
A new definition watches nothing until it is published. Switching an attachment on or off is not part of a version and still acts on running executions at once.

## Addendum (2026-11-27): the shipped templates are removed

The templates (Stall, Runtime, Health guard, and Agent quiet and storm / Agent health) were files shipped with the application
(`guards/templates/*.json`) and read by `GET /api/guards/templates` and `POST /api/guards/from-template`. The user could neither define nor
change them, and their content was fixed, so they promised more than they gave. **Templates removed (2026-11-27): they could not be defined or
changed by the user and shipped fixed content; a guard is made blank.**

- *New guard* on the Guards page is a plain button that opens the editor with a blank definition (its name is typed first); nothing is stored until
  it is saved. The two routes (REST and `/api/v1`), the template files, the builder of a template's action and the menu are gone.
- **Guards made from a template earlier stay as they are:** they are ordinary definitions in the library (no field of a definition points to a
  template), with their versions and attachments.
- The conditions the templates held are plain definitions and can be written in the editor or posted to `POST /api/guards` (see the examples in
  the guide). A user-defined template (a definition saved as a starting point) may come with the JSON import layer; it is not built.

