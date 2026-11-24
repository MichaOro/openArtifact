# ADR-012: Pipeline and action definitions as a graph, edited on a canvas

> Renamed: this ADR was written with the product term "workflow"; the vocabulary is now Pipeline, Stage, Action and execution nodes, and the storage term is "graph". See ADR-015. The file name is kept so that links stay valid.

**Status:** Accepted  
**Date:** 2026-11-21  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** —  
**Amended by:** [ADR-014](014-building-blocks-and-extension-points.md) (routing select), [ADR-015](015-vocabulary-and-storage-names.md) (vocabulary), [ADR-030](030-accessibility-scope.md) (accessibility), [ADR-040](040-agent-tools.md) (tool nodes attached below an Agent node), [ADR-041](041-github-and-postgres-nodes.md) (GitHub, Postgres and Postgres Tool nodes)

## 1. Context

Artifacts are meant to pass through pipelines. A pipeline is defined visually, without tables or
forms, in the spirit of n8n: boxes and lines that can be dragged around. The first stage only
defines the structure (stages, actions and how they connect); what an action does inside is
defined later in a separate interface.

## 2. Decisions

### 2.1 Model

A pipeline is a graph of **nodes** and **edges** between their **ports**.

| Node | Ports | Meaning |
|------|-------|---------|
| Trigger | out | Start of the pipeline (placeholder; manual, webhook or event later). Every pipeline starts with one. |
| Stage | start, end | An isolated container of actions. Each port serves both sides: `start` receives from the trigger or a previous stage and feeds the first action; `end` receives from the stage's actions and leads on to the next stage or an ending. Which side an edge is on follows from its other end (migration 0009 merged the former `in`/`entry` and `out`/`exit`). Each side offers three attachment points (slots 0–2, top to bottom); an edge stores its slot per end (migration 0010), and only used points are shown unless the stage is hovered, selected or a connection is being drawn. |
| Action | in, pass, error | A business execution, a container for now. Connects only to actions of its own stage or to its stage's `end`. `error` may also go to its own input. |
| Complete | in | Ends the pipeline; stands outside any stage. |

There are no fixed "Completed" or "Needs Attention" nodes: a human-in-the-loop step is just an
action. An output has at most one edge (connecting again replaces it); an input accepts many.
Unconnected outputs are allowed. The rules live in `graph/rules.py` and are enforced by the
server (422); the editor mirrors them only to offer valid targets.

### 2.2 Persistence

Tables `graphs`, `graph_nodes` and `graph_edges` (migration 0008 as `workflows`, `workflow_nodes`, `workflow_edges`; renamed in migration 0020, ADR-015) with real foreign keys
and `ON DELETE CASCADE`: deleting a stage removes its actions and every edge touching them. An
action's position is relative to its stage's body; stages store their size. Every change is saved
immediately through `/api/pipelines/...` and `/api/actions/...`; there is no separate save step and no live sync between
tabs yet.

### 2.3 Editor

Server-rendered pages (`/pipelines`, `/pipelines/{name}`, `/actions`, `/actions/{name}`) with vanilla JS modules, no library and
no build step (ADR-010). Nodes are HTML elements (accessible, stylable with the tokens) inside a
transformed "world"; edges are SVG paths drawn over them. Pan, zoom, moving nodes and dragging from
a port to connect use Pointer Events, so mouse, touch and pen work alike. An action stays inside
its stage, which grows to contain it. The right-hand inspector edits the selected node and offers a
**Routing** select per output (removed again, see 2.21); Enter on a focused node
opens it, arrows nudge, Delete removes. Connections are made by dragging only.

### 2.4 Out of scope for now

What an action does, running pipelines, versions and a "Runs" view, undo, resizing stages by hand,
multi-select, pinch zoom, and syncing the editor between tabs.

Edges that go forward are smooth curves. An edge that has to go back (a loop into the node's own
input, or to a node further left) leaves to the right, runs below both nodes and returns from the
left with rounded corners, so it never cuts across a node (`edgePath` in `geometry.js`).

### 2.13 Line style and routing

An edge has a `style` (`curved`, `straight`, `elbow`), chosen in the inspector and stored per edge (migration 0010, `PATCH .../edges/{id}`). Connections that go backward or have less than 48 units of horizontal room are routed below both nodes with rounded corners (sharp for `straight`) instead of bending sharply.

### 2.14 Action definitions

