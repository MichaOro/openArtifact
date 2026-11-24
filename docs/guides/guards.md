# Guards

A **guard** watches a part of a pipeline while it runs and steps in: it pauses a run that makes no progress, aborts one
that runs too long, or every few rounds of a loop runs its own action (an agent that judges whether more rounds are
still worth it). A guard is a specialised action: its logic is an ordinary action definition, but it is not part of
the flow. It is triggered by an **event** of what it watches or by an **interval**. The decision record is
[ADR-060](../architecture/adr/060-guards.md); the terms are in [Concepts](concepts.md).

## What a guard watches

| Scope | Entered | Left |
|-------|---------|------|
| Pipeline | after its trigger | when the run is done (a called pipeline: when it returns) |
| Stage | before its entry action starts, **and again** every time a loop brings the flow back to that action | when the flow leaves the stage |
| Action | before it runs | after it ended (On Pass or On Error) |

A guard watches only while its scope is active. There are no guards on guards.

**Counters.** Per scope and run the engine counts `runs` (entries: the rounds of a looping stage), `passes` and `errors`
(actions in it left by On Pass / On Error), the last action's status and the time since the entry; per guard,
`guard.runs` (times it fired). They are never reset within a run; a new start is a new run. A called pipeline counts per
call. The counters are kept with the execution (`guard_state`) and shown in its flow.

## Adding a guard

In the pipeline editor:

- the **+** menu → *Guard*: a guard of the pipeline (its chip sits in the tool bar);
- the **+** of a stage → *Guard*: a guard of that stage (its chip sits in the stage's header);
- the menu of an action node (right click or **…**) → *Guard*, or the *Guards* section of the action's settings.

A guard is shown as a **shield chip**, never as a node of the canvas; a chip opens the **Guard window**. A crossed-out
name is a guard that is off.

## The Guard window

| Part | What it says |
|------|--------------|
| Start from | A blank guard or a template (new guards only); the template fills in the rest, which you can change |
| Trigger | **On an event**: entered, an action passed, an action erred, left, the run fails. The flow **waits** for the guard and goes on as it decides. **Every few seconds**: check every N seconds while the scope runs (at least the minimum interval), fire once the condition has held for *held for* seconds, then stay quiet for *quiet after firing* seconds; the running action keeps running meanwhile and is stopped if the guard pauses or aborts |
| Condition | The rule builder (the same one as the retention rules) over the facts below; an empty condition never fires |
| Escalation steps | "From firing k on, every N rounds (or N seconds)": counted from the guard's last firing. Without steps it fires whenever the condition holds |
| Then | The consequence; *notify* and *hand over* are shown disabled until notifications (card #93) and handover (card #95) exist |
| If its action fails | For *Run the guard's action*: pause, abort or continue |
| On | Off acts at once on running executions |
| Preview | How many running scopes the condition holds for right now (no trigger, escalation or cap applied) |

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
| Run the guard's action | Its own action runs with the facts as `${var.guard_runs}`, `guard_idle`, `guard_elapsed`, `guard_errors`, `guard_passes`, `guard_last_status`, `guard_firing`, `guard_name` (Code nodes read them in `context.json`); On Pass continues, On Error does the fallback. It works on a copy of the run's context, its steps are not steps of the execution, and nothing watches it. Saving a guard with this consequence and no action makes an empty one; *Edit the guard's action* opens it in the action editor |

## Writing a guard: three examples (the templates)

| Template | Scope | Trigger | Condition | Then |
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
| Guards per pipeline | 100 | — |
| Escalation steps | 10 | — |

- **Fail open:** a guard that raises or times out is recorded as failed and the flow goes on.
- No guards on guards; a guard's own action does not trigger guards.
- A running execution keeps the guards it started with; switching one off acts at once.
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
| `GET /api/v1/guards?pipeline_id=` | List guards |
| `POST /api/v1/guards` | Create one (`pipeline_id`, `name`, `scope_type`, `scope_id`, `trigger`, `when`, `consequence`, `fallback`, `escalation`, `definition_id`, `enabled`) |
| `GET`, `PATCH`, `DELETE /api/v1/guards/{id}` | Read, change, delete (its action stays) |
| `PUT /api/v1/guards/{id}/enabled` | `{"enabled": false}` switches it off |
| `POST /api/v1/executions/{id}/heartbeat` | The heartbeat |
| `GET /api/rules/schemas/guard` | The fields, operators and consequences |

The browser API (`/api/guards`) also has `GET /templates`, `POST /from-template` and `POST /preview`. MCP tools:
`list_guards(pipeline?)`, `set_guard_enabled(guard, enabled)`, `heartbeat(execution_id, note?)`.

```json
{"pipeline_id": "…", "name": "Stall guard", "scope_type": "action", "scope_id": "…",
 "trigger": {"type": "interval", "every_seconds": 60, "for_seconds": 0, "cooldown_seconds": 600},
 "when": {"type": "group", "mode": "all", "items": [{"type": "condition", "field": "idle", "op": "at_least", "value": 900}]},
 "consequence": "pause"}
```
