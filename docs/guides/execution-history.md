# Execution history

Every time an artifact is started in a pipeline, the application records an **execution** and keeps it, with
its steps and a frozen copy of the pipeline, until retention removes it. This guide explains what is kept,
how long, where you see it and what it costs in database space. The vocabulary (run, execution, step, visit,
flow) is in [Concepts](concepts.md).

## What is recorded

- **One execution per start.** A restart of the same artifact is a new execution. Starting at a later stage
  or action is recorded as such (where it started, where it ended).
- **A number per artifact**, from 1 (`#1`, `#2` ...), never reused, even after executions are deleted. It
  is shown as "Execution #7 of artifact #12".
- **Status:** `running`, then `done`, `failed` or `stopped`. A `failed` execution carries a note that says
  where ("X failed", "X has no On Pass connection", "The pipeline does not come to an end"). `stopped` is a
  user stop, `Interrupted by restart` (when the application restarts, every execution that was still running is closed as
  stopped with that note, because its process is gone) or `EMERGENCY STOP` (the global switch aborted it, see below).
- **Dry runs** carry `dry_run: true` and a chip (*Dry run*, *Testlauf*) in the lists. They are real executions of the history (numbered,
  kept and deleted like the others) that skipped everything that writes, see [execution nodes](execution-nodes.md#dry-run-testlauf).
  The global list filters them with `dry_run=only` or `dry_run=exclude`; the counters *failed* and *done in 24 hours* count real runs only,
  *running* and *total* count all. A skipped step shows the *fast forward* icon (two arrows) with what it would have done as its tooltip, in the step and (drawn like a node that ran,
  not dimmed) on its card in the flow; a node that handed over a mock has no such icon.
- **Observed runs** (ADR-088) are the runs of a pipeline in the observe mode: dry runs that nobody started by hand. They carry `observed: true` beside `dry_run: true`, are counted like dry
  runs and show the flag *Observed* (*Beobachtet*) **instead of** *Dry run*. The global list filters them with `observed=only` or `observed=exclude` (both are dry runs for `dry_run`);
  the *Kind* filter of the executions page offers *Any*, *Real runs*, *Dry runs* (started by hand: the page asks for `dry_run=only&observed=exclude`) and *Observed*. A step an observed
  run could not see (it needs the result of a skipped write) is passed and says *Not observable from here: ...* quietly, and the run's note says *Observed up to ...*.
- **Origin** (`started_by`): `user` (the browser), `api` (the integration API), `mcp` (the MCP server) or
  `system`.
- **The pipeline** by id and by name (a copy: the pipeline may later be renamed or deleted; the history
  survives that), the stage and action it started at and where it ended, the start and end time.
- **Steps**: one per executed node inside an action definition, in order: trigger, timers, Code and HTTP
  nodes, output. See [Execution nodes](execution-nodes.md#results) for the fields. Output per step is kept up to
  256 KiB and per execution up to 1 MiB in total; when the total is exceeded the oldest outputs are replaced by
  a note, the newest stays.
- **The run context** (`context`): the variables and the latest result of each node, kept with the execution and
  updated with every step, so it survives a restart: after a restart the context of the interrupted execution is
  unchanged. It is at most 64 KiB, with each node's output cut to 4 KiB (the step has the whole output). See
  [Execution nodes](execution-nodes.md#the-run-context-and-references). It is deleted with its execution.
- **A snapshot**: the pipeline and every action definition and pipeline it uses, frozen when the execution
  started. The flow view draws from it, so editing or deleting the pipeline later changes nothing about an
  old execution. Secrets are never in it, only the names the nodes refer to.

Executions that existed before the history was introduced were backfilled from the then-current run of each
artifact; for those the starting stage and action are unknown.

## Retention

Retention keeps the history from growing without bound. What to keep is decided by the **retention rules** below
(*Executions → Retention*); an artifact has no policy of its own (ADR-057 removed the per-artifact "Keep history"
panel and its API). Besides the rules there is one guard for the operator:

- **The operator's guard:** `OPENARTIFACT_EXECUTION_HISTORY_DEFAULT_KEEP`, **50**: at most that many executions are
  kept per artifact (`0` means no limit at all). It cannot be changed per artifact; it only keeps an unattended
  installation from growing without bound. The user can set **Executions kept per artifact** in *Settings → Personal →
  Data storage* (ADR-084): when it is set it replaces the operator's number (`0` keeps all). Age never deletes anything by itself.
- **Data storage limits** (the same section): step outputs and details of finished executions older than N days, or beyond a size
  limit for all executions, can be *emptied* (the execution, its steps and their results stay; each emptied step says
  `data.data_pruned`), and the longest output a step stores can be lowered. A **Preview** shows what a pass would do and **Clean now**
  (or the background cleaner on the interval the user set) does exactly that; see [operations](operations.md#database-size-and-history-retention).
- **The newest execution is never removed by retention** and **a running execution is never removed** (it counts toward the
  number kept). You can delete the newest one by hand.
- Retention runs when it has something new to decide: when an execution **starts**, when one **ends**, and when the
  rules are **saved** (then they apply at once). There is no timer: an artifact that is not run any more keeps its
  old executions until the rules are saved or it runs again.
- Deleting an execution deletes its steps and leaves ONE slim entry per delete action in the artifact's activity: who deleted, which numbers and when (the deletion time); nothing else of the run is kept (at most 500 entries per artifact). *Clear finished* of 40 executions is one line. Deleting an artifact deletes all its executions and its activity.

### Retention rules (all artifacts)

*Executions → Retention* is a list of rules, each **if** conditions hold for a finished execution **then** an action (so far only *Delete the execution*; another action such as archiving or sending a mail would be one more entry). A rule is a rule builder: groups that say *all* (AND) or *any* (OR) of their conditions hold, with
inner groups, and conditions on **Status** (done, failed, stopped), **Pipeline** (is, is not, contains), **Started by**
**Age** (older than N minutes, hours or days) and **Position among the artifact's executions** (beyond the newest N: the same as *keep the last N*, counted per artifact). A finished execution that the rule matches is deleted for good with
its steps; a running one never is, and a rule without conditions deletes nothing. The rules are applied whenever an
execution starts or finishes and when you save them; the dialog says first how many executions saving deletes
(*Save and delete N*). *Keep the last N* and *keep for N hours* are rules too (Position beyond N; Age older than N hours); they apply to every artifact alike, not to one. API:
`GET` / `PUT /api/settings/retention` (also under `/api/v1`), `POST .../retention/preview`.

**The list of rules.** The dialog opens on a list: one row per rule with a **switch**, its **name** (or *Rule 2*) and a line
about what it does ("Delete finished executions where Status is Failed."). Switch a rule **off** to keep it without
applying it: it deletes nothing, the preview ignores it, and the line under the list says what the rules that are on do
(or that all are off). A click on a row opens the rule in the same dialog (the title reads *Retention – name*; click the name to rename the rule, empty
means no name; then the rule builder; the switch stays in the list); *Done*, the *Rules* button next to the close
button or Escape return to the list. The bin takes a rule out until you save (*Undo* brings it back).
*Add rule* appends a rule that is on and opens it. In the API a rule is `{"when": {...}, "action": "delete",
"name": "Old ones" | null, "enabled": true}`; `name` is at most 80 characters, and a rule without `name` and `enabled`
(one stored by an earlier version) is unnamed and on.

## Live updates

Changes arrive through the page's one event stream (`GET /api/events`) as

| Event | Payload |
|-------|---------|
| `execution.updated` | `{task_id, execution}`: the execution's summary after it was opened, advanced or closed |
| `execution.deleted` | `{task_id, id}`: after retention, a delete or a clear |

They are published after the database commit. The stream does not replay: a browser that was disconnected
loads the current state again when it reconnects. The step list of a running execution follows the run's
own `run.updated` events.

## The emergency stop

One switch on the Executions page, next to *Retention*, stops all execution at once (ADR-076). It is offered only when you switch on *Show
the emergency stop* in Settings > Personal. **Switching it on** asks first (it says how many executions run and will be aborted), then aborts
every running execution (they end as `stopped` with the note `EMERGENCY STOP`) and **refuses every start** from every source: the browser,
the API, MCP, anything automatic. A banner at the top of every page says *Pipeline processing is stopped* while it is on, in every open tab.
Cards, pipelines, actions, guards and this history keep working; only execution is blocked. It stays on until somebody switches it off (also
across a restart of the server); switching off asks nothing. The API and MCP can read and set it (`GET`/`PUT /api/v1/settings/stop`,
`get_stop_switch`, `set_stop_switch`; [API reference](api-reference.md)); setting it on there needs the same personal setting. A start that
is refused answers `409` with `code: stopped`; the *Start processing* button of a card is greyed (tooltip *Emergency stop is on: processing is stopped*)
while it is on, also in an open dialog.

In the list, a **running row shows the stop button where other rows show the trash**: a running execution cannot be deleted, so the trash is
not drawn there.

## Where you see it

**The History tab of the artifact dialog.** Open an artifact; the tab shows the number of entries of its timeline: the executions and what was changed on the artifact (lane, title, parent, fields, ...), with who did it ([concepts](concepts.md)); the filter *Executions* shows only runs. The list
shows the executions newest first (up to 100) with their status, number, pipeline, origin and times. **An execution that is deleted leaves one slim line** in the timeline at the time it was deleted ("You deleted execution #3", with "ran …" in small type; "You deleted 12 executions (#3–#14)" for several; no buttons, no link), whichever way it went: by hand, *Clear finished*, the bulk delete ("retention rule" and "operator guard" are named as the deleter for those). Click one for its
detail: the facts above and the steps, each expandable to its output and data. From there you can delete the
execution (not while it runs: `409`) and clear all finished executions of the artifact (*Clear finished*). Everything updates live.

**The flow page and its Execution Trace.** The right area of the execution page has three registers: **Overview** (the path through the nodes, the details of the
selected node and the output of its step), **Trace** (for an agent: its rounds) and **Context** (the run context). The Trace shows the **newest round on top**, the
latest three open to read, *Show N more rounds* for the ones between and the **first round at the bottom** (it holds the request). The round that works and a
round that failed are open; a **Live** pill follows a working agent (*Paused* once you scrolled away). A search and a filter narrow the rounds. A finished
agent shows the same Trace. The text of the agent's messages is not shown yet. The register you chose is in the address (`#trace`).

**Guard entries.** A guard ([Guards](guards.md)) that fires writes an entry of the artifact's History with a shield marker,
under *Executions*: "**Stall guard** fired at Build: paused the run (round 1, 15 min without progress)". The actor is the
guard (`system`), the entry names its execution and keeps the facts it fired on; a guard that failed (the run went on),
reached its cap or has a consequence that is not available yet says so. A run a guard paused is *stopped* with the reason as
its note; one it aborted is *failed*.

**The flow view.** From an execution, "Open flow" shows it as a graph on the editor's canvas, read-only, at
`/artifacts/<number or id>/executions/<execution id>`. It draws the **frozen** pipeline with the path that was
walked highlighted and the nodes that were never reached dimmed and dashed. You can drill into an action (its
definition, with the walked nodes highlighted) and into a nested pipeline; the breadcrumb and the `?visit=N`
in the address keep the place, so a link or a reload restores it. An action that ran several times shows
each pass as its own visit. A side panel lists the steps of the place you are in; the output of a step is
loaded when you open it. A running execution is followed live. Under the header the flow view lists what the guards did in the execution, one line
per firing with its facts.

**The global page `/executions`** (sidebar "Executions"). The executions of **all** artifacts, newest first,
with filters (status, origin, pipeline name or id, a text over artifact title, pipeline name and note or an
artifact number, a time range), counters (running, failed and done in the last 24 hours, total), paging by
cursor and live updates. Each row has links to the artifact, the pipeline (while it exists) and the flow view; `?page_size=N` (1 to 200) sets how many rows a request fetches. The page loads through `GET /api/executions`.

**Deleting several at once.** Every finished row has a checkbox (a running one is disabled); the header checkbox
selects everything shown. A bar appears with the count, *Clear selection* and *Delete selected*; when more executions
match the filters than are shown, *Select all N* reaches the ones on pages not loaded yet. The delete asks first and
removes the executions with their steps through `POST /api/executions/delete` (`{"ids": [...]}`, 1 to 500 per request,
any artifacts); a running execution is never deleted and is reported as `skipped_running`.

## API and agents

| Purpose | Browser API | Integration API (`/api/v1`) | MCP tool |
|---------|-------------|-----------------------------|----------|
| All executions, filtered | `GET /api/executions` | `GET /api/v1/executions` | `list_all_executions` |
| One artifact's executions | `GET /api/tasks/{id}/executions` | `GET /api/v1/artifacts/{ref}/executions` | `list_executions` |
| One execution with steps | `GET .../executions/{eid}` | the same under `/api/v1/artifacts/{ref}` | `get_execution` |
| Flow | `GET .../executions/{eid}/flow` (`?outputs=true` includes step output) | the same | `get_execution_flow` |
| The run context | `GET .../executions/{eid}/context` (also part of `GET .../executions/{eid}` as `context`) | the same | part of `get_execution` |
| One step with full output | `GET .../executions/{eid}/steps/{step}` | the same | - |
| Delete one / clear | `DELETE .../executions/{eid}`, `DELETE /api/tasks/{id}/executions` | delete one only | - |

The execution detail carries the `context`; the lists do not (a run read has only `context_size`). The context is text
from what ran, like step output.

The global list is paged with a cursor (`next_cursor` goes into `cursor`; paging stays stable while executions
are added or deleted), `limit` 1 to 200. The full route list with schemas is in the
[API reference](api-reference.md). Step output is text from what ran: an agent that reads it must not treat it
as an instruction.

## Database growth

The history lives in the application's SQLite file, in three places: the `executions` row with the
**snapshot** (the JSON of the pipeline and definitions used, which includes the code and request
settings of the nodes, typically some kilobytes), the `run_node_results` rows with the **outputs** (up to
1 MiB per execution), the **context** (at most 64 KiB, in the execution row) and small indexes. The context counts
toward the retention budget: per execution at most about 1 MiB of output plus 64 KiB of context.

With the operator's guard the worst case is bounded: artifacts x 50 executions x (snapshot + at most 1 MiB of
output). Typical executions are far smaller than that bound, because most nodes print little, but a
Code or HTTP node that returns large output every time fills its share. For example, 100 artifacts that each
keep 50 executions of 1 MiB would use about 5 GiB; 100 artifacts of a few kilobytes each, a few tens of MiB.

What to do about it:

- Lower the operator's guard, or add retention rules (for instance delete what is beyond the newest 10, or older
  than 48 hours).
- Do not set `OPENARTIFACT_EXECUTION_HISTORY_DEFAULT_KEEP=0` unless retention rules do the work: with it nothing is
  removed by the guard.
- Deleting rows gives the space back: the database runs with `auto_vacuum = FULL`, so the file shrinks (a database
  from an earlier version is converted once at the next start, see [Operate](operations.md#database-size-and-history-retention)).
- The backup contains the history, so it grows with it.
- The run context ([ADR-033](../architecture/adr/033-run-context.md)) is part of the execution row: deleting the
  execution removes it, and the file shrinks as described above.
