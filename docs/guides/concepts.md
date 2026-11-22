# Concepts

The domain model in plain language: what an artifact is, what a pipeline does with it, and how a run
leaves a record behind. The UI uses these words; the code and the API sometimes use older storage names, listed
at the end. For the decisions behind the model see the [architecture documentation](../architecture/arc42/12-glossary.md).

## The picture

```
 Artifact #12            started in a pipeline
 (a card on the board) ───────────────────────────────┐
                                                      ▼
 PIPELINE      Trigger ──▶ [ Stage A ] ──▶ [ Stage B ] ──▶ Pipeline node ──▶ Complete
                               │                │              (runs another pipeline)
                     ┌─────────┴────────┐       ...
 STAGE A             │  Action 1 ──On Pass──▶ Action 2 ──On Pass──▶ (stage end)
                     │      └─On Error──▶ (stage end or another action)
                     └──────────────────┘
                            │ each action is linked to an
                            ▼
 ACTION DEFINITION   Trigger ──▶ Timer ──▶ Code ──On Pass──▶ HTTP ──On Pass──▶ Output: On Pass
                                             └─On Fail────────────On Fail──▶ Output: On Fail
```

An artifact is carried through a pipeline. The pipeline is a graph of stages; each stage holds actions; each
action runs an action definition, which is a small graph of nodes that do the work (wait, run code, call a
URL). Every start leaves an execution in the history.

## Terms

**Artifact.** The unit of work: a card on the board with a title, a body, a lane (Backlog, In Progress, Done: the board shows them under titles the user can change with the pencil in the lane header; the code and the API keep `backlog`, `in_progress`, `done`), an optional parent and a
permanent number (`#12`, never reused; `#12` in another artifact's body is a link). An artifact is processed by
at most one run at a time. While that run is running the artifact is locked: its lane, parent, target, type and parameters cannot be
changed and it cannot be deleted (title and body stay editable); stopping the run releases it. In the
code and the API an artifact is a `task`.

**Artifact type and parameters.** An artifact can have a type, which you define on the *Artifact types* page (sidebar):
a name and a list of typed parameters (text, number, yes/no, choice) with a label, whether a value is required, a default
and, for a choice, the allowed values. The artifact dialog then shows these as form fields; a wrong value (a typo in a
choice, a number out of range, a missing required value) is refused when you save, not when a run fails. Which
parameters exist is data of the type, so a second kind of artifact with its own parameters needs no code. The type
and the parameters are locked while the artifact is processed. A type that artifacts use cannot be deleted, and its
parameters cannot be removed or changed in a way that could invalidate stored values
([details](execution-nodes.md#card-parameters-card)).

**Run context.** The values an execution keeps while it runs: the artifact's parameters as they were when it started
(`card`), variables a Code node sets and the latest result of
every node that ran. Later nodes use them through references such as `${node.Fetch_user.output}`, `${var.user}` and
`${card.urgency}` (HTTP nodes) or the file `context.json` (Code nodes). It is stored with the execution and shown in its history
([execution nodes](execution-nodes.md#the-run-context-and-references)).

**Pipeline.** What an artifact runs through: a trigger, a main line of stages (and pipeline nodes) and a
complete node, joined by connections you draw in the editor. A pipeline can be started at any stage, and
at any action inside it; the stages before the starting point count as done (or skipped, if the artifact
never passed them).

**Stage.** A container in a pipeline. It holds actions and connects to the next stage. Its start feeds
the first action; its end is fed by the last actions and leads on.

**Action.** One step inside a stage. It has an input and two outcomes, **On Pass** and **On Error**, which you
connect to the next action or to the end of the stage. An action does nothing by itself: it runs the action
definition it is linked to. An action without a definition is an empty shell: it passes at once and leaves no
step in the history. If an action fails and its **On Error** is not connected, the whole run fails there.

**Action definition.** What an action does, as a graph of its own: a trigger, then **execution nodes**, then an
**Output**. The Output has an **On Pass** connector and, if switched on, an **On Fail** connector; the node
that reaches On Pass makes the action pass, the one that reaches On Fail makes it leave through On Error. A
path that ends nowhere (a node with an unconnected outcome) fails the action. One definition can be used by
many actions.

**Execution nodes.** The nodes of an action definition that do work:

| Node | What it does | Leaves by |
|------|--------------|-----------|
| Timer | Waits 1 second to 1 day | Next |
| Code | Runs shell or Python text | On Pass or On Fail |
| HTTP request | Calls an HTTP address | On Pass or On Fail |

Details in the [execution nodes guide](execution-nodes.md). Further kinds are added through a registry
([Extending](extending.md)).

**Pipeline node.** A step of the main line that runs another pipeline and, when that is complete, goes on.
Pipelines may nest five levels deep; a pipeline that calls itself (directly or through others) is refused at
the start.

**Run.** The *current state* of an artifact in its pipeline: which stage and action it is at, the status
(`running`, `done`, `failed`, `stopped`) and a note. There is one run per artifact and every start reuses it.
It is what the board shows live.

**Execution.** One start of an artifact, kept for good: its number (`#1`, `#2` ... per artifact), the pipeline
it ran in, who started it (`user`, `api`, `mcp`, `system`), its status, where it started and where it ended,
its steps and a frozen copy of the pipeline. A restart makes a new execution. The history is made of
executions; see the [execution history guide](execution-history.md).

> Run versus execution: the run is *where the artifact is now* and is overwritten by the next start; an
> execution is *what happened in one start* and stays until retention removes it.

**Step.** The record of one node being executed inside an action definition, in order: the trigger, each
timer, Code and HTTP node, and the output. It has the outcome (`pass` / `fail`), the port it left by, the
exit code for code, the output text (up to 256 KiB), a reason, a small data object (for HTTP: the status
code) and the times. Stages, actions without a definition and pipeline nodes are not steps; they are
reconstructed for the flow view.

**Snapshot.** The frozen copy of the pipeline and of every action definition and pipeline it uses, taken when
the execution starts. Editing a pipeline later never changes how an older execution is shown or how a
running one continues.

**Visit.** One pass of an execution through one graph: the root pipeline, an action's definition, a called
pipeline. An action that runs twice (a loop through On Error) has two visits. Visits nest: the root pipeline
visit contains the visits of its actions' definitions.

**Flow.** An execution drawn as a graph: the frozen pipeline and definitions on the editor's canvas with the
path that was walked highlighted, the visits you can drill into and the steps with their output. The path is
replayed from the snapshot and the steps; it is not stored separately.

**Retention.** The rule that removes old executions: per artifact by count (keep the last N) and/or age (keep
the last H hours), with an application default of 50 executions. The newest execution and a running one are
never removed by it.

## Names in code and API

| In the UI | In code, API and database |
|-----------|---------------------------|
| artifact | `task` (`/api/tasks`, table `tasks`) |
| pipeline, action definition | `graph` of kind `pipeline` / `action` (`/api/pipelines`, `/api/actions`, tables `graphs`, `graph_nodes`, `graph_edges`) |
| run | `pipeline_runs` (one row per artifact) |
| execution | `executions` |
| step | `run_node_results` |

Never "workflow": that was the earlier name of pipeline and is gone from the UI and the API.