The definition of what an action does is edited on the same canvas, reached through the navigation entry "Actions" (`/actions`). It is a `graphs` row of `kind = action` (migration 0011), so storage and editor are shared; the API is the same under `/api/actions` as under `/api/pipelines`, and a graph asked for under the wrong kind answers 404. An action definition always has an automatic **trigger** in front and an **output** node (kind `output`, input `in`) at the end; both are created with it and cannot be deleted or added. The output has a connector of its own for each outcome: an input *On Pass* (`pass`, always) and an input *On Fail* (`fail`, only while `fail_enabled`, switched with an On/Off switch in the inspector of the output node, because not every business logic has a failure case). The logic to come routes successful runs to one and failed runs to the other; the default connection leads from the trigger to On Pass. Switching On Fail off removes the connection into it (migration 0015 renamed the former single input `in` to `pass`). Specialised nodes between trigger and output are planned; linking an action to a definition is described in §2.17.

### 2.15 Navigation: Pipeline and Actions

The sidebar has two entries: Board (called Projects until 2026-11-22) and **Pipeline** (own icon). Pipeline is a page of its own: the list of pipelines, each containing a trigger, stages and a complete. Only while the user is inside the Pipeline section (on a pipeline page or on Actions) does it show its one sub-entry **Actions** (`/actions`, the action definitions); on the Board it is not rendered. The user switches between Pipeline and Actions. The sidebar template marks the section (`nav-link--section`) when a child is current, and sets `aria-current="page"` only on the current entry. Inside the section, Pipeline and its sub-entries are outlined together as one group (`nav-section`), so the grouping also reads with the collapsed, icon-only sidebar. Arriving in the section from outside, the group's box fades in and grows downwards, then the sub-entries appear one after the other (about 1.4 s in total for two entries, at most about 0.75 s of staggering however many there are; an inline script before first paint compares with `sessionStorage`; switching inside the section does not replay it; skipped with `prefers-reduced-motion`).

### 2.16 Trigger and complete are fixed

Every pipeline has exactly one trigger and one complete, created with it and connected to each other by default (`trigger.out → complete.in`; a trigger may now feed a complete directly). They cannot be added or deleted through the API or the editor (the last of its kind stays; pipelines from before may hold several, migration 0012 adds a missing complete). The toolbar no longer offers nodes; a "+" menu at the top right of the canvas offers **Stage** (the only thing to add so far). A new stage is placed right of the last stage, and the complete moves further right when it would be in the way. Connecting a trigger or stage replaces the default edge, as every output has one edge.

### 2.17 Actions in a stage are shells linked to action definitions

An action created in a stage is an empty shell. Selecting it offers, instead of routing selects, a choice of an existing action definition or a new one by name. A link is `graph_nodes.definition_id` (migration 0013, `ON DELETE SET NULL`: deleting the definition makes the action a shell again). The node API returns `definition_name` and `definition_fail_enabled` for linked actions; the canvas shows the definition's name, so a rename in Actions shows in Stages. The inspector of a shell shows the definition choice and one compact row **New · Edit · Delete** (icon and short text; Edit is disabled until a definition is linked; Delete removes the action from the stage, not the definition). *New* opens a small window over the blurred canvas asking for the title; on *Create* the definition is created, the shell linked, and the editor opens `/actions/{id}?from=<pipeline>&node=<action>`, where a "Back to ..." link returns to `/pipelines/{slug}?select=<action>` with the shell selected. The editor stores the last stage and action in `localStorage` (`oa-last-pipeline`) and `main.js` points the navigation's Stages/Pipeline links there; a vanished pipeline clears it.

The definition's *On Fail* controls the shell's Error output: without it the port is hidden and Pass moves to the middle of the node (the edge follows; linking a definition with On Fail moves both back), existing Error connections are removed when On Fail is switched off or the link is made, and the API refuses a new one. Unlinked shells show both outputs. Connecting actions is done by dragging only; the routing selects remain for trigger and stages as the keyboard path.

### 2.18 Readable URLs

Pages are addressed by name, not id: `/pipelines/test`, `/actions/gap-analysis`. `graphs.slug` (migration 0014) is derived from the name (lower-case ASCII, umlauts transliterated), unique per kind with `-2`, `-3` ... on collisions, and follows a rename (the editor replaces the URL after renaming). The API keeps ids (`/api/pipelines/{id}`, `/api/actions/{id}`). The earliest page URLs, from before the vocabulary was settled, were removed without redirects, on purpose: the project is pre-release. `from`, `select` and the remembered pipeline (`oa-last-pipeline`) use the slug, so a rename elsewhere can leave a stale link that the editor reports as not found.

### 2.19 The timer: first logic in an action definition

An action definition can hold **timer** nodes (migration 0016, `graph_nodes.seconds`, 1 s to one day, default 5 s), added through the "+" menu at the top right of the action canvas like stages in a pipeline. A timer has an input `in` and an output `out`, so a definition reads trigger → timer → output (On Pass). The caption of a timer always shows its seconds; a new timer is placed right of the last one and the output moves on if it is in the way. Executing the nodes is the job of the execution engine (see ADR-013); until then a timer is only defined.

### 2.20 Names are edited in place

