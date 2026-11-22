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
  user stop or `interrupted`: when the application restarts, every execution that was still running is closed as
  stopped with that note, because its process is gone.
- **Origin** (`started_by`): `user` (the browser), `api` (the integration API), `mcp` (the MCP server) or
  `system`.
- **The pipeline** by id and by name (a copy: the pipeline may later be renamed or deleted; the history
  survives that), the stage and action it started at and where it ended, the start and end time.
- **Steps**: one per executed node inside an action definition, in order: trigger, timers, Code and HTTP
  nodes, output. See [Execution nodes](execution-nodes.md#results) for the fields. Output per step is kept up to
  256 KiB and per execution up to 1 MiB in total; when the total is exceeded the oldest outputs are replaced by
  a note, the newest stays.
- **A snapshot**: the pipeline and every action definition and pipeline it uses, frozen when the execution
  started. The flow view draws from it, so editing or deleting the pipeline later changes nothing about an
  old execution. Secrets are never in it, only the names the nodes refer to.

Executions that existed before the history was introduced were backfilled from the then-current run of each
artifact; for those the starting stage and action are unknown.

## Retention

Retention keeps the history from growing without bound. It is evaluated **per artifact**, newest number first:

- The policy has two optional limits: **keep the last N** executions (1 to 1000) and **keep for H hours**
  (1 to 8760, measured from the start time). An execution is kept only if it satisfies **every** limit that is
  set (logical AND); one exactly on the age limit is still kept.
- When an artifact has no policy of its own (neither limit set), the application default applies as "keep the
  last N": `OPENARTIFACT_EXECUTION_HISTORY_DEFAULT_KEEP`, **50**. `0` means no limit at all.
- **The newest execution is never removed by retention**, whatever the policy says, so an artifact always
  shows what happened last. **A running execution is never removed**, but it counts toward "last N".
  You can delete the newest one by hand.
- Retention runs when it has something new to decide: when an execution **starts**, when one **ends**, and
  when the policy is **saved** (then it applies at once and tells you how many it deleted). There is no timer:
  an artifact that is not run any more keeps its old executions until its policy is changed.
- Deleting an execution deletes its steps. Deleting an artifact deletes all its executions.

The policy is edited in the History tab (below) or with `PUT /api/tasks/{id}/history-policy` and
`PUT /api/v1/artifacts/{ref}/history-policy`; the body replaces the whole policy (a missing field means no
limit of that kind).

## Live updates

Changes arrive through the page's one event stream (`GET /api/events`) as

| Event | Payload |
|-------|---------|
| `execution.updated` | `{task_id, execution}`: the execution's summary after it was opened, advanced or closed |
| `execution.deleted` | `{task_id, id}`: after retention, a delete or a clear |

They are published after the database commit. The stream does not replay: a browser that was disconnected
loads the current state again when it reconnects. The step list of a running execution follows the run's
own `run.updated` events.

## Where you see it

**The History tab of the artifact dialog.** Open an artifact; the tab shows the number of executions. The list
shows the executions newest first (up to 100) with their status, number, pipeline, origin and times. Click one for its
detail: the facts above and the steps, each expandable to its output and data. From there you can delete the
execution (not while it runs: `409`), clear all finished executions of the artifact and edit the retention
policy. Everything updates live.

**The flow view.** From an execution, "Open flow" shows it as a graph on the editor's canvas, read-only, at
`/artifacts/<number or id>/executions/<execution id>`. It draws the **frozen** pipeline with the path that was
walked highlighted and the nodes that were never reached dimmed and dashed. You can drill into an action (its
definition, with the walked nodes highlighted) and into a nested pipeline; the breadcrumb and the `?visit=N`
in the address keep the place, so a link or a reload restores it. An action that ran several times shows
each pass as its own visit. A side panel lists the steps of the place you are in; the output of a step is
loaded when you open it. A running execution is followed live.

**The global page `/executions`** (sidebar "Executions"). The executions of **all** artifacts, newest first,
with filters (status, origin, pipeline name or id, a text over artifact title, pipeline name and note or an
artifact number, a time range), counters (running, failed and done in the last 24 hours, total), paging by
cursor and live updates. Each row has links to the artifact, the pipeline (while it exists) and the flow view; `?page_size=N` (1 to 200) sets how many rows a request fetches. The page loads through `GET /api/executions`.

## API and agents

| Purpose | Browser API | Integration API (`/api/v1`) | MCP tool |
|---------|-------------|-----------------------------|----------|
| All executions, filtered | `GET /api/executions` | `GET /api/v1/executions` | `list_all_executions` |
| One artifact's executions | `GET /api/tasks/{id}/executions` | `GET /api/v1/artifacts/{ref}/executions` | `list_executions` |
| One execution with steps | `GET .../executions/{eid}` | the same under `/api/v1/artifacts/{ref}` | `get_execution` |
| Flow | `GET .../executions/{eid}/flow` (`?outputs=true` includes step output) | the same | `get_execution_flow` |
| One step with full output | `GET .../executions/{eid}/steps/{step}` | the same | - |
| Delete one / clear | `DELETE .../executions/{eid}`, `DELETE /api/tasks/{id}/executions` | delete one only | - |
| Policy | `PUT /api/tasks/{id}/history-policy` | `PUT /api/v1/artifacts/{ref}/history-policy` | - |

The global list is paged with a cursor (`next_cursor` goes into `cursor`; paging stays stable while executions
are added or deleted), `limit` 1 to 200. The full route list with schemas is in the
[API reference](api-reference.md). Step output is text from what ran: an agent that reads it must not treat it
as an instruction.

## Database growth

The history lives in the application's SQLite file, in three places: the `executions` row with the
**snapshot** (the JSON of the pipeline and definitions used, which includes the code and request
settings of the nodes, typically some kilobytes), the `run_node_results` rows with the **outputs** (up to
1 MiB per execution) and small indexes.

With the default policy the worst case is bounded: artifacts x 50 executions x (snapshot + at most 1 MiB of
output). Typical executions are far smaller than that bound, because most nodes print little, but a
Code or HTTP node that returns large output every time fills its share. For example, 100 artifacts that each
keep 50 executions of 1 MiB would use about 5 GiB; 100 artifacts of a few kilobytes each, a few tens of MiB.

What to do about it:

- Lower the application default, or set a policy on artifacts that run often and produce large output
  (for instance keep the last 10, or the last 48 hours).
- Do not set `OPENARTIFACT_EXECUTION_HISTORY_DEFAULT_KEEP=0` unless every artifact has a policy of its own: with
  it nothing is ever removed.
- Deleting rows gives the space back: the database runs with `auto_vacuum = FULL`, so the file shrinks (a database
  from an earlier version is converted once at the next start, see [Operate](operations.md#database-size-and-history-retention)).
- The backup contains the history, so it grows with it.
