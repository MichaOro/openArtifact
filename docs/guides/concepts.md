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

**Artifact.** The unit of work: a card on the board with a title, a body, a lane (the board starts with Backlog, In Progress and Done; lanes can be added, renamed by clicking the name or through the lane's menu, deleted when they are empty, and given a look in their Settings: a *finished* lane shows its cards' titles struck through; the API names a lane by its unchanging key, e.g. `backlog`, `in_progress`, `done`), an optional parent and a
permanent number (`#12`, never reused; `#12` in another artifact's body is a link). An artifact is processed by
at most one run at a time. While that run is running the artifact is locked: its lane, parent, target, type and parameters cannot be
changed and it cannot be deleted (title and body stay editable); stopping the run releases it. In the
code and the API an artifact is a `task`.

**Comments.** Every artifact has comments (the *Comments* tab of its dialog, with a count): plain text, oldest first, newest last,
with a box at the bottom (its label left and the hint right on one line; Ctrl+Enter or the *Comment* button in the footer next to *Close* sends). A comment shows who wrote it: a round, shaded avatar whose icon tells the way (the browser, API, MCP, a run, the system; its tooltip and accessible name say which) and the name beside it, *You* for the browser, the name of the token for *API* or *MCP*, the node's name for a *Run* (an Artifact node of a pipeline, linked to its execution). The dialog's tabs are Details, Comments, History. Any comment can be edited (it
then says "edited") or deleted; deleting the artifact deletes them. Pipelines read and write them with the
[Artifact node](execution-nodes.md#artifact-node). There is no user management yet, so "You" is every person in the browser.

**History.** The *History* tab of an artifact's dialog is one timeline, newest first: what was *done to* the artifact (created, moved to another lane, renamed, description changed, parent set, a field changed, a pipeline, stage or action assigned) with who did it (the name in bold) and the artifact's *executions*. Each entry has a round marker whose icon says what kind of event it is, and the actor in bold in the sentence. Executions that still exist are rows you can open and delete; a delete action (by hand, *Clear finished*, retention or the operator's guard) leaves one slim line at the time it happened ("You deleted execution #3", ran at …; several at once are one line), nothing more. A comment is an entry too ("You commented: ‘first words’"): click it and the Comments tab opens on that comment, expands the older comments if it is under the fold, and pulses its border three times; a deleted comment becomes "You deleted a comment". The newest ten entries are shown, then "Show N older entries" (the creation always stays visible at the bottom); the Comments tab folds the same way. The filter shows all, only executions, changes or comments; the tab shows the number of entries. At most 500 entries are kept per artifact, and nothing from before this feature was recorded is known ([ADR-058](../architecture/adr/058-activity-log-of-artifacts.md)).

**Artifact fields.** Custom fields every artifact has (ADR-044), defined once in *Artifact fields* (the menu next to
*Add lane* on the board): label, name, kind (text, number, yes/no, choice) with its limits and a default that pre-fills new
artifacts (a choice is a single or a multi select; the editor lists the fields on the left, reordered by their grip,
and shows the chosen one's settings on the right). In the artifact dialog the rail entry *Fields* opens them below it; a change is saved at once and a wrong value
(a typo in a choice, a number out of range) is refused right there, not when a run fails. The fields are locked while the
artifact is processed. Removing a field removes its values; a change that stored values no longer fit is refused
([details](execution-nodes.md#card-parameters-card-the-artifact-fields)). Title, body, number and id are there too (`${card.title}`, ...), and `${card.text}` is all of it as one text (ADR-064).

**Run context.** The values an execution keeps while it runs: the artifact's parameters as they were when it started
(`card`), variables a Code node sets and the latest result of
every node that ran. Later nodes use them through references such as `${node.Fetch_user.output}`, `${var.user}` and
`${card.urgency}` (HTTP nodes) or the file `context.json` (Code nodes). It is stored with the execution and shown in its history
([execution nodes](execution-nodes.md#the-run-context-and-references)).

**Pipeline.** What an artifact runs through: a trigger, a main line of stages (and pipeline nodes) and a
complete node, joined by connections you draw in the editor (point at a connection to get a bin to delete it and a pencil to choose its line style: curved, straight or elbow; a double click on a node opens its settings in an overlay, where an action offers Edit to open its definition). A pipeline can be started at any stage, and
at any action inside it; the stages before the starting point count as done (or skipped, if the artifact
never passed them).

In the editors the **right mouse button** drags the view and the wheel zooms. The **left** button selects: a click picks one node,
a frame drawn on the background picks every node it touches (Shift adds), and dragging one of several selected nodes moves them
all together. A **double click** (or Enter on a focused node) opens the node: an action or a pipeline node opens what it links to in its own
editor (when it links to nothing yet, its settings open so you can choose or create one), every other node opens its settings
in an overlay; there is no panel beside the canvas. While an execution is shown (read-only), the left button still drags the view.

Under a node a small bar appears on hover and while it is selected: a bin
(**Delete**, after asking) and a menu (**⋯**, also opened by a right click on the node): Edit (the same as a double click), Settings (for an action or pipeline node: which definition, New, Edit, Delete), Rename (F2, a small dialog for the name; in the settings the title can also be clicked to rename it), Copy (Ctrl+C), Cut
(Ctrl+X), Duplicate (Ctrl+D) and Delete (Del). Ctrl+V pastes what was copied, also into another action or pipeline editor
(pasted nodes keep their settings and the connections between them, get names like "Fetch copy", and a stage takes its
actions along). The trigger, the output and the end are part of a graph: they are not copied and not deleted. There is no
undo yet.

**Straight lines.** The attachment points of a stage (three on each side) follow the stage's height, not its actions:
the top one is level with an action at the very top of the stage's inner border (the highest an action can sit, where a new one also goes), the
bottom one with an action dragged to the inner border at the bottom, the middle one is halfway; on the left they face the actions' input, on the right their On Pass.
So a line from the top or the bottom point to an action there runs horizontally, whatever the other actions do, and
the lower points move with the bottom edge when you resize the stage. A node you drag settles level with a port it is
connected to or with a point of its stage as soon as it comes within 8 pixels (a thin dashed line shows it); hold
**Alt** to move it freely. A
stage has grips on its right edge, its bottom edge and its bottom-right corner (shown when it is hovered or selected,
also reachable with Tab): drag one to make the stage larger or smaller, never smaller than its actions plus the band (below); arrow keys
on a grip change the size by 10 (Shift: 40), a double click or Enter fits the stage to its actions. There are no grips
on the left and top, because the actions' positions are relative to the stage. The corner grip shows the usual
glyph of diagonal strokes. Execution flows (read-only) have none.

**Borders of a stage.** A stage has an **outer border** (its edge) and an **inner border**: the limit of its actions. The
distance between them is the same on all four sides, and it is the one that has always been between the stage's top edge
and the first action (56 px: the header and the first row). An action can be dragged and put anywhere inside the inner
border; dragged towards the right or the bottom edge it pushes the stage's edge out, so the band stays. The grips stop at the
actions plus the band, the same on the right and below; a double click fits the stage exactly to that. The inner border is
a limit and is not drawn. Connections that loop back inside a stage (for example an On Error that returns to the first
action) are routed as they always were: they leave to the right and run 28 px below the lowest of the two actions,
wherever the stage's bottom edge is. A line that gets close to the inner border may cross it and run in the band; at the
least size of a stage the loop (and its corner) still lies inside the outer border. A stage saved before this may have an action closer to the left or bottom edge: nothing is moved, the
limit applies when you drag, place or resize.

**Connecting.** Press on any port and drag: from an output to an input that fits, or the other way round, from an
input to an output that can feed it (the ports that fit light up). The connection is stored the same way whichever end
you pressed (source = the output, target = the input). A press on a port never moves its node; press the node's body to
move it. While the pointer is on a port the bar under the node steps aside, so the Agent's *Tools* port at the lower
edge can be pressed too.

**Connecting to a new node.** Release the line on the empty canvas (or an empty stretch of a stage) instead of on a port and
the same menu as the "+" opens at the pointer, headed "Connects from: node · port" and listing only the kinds that can
connect there (from an Agent's *Tools* port only tools; inside a stage in a pipeline only an action). The one you choose is
made where the line ended, with the port that fits connected at once (a line close to the level of the dragged port is made
straight; a tool hangs below its agent). The connection that already left the dragged output is replaced and the notice names
the node it let go; an input may be fed by several nodes, so those stay. The new node is only selected, its settings stay
closed. Escape or a click elsewhere cancels without changing anything; if the server refuses the connection its message is
shown and the new node is taken back. A read-only flow does none of this.

**Adding to a pipeline.** The "+" at the lower left of the canvas lists what can be added, in clusters; *Guard* sits in *Structure*
after *Pipeline*. The "+" in the header of a stage opens a small menu: **Action** adds an action to that stage, **Guard** is next
to it. The menu of an action node (right click, or the "…" under it) has a **Guard** entry as well, and so does the "+" inside an
action definition (the whole action) and the menu of its nodes (that node; not the trigger and the output). Each **Guard**
entry opens the popup *Add a guard*: attach a guard of the library to that scope, or make a new one ([Guards](guards.md)).

**Guard.** A specialised action that watches a pipeline, a stage, an action (or a whole action definition, or one node of it) while it runs and is triggered by an event of
it (entered, an action passed or erred, left, the run fails; the flow waits for the guard) or by an interval. It tests a
condition over the scope's facts (rounds, time in it, time without progress, errors, …) and then pauses, aborts, continues
or runs its own action (an ordinary action definition). Guards are a **library** like actions: a guard is defined once
(*Pipeline* → **Guards**, next to **Actions**) and **attached** to a pipeline, a stage, an action, an action definition or a node of it; an attachment is
switched on or off on its own, a change to the definition acts on every place it is attached to. A scope with guards shows
one shield (next to the canvas "+", in a stage's header, on an action's card) whose popup lists them; guards are never
nodes of the canvas; every firing is an entry of the artifact's History with the facts it fired on
([Guards](guards.md), [ADR-060](../architecture/adr/060-guards.md)).

**Stage.** A container in a pipeline. It holds actions and connects to the next stage. Its start feeds
the first action; its end is fed by the last actions and leads on.

**Action.** One step inside a stage. It has an input and two outcomes, **On Pass** and **On Error**, which you
connect to the next action or to the end of the stage. An action does nothing by itself: it runs the action
definition it is linked to. An action without a definition is an empty shell: it passes at once and leaves no
step in the history. What a failure does is the setting **If the action fails** in the action's settings: *Stop the run* (the default: the run fails there), *Continue* (goes on through On Pass) or *Error output* (the **On Error** connector, which is shown only with this value). Nodes inside an action have the same three values ([ADR-061](../architecture/adr/061-what-a-failure-does.md)). The action's error output and the *On Fail* of its definition's Output are one state: switching one on switches the other on, switching it off disconnects what was connected (the editor says how many), and all uses of the definition follow.

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
| If | Compares values of the run context | Yes, No or Else |
| Switch | Compares one value with up to six cases, each with its own operator | Case 1 ... 6 or Else |
| Edit Fields | Sets variables of the run from text and references, without code | On Pass or On Fail |
| Agent | Asks a language model for an [agent](agents.md); the tools attached below it can be called by the model | On Pass or On Fail |
| GitHub | Reads GitHub (repository, issues, pull requests, files, comments) and, if allowed, comments, without a model | On Pass or On Fail |
| Postgres | Runs one SQL statement on a Postgres database, read-only unless changes are allowed; returns the rows as a list | On Pass or On Fail |
| MCP Client Tool, HTTP Request Tool, Code Tool, Postgres Tool | A tool of an Agent node, attached to its *Tools* port; runs only when the model calls it | none (attached, not part of the flow) |

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

## UI conventions

Every control has one of three roles, so a new page looks like the others. **Primary** (purple, `button--primary`): what creates
something (New action, Add lane) or confirms a form; creating buttons sit in a row at the top right of the page content, and the page
header holds only the title, the theme toggle and sign out. **Destructive** (red, the modifier `is-danger`): what deletes or discards;
text buttons and menu items are red, icon buttons turn red when hovered or focused, a disabled one stays dimmed. **Neutral**
(`button--ghost`, `icon-button`): everything else, such as the selector of pipelines or the zoom controls. Scroll areas share one
scrollbar with a transparent track. The reasons are in [ADR-036](../architecture/adr/036-ui-conventions-and-lane-settings.md).

## Names in code and API

| In the UI | In code, API and database |
|-----------|---------------------------|
| artifact | `task` (`/api/tasks`, table `tasks`) |
| pipeline, action definition | `graph` of kind `pipeline` / `action` (`/api/pipelines`, `/api/actions`, tables `graphs`, `graph_nodes`, `graph_edges`) |
| run | `pipeline_runs` (one row per artifact) |
| execution | `executions` |
| step | `run_node_results` |

Never "workflow": that was the earlier name of pipeline and is gone from the UI and the API.