There is no "Name" field in the inspector. The title of the inspector and the page title (top left) are renamed by clicking them: a text field with a check and a cross appears; Enter or the check saves, Escape or the cross discards (`js/components/inline-name.js`). An action shell is named by its definition and is not renamed here. A caption that repeats the title (for example "Output" under "Output") is left out, and the *On Fail* switch sits in one row with its label.

### 2.21 Routing selects removed

The inspector no longer offers the routing select ("Next", "On Pass" ...) on any kind; connections are made by dragging. The code was first kept in quarantine (ADR-014 §3.6) and has since been removed. The inspector, the ports and the "+" menu now come from the node kinds (ADR-014 §3.1, §3.2).

## 3. Consequences

- **Easier:** new node kinds or ports need an entry in the rules, the port tables and the canvas;
  the graph shape does not change.
- **Limitation:** a stage only grows, never shrinks; edges are routed only for loops and backward
  connections, so other lines can still cross nodes or each other.
- **Risk:** large graphs re-draw all edges on every pointer move; fine for tens of nodes.

## Update (2026-11-22): connections, editor modules

The history above is kept; what changed afterwards.

- The routing select is gone ([ADR-014](014-building-blocks-and-extension-points.md)), so **connections are made by
  dragging only**. The keyboard alternative that §2.3 and §2.21 once described does not exist; this is a known
  limitation (arc42 chapter 11), a later goal, see [ADR-030](030-accessibility-scope.md).
- The graph editor's CSS classes use the prefix `ge-` (`ge-node`, `ge-port`, `ge-inspector`), no longer `wf-`
  ([ADR-015](015-vocabulary-and-storage-names.md)). The editor is split into modules: `editor.js` (orchestrator),
  `graph-model.js`, `inspector-panel.js`, `inspector.js` (blocks), `add-menu.js`, `navigation.js`, `geometry.js`.
- The "+" menu is a plain disclosure list, not an ARIA menu.
- Timers, Code nodes and HTTP nodes are executed by the engine through registered executors
  ([ADR-021](021-execution-nodes-as-executors.md)); the sentence in §2.19 that a timer "is only defined until
  then" is outdated. Node settings beyond the timer's live in a JSON `config`
  ([ADR-022](022-node-settings-as-json-config.md)). The missing keyboard way to connect nodes is a scope decision
  in [ADR-030](030-accessibility-scope.md).

## Addendum (2026-11-24): straight lines and resizing

The three attachment points of a stage side no longer sit at fixed heights (header, middle, bottom) and do not follow its
actions either (a first version let the last point follow the lowest action, which left no point near the bottom edge
when that action sat high): they follow the stage's **height**. The first point is level with the port of an action at the
very top: the highest row an action can sit in, which is also where a new action goes and where the drag stops
(`FIRST_ROW`, one number for the three, `clampInStage`); it is fixed, whatever the other actions do; the last one is level with the port of an action dragged as
low as it goes without the stage growing (stage height minus the padding minus the action's height); the middle one is
halfway. On the left they face the actions' input, on the right their On Pass. A line from a point to an action in the
very top or at the very bottom is therefore horizontal, and resizing the stage moves the lower points with its edge. A
node dragged in the editor settles level with a connected port or with one of its stage's points (the connected one
first when two are equally near) within 8 screen pixels (Alt switches it off), and a stage can be resized with grips on
its right edge, bottom edge and corner down to the size its actions need (`minStageSize`). A level connection with little
room is drawn straight instead of being routed around the nodes. The stored data does not change: an edge keeps its slot,
the heights are computed.

## Addendum (2026-11-24, later): outer and inner border, one band

A stage has an outer border (its edge) and an inner border, the limit of its actions, the same distance from the edge on
all four sides: `STAGE_MARGIN`, the header plus `FIRST_ROW` (56 px), which is the distance from a stage's top edge to an
action in the first row; it is one number derived from those two, not a second value. `clampInStage` stops an action
at the inner border on the left and at the top; right and below the stage grows with it (`fitStage`), so the band stays
there too. `minStageSize` (the floor of both grips and of the double click) is the actions plus the band to the right
and below (before: 24 below and right, 12 on the left, and not the same for the two grips). The bottom attachment point
is level with an action at the bottom of the inner border (stage height minus the band minus the action's height); the top and
middle ones are unchanged. A connection that loops back between two actions of one stage keeps `DETOUR` plus its corner
inside the band (`DETOUR + CORNER <= STAGE_MARGIN`, a test holds it) and is clamped to the stage's box, so it never
crosses the outer border and never runs over an action. The inner border is drawn only while an action or a grip is dragged,
as a faint dashed line. Stored positions do not change: a stage saved earlier may have an action closer to an edge; the
limit applies when it is dragged, placed or resized.
