# ADR-070: Versions of actions and pipelines

**Status:** Accepted  
**Date:** 2026-11-25  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-015](015-vocabulary-and-storage-names.md) (the names of graphs), [ADR-067](067-pipeline-actions-and-guard-actions.md) (guard actions), [ADR-069](069-management-pages.md) (the *Versions* tab)  
**Implemented in:** `models/graphs.py` (`GraphVersion`, `Graph.published_number`), `graph/content.py`, `graph/versions.py`, `graph/publishing.py`, `engine/snapshot.py`, `api/graphs.py`, migration `0057`, `static/js/editor/versions-tab.js`, `static/js/editor/publication-control.js` (addendum 1)  
**Affected chapters:** guides [agents](../../guides/agents.md) (the same words), [UI catalog](../../guides/ui-catalog.md)

## 1. Context

Pipelines and actions carried a chip *Draft* and nothing else: every change in the editor reached every pipeline that uses the
definition at once, and the next run. Agents already have a draft and published versions ([ADR-037](037-agent-harness.md)): only publishing changes what
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
- Not built: pinning a pipeline to a version of an action, comparing two versions. (Restoring a version into the draft: Addendum 1, as *Discard draft*; restoring an *earlier* version into the draft is still not built.)

## Addendum 1 (2026-11-26): publish and discard from the editor's toolbar

- **The mark is a control.** The mark beside the way back in the editor (*Draft*, *v3 published*) opens a small popup when there is something to do
  (`static/js/editor/publication-control.js`, the catalog class `ge-state`, the popup `pub-popover`):
  - *Draft* (nothing published): *Publish* only; there is no version to go back to.
  - *Draft* with changes (the draft differs from the published version): *Publish* and *Discard draft*.
  - *v3 published* (equal): nothing to do, so the mark stays a plain chip and no popup opens.
- **Publish** is the call of the Versions tab (`POST /{id}/publish`), as one click in the popup (the popup states what executions will run). **A refusal
  of the server** (409 when nothing changed meanwhile) is shown in the popup, which stays open; the buttons wait while a call runs. On success the popup
  closes and the editor reads the graph again, which draws the mark anew.
- **Discard draft** asks once inside the popup (*The changes since version N are lost*), then calls the new `POST /api/{pipelines|actions}/{id}/draft/discard`
  (`publishing.discard_draft`, `GraphRepository.restore`), which answers the graph as it is now; the editor reads it again, without reloading the page.
  409 while nothing is published and while the draft equals the published version.
- **What discard does.** The draft becomes the published version's graph: nodes that are in it stay the same rows (same id, so guards attached to them
  stay) and take its values, nodes that are not in it go (with the guards attached to them), nodes only the version has are made again, connections are
  replaced; a link to a definition that no longer exists is left empty. Nothing that executions run changes (they read the published version), and no version is
  made or removed. The error output is one state of an action definition and its uses (ADR-061 addendum): a definition whose *On Fail* changes is carried to its
  uses, and a restored use agrees with its definition afterwards, in the same transaction, exactly as an edit does; other graphs this reached are announced
  with `graph.changed`.
- **Unsaved edits.** The editor saves every change at once, so there is no unsaved graph. Text typed into a field and not left yet is saved first.
- The agent editor keeps its own header buttons (*Save draft*, *Discard draft*, *Publish*): it does not use this mark.

## Addendum 2 (2026-11-26): guards get the same

The guard library has a draft and published versions in the same words (*Draft*, *v3 published*, *Draft has changes*, *Publish*, *Publish again*, *Discard
draft*) and the same popup on the chip ([ADR-081](081-guard-versions.md)). One difference: a graph that was never published runs its draft, a guard that was never
published watches nothing.
