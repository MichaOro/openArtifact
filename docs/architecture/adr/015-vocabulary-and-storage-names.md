# ADR-015: Vocabulary and storage names

**Status:** Accepted  
**Date:** 2026-11-21  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-012](012-workflow-definition-editor.md), [ADR-013](013-execution-engine-and-runs.md)  
**Amended by:** [ADR-016](016-access-protection-integration-api-and-mcp.md) (resolves §6)

## 1. Title

One vocabulary for the product, and one neutral name for how definitions are stored.

## 2. Context

The editor and the engine grew under the working name "workflow" (ADR-012), while the interface
said "pipeline" and "action". The word "workflow" was therefore a second name for the same thing
in code, API, tables and documents. The product has no workflows: it has pipelines, and
pipelines are made of stages, which are made of actions, which are defined by execution nodes.

## 3. Decision Drivers

- The same word in the interface, the API, the code, the tables and the documents.
- A pipeline and an action definition are built from the same nodes and connections and edited on
  the same canvas, so storage and editor stay shared.
- Pre-release: renaming is cheaper now than after the first outside user.

## 4. Considered Options

### Option A: keep "workflow" in code and API, "pipeline" in the UI

No work, but two words for one thing; rejected.

### Option B: rename everything to "pipeline"

An action definition is not a pipeline, so the storage table would be misnamed.

### Option C: product vocabulary plus a neutral storage term

Chosen.

## 5. Decision

### 5.1 Vocabulary

**Pipeline** (what an artifact runs through) → **Stage** → **Action** (a step in a stage) →
**execution nodes** (trigger, timer, output ... the logic inside an **action definition**). A
**pipeline node** calls another pipeline. A **run** carries one artifact through a pipeline.
"Workflow" is not a concept of the product.

### 5.2 Storage: graph

Pipelines and action definitions are both stored as a **graph** (nodes and connections); "graph"
is only the storage term and is not shown to users.

| Before (migration 0008-0019) | Now (migration 0020) |
|------------------------------|----------------------|
| `workflows` | `graphs` (`kind` is `pipeline` or `action`; was `workflow` or `action`) |
| `workflow_nodes`, `workflow_edges` | `graph_nodes`, `graph_edges` |
| `workflow_nodes.workflow_id`, `workflow_edges.workflow_id` | `graph_id` |
| `pipeline_runs.workflow_id` | `pipeline_id` (the pipeline the run started in) |

Constraints and indexes are renamed with their tables. `definition_id` and all other columns are
unchanged. Stored run snapshots keep their keys. The migration is reversible and keeps all rows,
ids, foreign keys and edges.

### 5.3 Code and API

- Python: package `openartifact/graph/`, models `Graph`, `GraphNode`, `GraphEdge`,
  `GraphRepository`, schemas `Graph*`.
- Routes: `api/graphs.py` has a factory `build_graph_router(kind)`; `/api/pipelines` and
  `/api/actions` have the same sub-resources (`nodes`, `edges`), `/stages` only for pipelines. A
  graph under the wrong kind answers 404. The node kinds are at `/api/node-types`.
- The detail of a graph answers `{graph, nodes, edges}`. A run starts with
  `{pipeline_id, stage_id, action_id}`; a run reports `pipeline_id` (where it is now) and
  `root_pipeline_id` (where it started).
- Browser: `js/editor/`, `css/editor.css`, templates `graph_list.html` and `graph_editor.html`,
  `data-graph-id`. The class prefix was `wf-` at first; it is now `ge-` (graph editor, e.g. `ge-node`, `ge-port`,
  `ge-inspector`, `data-ge-list`); `editor.css` keeps its name.
- `/api/v1/*` paths and the MCP tools keep their names.

## 6. Consequences

- **Easier:** one word everywhere; a new graph kind needs one registry entry and a router.
- **Cost:** old ADRs and revisions 0008-0019 still say "workflow"; ADR-012 keeps its file name and
  carries a note. Local databases need `alembic upgrade head`.
- **Not decided here** (resolved by [ADR-016](016-access-protection-integration-api-and-mcp.md) §3.4): whether the
  browser API (`/api/pipelines`, `/api/actions`, `/api/tasks`) should require the API token as `/api/v1` and
  `/mcp` do. It does, once a token is configured.
