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
| Stage | in, out; inner: entry, exit | An isolated container of actions. Stages connect to other stages through `in`/`out`. Its actions connect to the stage through `entry` (start) and `exit` (end). |
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

## 3. Consequences

- **Easier:** new node kinds or ports need an entry in the rules, the port tables and the canvas;
  the graph shape does not change.
- **Limitation:** a stage only grows, never shrinks, and edges are plain curves without routing
  around nodes, so crossing lines are possible.
- **Risk:** large graphs re-draw all edges on every pointer move; fine for tens of nodes.
