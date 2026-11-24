# Guards

A **guard** watches a part of a pipeline while it runs and steps in: it pauses a run that makes no progress, aborts one
that runs too long, or every few rounds of a loop runs its own action (an agent that judges whether more rounds are
still worth it). A guard is a specialised action: its logic is an ordinary action definition, but it is not part of
the flow. It is triggered by an **event** of what it watches or by an **interval**. The decision record is
[ADR-060](../architecture/adr/060-guards.md); the terms are in [Concepts](concepts.md).

Guards live in a **library**, like actions: a guard is *defined* once (the **Guards** page, under *Pipeline* next to
*Actions*) and *attached* wherever it should watch (a pipeline, a stage, an action). A definition changes for all the
places it is attached to; an attachment can be switched on or off on its own.

## What a guard watches

| Scope | Entered | Left |
|-------|---------|------|
| Pipeline | after its trigger | when the run is done (a called pipeline: when it returns) |
| Stage | before its entry action starts, **and again** every time a loop brings the flow back to that action | when the flow leaves the stage |
| Action | before it runs | after it ended (On Pass or On Error) |

A guard watches only while its scope is active. There are no guards on guards.

An **action definition** can hold guards too. They are scopes of the *action editor*:

| Scope | Entered | Left |
|-------|---------|------|
| Definition (the whole action) | before the action runs, wherever it is used | after it ended |
| Node (one execution node of it) | before the node runs, every time a loop brings the flow back to it | after it ended |

A guard on a definition watches that action in **every stage of every pipeline** that uses it, with a counter of its own
for each use; a guard on a node watches that node only. A node can be watched when its kind is *guardable*: Code, HTTP,
Timer, If, Switch, Agent, Edit Fields, Postgres, GitHub and Artifact (not the trigger, the output or a tool node). A
*stall* guard on an Agent node therefore stops that node while the rest of the action waits.

**Counters.** Per scope and run the engine counts `runs` (entries: the rounds of a looping stage), `passes` and `errors`
(actions in it left by On Pass / On Error), the last action's status and the time since the entry; per guard,
`guard.runs` (times it fired). They are never reset within a run; a new start is a new run. A called pipeline counts per
call. The counters are kept with the execution (`guard_state`) and shown in its flow.

## The Guards page (the library)

*Pipeline* → **Guards** lists every guard of the library: its name, one line about what fires it and its condition
("Every 1 minute · Time without progress is at least 15 minutes"), its consequence and **Used in N places**. The search
finds a guard by its name, its description or that line.

- **New guard** opens a menu: **Blank guard** (an empty definition in the guard editor) or **From template: Stall guard /
  Runtime guard / Health guard** (the template becomes a library entry at once, with its own action where it has one,
  and opens in the editor).
- A click on a guard opens it in the **guard editor**.
- **Delete** (the bin) is refused while the guard is attached anywhere: the bin says why ("Detach it first: it is used
  in 2 places"). Detach it in the pipelines first. Its own action stays (an action definition like any other).
- A definition has no on/off of its own: only where it is attached it is switched on or off.

## Attaching a guard

In the pipeline editor every **Guard** entry opens the small popup **Add a guard** for that scope:

- the **+** menu of the canvas → *Guard*: the pipeline;
- the **+** of a stage → *Guard*: that stage;
- the menu of an action node (right click or **…**) → *Guard*, or **Add guard** in the *Guards* section of the action's
  settings: that action.

In the **action editor** (an action definition) the same entries exist: the **+** menu of the canvas → *Guard*: the whole
action; the menu of a node (Code, HTTP, Agent, …) → *Guard*, or **Add guard** in its settings: that node. The trigger and
the output have no such entry.

The popup has two buttons, **Attach guard** on the left and **New guard** (the primary one) on the right; they wrap under
each other when the popup is too narrow. Opened from a **stage header or a card** (which the popup would cover next to each
other) the two buttons are **stacked**, one above the other; from the canvas "+", the shield or the settings they sit side by side. **New guard** opens the guard editor for a new definition that is attached
there when you save it, and **Attach guard** opens the **attach dialog**. **Attach guard** is disabled with the note
*No other guard to attach.* when every guard of the library is attached there already. Below, *Attached here* lists the
guards of that scope, with their switch and Detach.

The attach dialog has one field, a **combobox**: it lists the guards that are not attached to that scope yet; typing
narrows the list by name first, then by description and what the guard does ("hea" finds *Health guard* and
*Health agent*); arrow keys move through it, Enter takes the highlighted one (and does not submit), Escape closes the list
and only then the dialog. **Attach** is there once one is chosen; the popup comes back with the guard under *Attached here*.

## The shield

A scope with at least one guard attached shows **one shield**: the pipeline's (in an action editor: the action's) next to
the **+** at the top right of the canvas, a stage's in its header next to its **+**, an action's or a node's as a bare icon
in the top right corner of its card. The shield is the quiet icon button of the catalog: no frame, a 24 px hit area. Its
tooltip says how many guards are configured there ("2 guards configured"; it never says *active*: guards act only
while a run goes). A click opens the popup of that scope's guards:

