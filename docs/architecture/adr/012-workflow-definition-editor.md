# ADR-012: Workflow definitions as a graph, edited on a canvas

**Status:** Accepted  
**Date:** 2026-11-21  
**Supersedes:** —  
**Superseded by:** —

## 1. Context

Artifacts are meant to pass through workflows. A workflow is defined visually, without tables or
forms, in the spirit of n8n: boxes and lines that can be dragged around. The first stage only
defines the structure (stages, actions and how they connect); what an action does inside is
defined later in a separate interface.

## 2. Decisions

### 2.1 Model

A workflow is a graph of **nodes** and **edges** between their **ports**.

| Node | Ports | Meaning |
|------|-------|---------|
| Trigger | out | Start of the workflow (placeholder; manual, webhook or event later). Every workflow starts with one. |
| Stage | start, end | An isolated container of actions. Each port serves both sides: `start` receives from the trigger or a previous stage and feeds the first action; `end` receives from the stage's actions and leads on to the next stage or an ending. Which side an edge is on follows from its other end (migration 0009 merged the former `in`/`entry` and `out`/`exit`). Each side offers three attachment points (slots 0–2, top to bottom); an edge stores its slot per end (migration 0010), and only used points are shown unless the stage is hovered, selected or a connection is being drawn. |
| Action | in, pass, error | A business execution, a container for now. Connects only to actions of its own stage or to its stage's `exit`. `error` may also go to its own input. |
| Complete | in | Ends the workflow; stands outside any stage. |

There are no fixed "Completed" or "Needs Attention" nodes: a human-in-the-loop step is just an
action. An output has at most one edge (connecting again replaces it); an input accepts many.
Unconnected outputs are allowed. The rules live in `workflow/rules.py` and are enforced by the
server (422); the editor mirrors them only to offer valid targets.

### 2.2 Persistence

Tables `workflows`, `workflow_nodes` and `workflow_edges` (migration 0008) with real foreign keys
and `ON DELETE CASCADE`: deleting a stage removes its actions and every edge touching them. An
action's position is relative to its stage's body; stages store their size. Every change is saved
immediately through `/api/workflows/...`; there is no separate save step and no live sync between
tabs yet.

### 2.3 Editor

Server-rendered pages (`/workflows`, `/workflows/{id}`) with vanilla JS modules, no library and
no build step (ADR-010). Nodes are HTML elements (accessible, stylable with the tokens) inside a
transformed "world"; edges are SVG paths drawn over them. Pan, zoom, moving nodes and dragging from
a port to connect use Pointer Events, so mouse, touch and pen work alike. An action stays inside
its stage, which grows to contain it. The right-hand inspector edits the selected node and offers a
**Routing** select per output, which is the keyboard path to connecting; Enter on a focused node
opens it, arrows nudge, Delete removes.

### 2.4 Out of scope for now

What an action does, running workflows, versions and a "Runs" view, undo, resizing stages by hand,
multi-select, pinch zoom, and syncing the editor between tabs.

Edges that go forward are smooth curves. An edge that has to go back (a loop into the node's own
input, or to a node further left) leaves to the right, runs below both nodes and returns from the
left with rounded corners, so it never cuts across a node (`edgePath` in `graph.js`).

## 3. Consequences

- **Easier:** new node kinds or ports need an entry in the rules, the port tables and the canvas;
  the graph shape does not change.
- **Limitation:** a stage only grows, never shrinks; edges are routed only for loops and backward
  connections, so other lines can still cross nodes or each other.
- **Risk:** large graphs re-draw all edges on every pointer move; fine for tens of nodes.

## 2.13 Line style and routing

An edge has a `style` (`curved`, `straight`, `elbow`), chosen in the inspector and stored per edge (migration 0010, `PATCH .../edges/{id}`). Connections that go backward or have less than 48 units of horizontal room are routed below both nodes with rounded corners (sharp for `straight`) instead of bending sharply.

## 2.14 Action definitions

The definition of what an action does is edited on the same canvas, reached through the navigation entry "Actions" (`/actions`). It is a `workflows` row of `kind = action` (migration 0011), so storage, API and editor are shared; `GET /api/workflows` lists only workflows unless `?kind=action`. An action definition always has an automatic **trigger** in front and an **output** node (kind `output`, input `in`) at the end; both are created with it and cannot be deleted or added. The output always offers *On Pass*; *On Fail* is optional (`fail_enabled`, switched with a small button on the node or a checkbox in the inspector), because not every business logic has a failure case. Specialised nodes between trigger and output are planned; linking a workflow action to a definition is not built yet.

## 2.15 Navigation: Pipeline

The sidebar has two entries: Projects and **Pipeline** (own icon). Pipeline links to its first child. Only while the user is inside it (on Stages or Actions) does it show the sub-entries **Stages** (`/workflows`, the workflow list; "workflow" stays the name in code and API, as "task" does for artifacts) and **Actions** (`/actions`); on Projects they are not rendered. The sidebar template marks the section (`nav-link--section`) and sets `aria-current="page"` only on the current leaf. Inside the section, Pipeline and its sub-entries are outlined together as one group (`nav-section`), so the grouping also reads with the collapsed, icon-only sidebar, where the current sub-entry keeps the stronger highlight. Arriving in the section from outside it, the group's box fades in and grows downwards, then the sub-entries appear one after the other (about 1.4 s in total for two entries, at most about 0.75 s of staggering however many there are) (an inline script before first paint compares with `sessionStorage`; switching between Stages and Actions does not replay it; skipped with `prefers-reduced-motion`).
