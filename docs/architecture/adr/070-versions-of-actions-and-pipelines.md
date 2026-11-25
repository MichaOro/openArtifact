# ADR-070: Versions of actions and pipelines

**Status:** Accepted  
**Date:** 2026-11-25  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-015](015-graphs.md) (the graph model), [ADR-067](067-pipeline-actions-and-guard-actions.md) (guard actions), [ADR-069](069-management-pages.md) (the *Versions* tab)  
**Implemented in:** `models/graphs.py` (`GraphVersion`, `Graph.published_number`), `graph/content.py`, `graph/versions.py`, `graph/publishing.py`, `engine/snapshot.py`, `api/graphs.py`, migration `0057`, `static/js/editor/versions-tab.js`  
**Affected chapters:** guides [agents](../../guides/agents.md) (the same words), [UI catalog](../../guides/ui-catalog.md)

## 1. Context

Pipelines and actions carried a chip *Draft* and nothing else: every change in the editor reached every pipeline that uses the
definition at once, and the next run. Agents already have a draft and published versions (ADR-034): only publishing changes what
executions use. The owner wants the same for actions and pipelines, handled in the detail panel of the management page (ADR-069), not in
the graph editor.

## 2. Decision

- **The editor edits the draft**, as before: the nodes and edges of the graph. Nothing changes in the editor.
- **A version is a frozen copy of the graph** (`graph_versions`: the nodes with their settings, the edges, the name and kind, i.e. what
  `graph_of` returns; stages and their actions are nodes of a pipeline). Rows are written once and never changed. `number` counts per
  graph from 1 and is never reused. `source_number` is set when the version was made by publishing an earlier one again (a rollback): its
  content equals that version's. `published_via` is `user` or `api`. A `fingerprint` of the parts that decide what runs (not the
  position, size or label of a node) says whether the draft differs from the published version.
- **`Graph.published_number`** is the version executions use. *Publish* makes a new version of the draft and points to it. *Publish again*
  makes a new version with the content of an earlier one (history stays; the draft is not touched: it is shown as changed if it differs).
  Publishing an unchanged draft is refused (409): nothing would change.
- **Chip:** `Draft` (nothing published), `v3 published` (published and the draft equals it), `Draft has changes` (the draft differs from the
  published version); the API says `published_version` and `draft_changed` on every pipeline and action.
- **What runs (backward compatible):** while a definition has **no published version**, the current draft runs as before. From its first
  publication on, an execution uses the **published version**. The execution freezes its snapshot at the start as before
  (`engine/snapshot.py`); the only change is where the snapshot reads each graph from: the pipeline, the actions of its stages, the
  pipelines it calls and the guards' own actions are read through `graph_for_run` (the published content when there is one, else the
  draft). So a pipeline follows the **published** versions of its actions and an edit of an action reaches no run before it is published.
  The places that start an execution at a stage or an action (`engine/targets.py`, the artifact's start options) read the same way.
- **Purpose and use:** a guard action is versioned like any action. Changing the purpose of an action (ADR-067) also looks at the
  published version: it must not hold a node of a kind that is not for the new purpose. The usage of an action (and the question before
  it is deleted) also names the pipelines whose **published** version still uses it, marked with the version.
- **Deleting** a pipeline or an action deletes its versions (cascade).
- **API** (browser API under `/api/pipelines` and `/api/actions`; the integration API `/api/v1` and the MCP server carry no graph
  endpoints, so they get none): `GET /{id}/versions`, `GET /{id}/versions/{number}` (the frozen content: nodes and edges, for the
  *Show* of the panel), `POST /{id}/publish`, `POST /{id}/versions/{number}/republish`.
- **Panel:** the *Versions* tab (`versions-tab.js`): *Publish* on top (with a note when the draft equals the published version), the list
  newest first, *In use* at the published one, *repeats vN* at a rollback, *Show* (the *Graph* tab shows that version read-only, with a
  note which one it is and a way back to the draft) and *Publish again*; long lists fold their middle (`FoldList`, ADR-069 addendum).
  Publishing and publishing again ask first, like the agents.

## 3. Consequences

- Editing an action no longer changes pipelines that already published it: a safe way to work on a shared definition. The price is the
  second step (*Publish*); a definition that was never published keeps running its draft, so nothing changes for existing data.
- A published pipeline version names the actions it uses by id; deleting an action that a published pipeline version still uses leaves
  that action empty at the next run (as deleting an action used by a stage did before). The usage lists those pipelines to be cleaned up.
- Not built: pinning a pipeline to a version of an action, comparing two versions, restoring a version into the draft.