| In the popup | What it does |
|--------------|--------------|
| The switch | Switches the guard on or off **there** (off acts at once on running executions; on at the next start) |
| The name | Opens the definition in the guard editor; a guard that is off is muted and struck through |
| × (Detach) | Takes the guard off that scope; the definition stays in the library |
| *In the action* (an action's card in a pipeline) | The guards that sit **inside** the action's definition, on the whole action or on one of its nodes, by name with what they watch; no switch and no Detach (they belong to the action); a name opens the guard; **Open the action** opens the action editor |

The card of an action in a pipeline counts the guards inside its definition as well ("3 guards configured": its own and
the ones in the action), so a stall guard on an Agent node shows up in the pipeline too.

Arrow keys move between the controls of the popup, Escape closes it and returns to the shield. A guard is never a node
of the canvas; deleting a stage or an action detaches the guards attached to it (their definitions stay).

## The guard editor

The window's title is **Guard – NAME**: the name is renamed in place (click it, or Enter or Space on it; Enter keeps,
Escape leaves only the field; a guard needs a name, an empty one is refused with a hint). Under the title it says in how
many places the guard is used: **a change affects all of them** (at the next start of a run; a running execution keeps
what it started with). There is no Name row and no template row (templates are in the page's *New guard* menu).

The form is a manifest (`ui/forms/guard.yaml`, [ADR-062](../architecture/adr/062-configuration-windows-as-data.md)) drawn by
`form-view.js`: on a wide window **Trigger** and **Then** side by side, **Condition** across the whole width, **Escalation steps**
and **Logic** side by side; on a narrow window one column. *Held for* and *Quiet after firing* are folded behind **More
options**. A typical guard needs 850 × 746 px (it was 1024 × 1216). The help of a part is in the (i) after its name.

**Settings**

| Part | What it says |
|------|--------------|
| Can watch | **Hidden on purpose** (the owner may want it back): the kinds of scope a definition may be attached to (`scope_types`) stay in the data, the API and the checks, a new definition may watch all five scopes (pipeline, stage, action, definition, node; definitions made before the action scopes were widened by migration 0049), and the control is kept unused in `guards/scope-chips.js` with an entry in `quarantine.json` until the owner decides |
| Trigger | **On an event**: entered, an action passed, an action erred, left, the run fails. The flow **waits** for the guard and goes on as it decides. **Every few seconds**: check every N seconds while the scope runs (at least the minimum interval), fire once the condition has held for *held for* seconds, then stay quiet for *quiet after firing* seconds; the running action keeps running meanwhile and is stopped if the guard pauses or aborts |
| Condition | The rule builder (the same one as the retention rules) over the facts below; an empty condition never fires |
| Escalation steps | "From firing k on, every N rounds (or N seconds)": counted from the guard's last firing. Without steps it fires whenever the condition holds |
| Then | The consequence; *notify* and *hand over* are shown disabled until notifications (card #93) and handover (card #95) exist. For *Run the guard's action*: what follows when its action fails |
| Preview | How many running scopes the condition holds for right now, over the places it is attached to (no trigger, escalation or cap applied) |

**Logic** (a section of the form). The guard's own action, for the consequence *Run the guard's action*: choose an action definition, or
**New** (an empty action definition named after the guard), and **Edit**, which saves the guard first and opens the
action in the action editor (its *Back to …* returns to the guard). With another consequence the part says that the
guard runs no action of its own and offers **Run an action when it fires**.

### Facts a condition can test

| Field | Meaning |
|-------|---------|
| Rounds of the scope (`runs`) | Entries of the scope in this run |
| Time in the scope (`elapsed`) | Seconds since the scope was entered |
| Time without progress (`idle`) | Seconds since the last step of the run or heartbeat (or the entry, if later) |
| Errors / Passes | Actions in the scope left by On Error / On Pass |
| Times this guard fired (`guard.runs`) | Its firings on this scope in this run |
| Last action (`last_status`) | passed, erred, none yet |
| Cost (`cost`) | Only when a node reports a cost (none does yet): a condition on it never fires today |
| Result field (`var.NAME`) | A numeric run variable, e.g. one a Code node declares and sets (`"vars": {"gain": 0.02}`) |

A fact that is missing makes every condition on it false.

### Consequences

| Consequence | What happens |
|-------------|--------------|
| Pause the run | The run stops with the reason (`Paused by guard …`) and stays where it is; start it again to resume |
| Abort the run | The run fails with the reason (`Aborted by guard …`); a running action is stopped |
| Continue | Only recorded |
| Run the guard's action | Its own action runs with the facts as `${var.guard_runs}`, `guard_idle`, `guard_elapsed`, `guard_errors`, `guard_passes`, `guard_last_status`, `guard_firing`, `guard_name` (Code nodes read them in `context.json`); On Pass continues, On Error does the fallback. It works on a copy of the run's context, its steps are not steps of the execution, and nothing watches it. Saving a guard with this consequence and no action makes an empty one; the *Logic* part chooses, makes and opens it |

## Writing a guard: three examples (the templates)

*New guard* → *From template* puts one of them into the library; attach it where it should watch.

| Template | Can watch | Trigger | Condition | Then |
|----------|-------|---------|-----------|------|
| **Stall guard** | action, stage, pipeline | every 60 s, quiet 10 min after firing | time without progress ≥ 15 min | pause |
| **Runtime guard** | action, stage, pipeline | every 60 s | time in the scope ≥ 1 h | abort |
| **Health guard** | stage | entered | rounds ≥ 5, steps: from firing 1 every 5 rounds, from firing 2 every 3 rounds | run its action; if it fails: pause |

The Health guard's action has two nodes: an **agent** *Judge progress* (choose the agent; its prompt asks for one JSON
object `{"gain": 0..1, "improving": …, "reason": …}` judging whether the latest round improved the work enough) and a
**Code** node *Marginal gain* that reads the judgement from `context.json`, declares and sets the result field `gain`, and
passes only when `gain ≥ 0.05` (change `MIN_GAIN` to suit the work). Too little gain fails the action, and the fallback
pauses the run.

## Heartbeat

An external agent or tool that works for a long time inside one action (and therefore records no steps) can say that it
still makes progress: `POST /api/v1/executions/{execution_id}/heartbeat` with an optional `{"note": "…"}` (200
characters), or the MCP tool `heartbeat(execution_id, note?)`. It restarts the stall clock (`idle`) of the running
execution. At most one per `OPENARTIFACT_HEARTBEAT_MIN_SPACING_SECONDS` (default 1 s; closer: 429); 404 for an unknown
execution, 409 when it is not running. The last heartbeat and a count are kept with the execution, not in the activity.

## Limits and safety

| Limit | Default | Setting |
|-------|---------|---------|
| Shortest interval | 30 s (shorter is refused with 422) | `OPENARTIFACT_GUARD_MIN_INTERVAL_SECONDS` |
| Firings per guard, scope and run | 20 (the cap is recorded once) | `OPENARTIFACT_GUARD_MAX_FIRINGS` |
| Time a guard may take (condition and its action) | 600 s; then the flow goes on | `OPENARTIFACT_GUARD_TIMEOUT_SECONDS` |
| Guards attached per pipeline | 100 | — |
| Guards in the library | 1000 | — |
| Escalation steps | 10 | — |

- **Fail open:** a guard that raises or times out is recorded as failed and the flow goes on.
- No guards on guards; a guard's own action does not trigger guards.
- A running execution keeps the guards it started with (the definitions and where they are attached); switching an
  attachment off acts at once.
- An event guard with its own action holds up the flow while the action runs.
- After a restart nothing is running, so nothing is watched; the counters of the interrupted execution stay with it.

## Where you see what guards did

- **History** of the artifact: one entry per firing under *Executions*, with a shield: "**Health guard** fired at Draft:
  paused the run (round 8, 14 min without progress)". A guard that failed, reached its cap or has a consequence that is
  not available yet says so.
- The **flow view** of the execution lists the firings under its header; `GET /api/v1/artifacts/{ref}/executions/{id}/flow`
  returns them with the counters in `guards`.
- The activity API (`GET /api/v1/artifacts/{ref}/activity`, MCP `list_activity`) returns them as kind `guard` with the
  facts.

## API

| Method and path | What |
|-----------------|------|
| `GET /api/v1/guards?pipeline_id=` | The library: each definition with `used_by` and its `attachments` (with `pipeline_id`: only the guards attached to that pipeline) |
| `POST /api/v1/guards` | Create a definition (`name`, `description?`, `scope_types?`, `trigger`, `when`, `consequence`, `fallback`, `escalation`, `action_id`) |
| `GET /api/v1/guards/templates`, `POST /api/v1/guards/from-template` | The templates; make one into a definition (`template`, `name?`, `description?`) |
| `GET`, `PATCH`, `DELETE /api/v1/guards/{id}` | Read, change (acts on every place it is attached to), delete (`409` while attached; its action stays) |
| `GET /api/v1/guard-attachments?pipeline_id=` | Where guards are attached: `pipeline_id` is any graph that holds scopes (a pipeline or an action definition); `inner=true` adds the attachments inside the action definitions a pipeline uses. Each row has `graph_id`, `holder_kind`, `holder_name`, `scope_type`, `scope_id`, `scope_name` |
| `POST /api/v1/guard-attachments` | Attach: `guard_id`, `graph_id` (the pipeline or action definition that holds the scope; `pipeline_id` is the old name), `scope_type` (`pipeline`, `stage`, `action` of a pipeline; `definition`, `node` of an action definition), `scope_id` (left out for `pipeline` and `definition`), `enabled?`; `422` for a scope the guard may not watch or that is not part of the pipeline, `409` when it is attached there already |
| `PUT /api/v1/guard-attachments/{id}/enabled` | `{"enabled": false}` switches it off there |
| `DELETE /api/v1/guard-attachments/{id}` | Detach |
| `POST /api/v1/executions/{id}/heartbeat` | The heartbeat |
| `GET /api/rules/schemas/guard` | The fields, operators and consequences |

The browser API (`/api/guards`, `/api/guard-attachments`) has the same routes and `POST /api/guards/preview`
(`guard_id`, `when`). MCP tools: `list_guards(pipeline?)` (the definitions with their attachments),
`set_guard_enabled(guard, enabled, pipeline?)` (switches an attachment: its id, or the guard's name when it is attached
in one place), `heartbeat(execution_id, note?)`.

```json
{"name": "Stall guard", "scope_types": ["pipeline", "stage", "action"],
 "trigger": {"type": "interval", "every_seconds": 60, "for_seconds": 0, "cooldown_seconds": 600},
 "when": {"type": "group", "mode": "all", "items": [{"type": "condition", "field": "idle", "op": "at_least", "value": 900}]},
 "consequence": "pause"}
```

```json
{"guard_id": "…", "pipeline_id": "…", "scope_type": "action", "scope_id": "…"}
```
