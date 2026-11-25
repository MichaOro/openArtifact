# ADR-069: Management pages

**Status:** Accepted  
**Date:** 2026-11-25  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-059](059-one-catalog-of-ui-building-blocks.md) (components), [ADR-065](065-every-window-is-a-form-manifest.md) (the windows of the lists are manifests)  
**Implemented in:** `static/js/components/management-page.js`, `graph-preview.js`, `preview-layout.js`, `static/css/management.css`, `static/js/editor/list.js` (pipelines and actions), `templates/graph_list.html`, migration `0056`, `api/graphs.py` (`/uses`, `q`, `tag`), `ui/forms/action.yaml`, `ui/forms/pipeline.yaml`  
**Affected chapters:** guides [UI catalog](../../guides/ui-catalog.md), [extending](../../guides/extending.md)

## 1. Context

The pages that manage the definitions (pipelines, actions, agents, guards) were four lists of one line each, built four times. They said
little (a name and a date), a click opened the editor at once, and what an entry is used by was not visible. The owner took a mock as
inspiration (cards with a small picture of the graph, a detail panel with tabs on the right) and set the way the pages are used.

## 2. Decision

**One way to use every management page** (binding for the four pages):
- A single click **selects** an entry and shows its details in the panel on the right. A **double click** opens it in its editor. The
  **pencil** on the card opens it too. The **bin** deletes it, after the question the page asked before. Keys: the arrows select, Home and
  End, **Enter** opens, **Delete** deletes (with the question). Everything the pages could do stays.
- The toolbar: tabs (where the entries are of two kinds: the actions for pipelines and the ones for guards), search, a filter by tag,
  the order, **cards or list** (kept per page for the next visit). Below the list: the range and the page size.
- The panel has tabs: *Overview*, *Graph*, *Versions*, *Usage*. A tab that is not built (*Versions* of pipelines and actions, until
  they have versions) is shown **greyed**, nothing more. The name, type, description and tags are changed in a window (*Properties*),
  a form manifest (ADR-065), not in the panel.
- On a narrow screen the panel is a **sheet** that rises from the bottom (the mobile web app); the page behind it is dimmed.

**One component for the frame** (`ManagementPage`): the toolbar, the list in two views, the selection, the keys, the paging and the panel
with its tabs. A page hands it the entries and says what a card and each tab of the panel show; the component never knows what a pipeline
is. The two later pages (agents, guards) use it the same way.

**One component for the picture of a graph** (`GraphPreview` with `layoutPreview`): the layout comes from the **structure** of the graph (what
follows what; tools hang below their agent with a dashed line), not from the coordinates of the editor, so it can be turned: a **row**
of columns while it stays legible (a row that would shrink below 60% of its size is turned), otherwise a **column**. Only symbols in the
colour of their kind (the manifests' `ui.color`); the name is the tooltip and the accessible name. It is drawn when its card comes into
view and kept while the graph has not changed.

**Description and tags** for pipelines and actions (migration `0056`): `graphs.description` and `graphs.tags`. The list API carries them with
the number of nodes and searches by text (`q`: name, description or a tag) and by `tag`; `GET .../{id}/uses` says where a definition is
used (an action: the stages of pipelines and the guards that run it; a pipeline: pipelines that call it, guards attached to it, how many
artifacts start in it and how many runs it had).

## 3. Consequences

- A new management page is a page script that builds a `ManagementPage` and a manifest for its window, not four hundred lines of layout.
- The Usage tab covers card OPT 15 (*where an action is used*, with a jump to the place) for actions and pipelines. What is not there: to
  clean up uses from the tab (the editor does it), and uses by artifacts as a list (only the count).
- The tab *Versions* is a place held. The version model of pipelines and actions (a draft, published versions, a stage that follows the
  published one) is a decision of its own.
- The migration number `0055` is reserved for the event log (card #100); `0056` follows `0054` until that one exists, then its
  `down_revision` becomes `0055`.

## 4. Addendum (2026-11-26): the agents page

The agents page (`static/js/agents/list-page.js`, `templates/agents.html`) is a `ManagementPage`. It is about the *definition* of an agent, not
about where it is used. The card says the name, the chips (active, published version, "Draft has changes"), the first sentence of the user
prompt, the provider and model the agent sets itself and how many nodes use it. The panel has two tabs:

- **Overview**: the **user prompt** and, only while it is in effect, the **system prompt** (a `ClampedText`: its first lines, *Show more*,
  *Copy*; `textContent` only), the status, the provider and the model (when the agent's own limits are in effect), the limits it sets
  (`limitRows` in `agents/model.js`), the description, *Open* and *Properties*. The published configuration is what runs and what the panel
  shows; when the draft differs a *Published | Draft* switch shows the draft's prompts.
- **Versions**: the published versions (number, date, "repeats vN" for a rollback, which one is current). Publishing and rolling back stay
  in the editor (one button leads there), so nothing about versions changed.

The list API (`GET /api/agents`) now says what the page needs without loading each agent: `user_prompt_start`, `system_prompt_enabled`,
`provider_id`, `model` and `shown_from` (``published`` or ``draft`` while nothing is published). The prompts themselves come from
`GET /api/agents/{id}` when an agent is selected. An agent that a node refers to cannot be deleted: the bin is disabled and says why
(`deleteBlocked` of the frame, optional). The window that makes or changes an agent is the form manifest `ui/forms/agent.yaml` (name,
description); the handmade `name-modal` of the list is gone (the editor page keeps its own rename window).

## 5. Addendum (2026-11-26): the Guards page

The Guards page (ADR-060) is the third page on the frame: cards or rows, search and order (by name, by use), the detail panel with **Overview**,
**Usage** and **Preview** (no *Versions*: a guard has none, and no place is held for it). A double click, the pencil and Enter open the guard
editor; the bin and Delete ask as before and a used guard says why it stays. The sentences are the guard editor's (`guards/model.js`:
`summaryLine`, `triggerText`, `previewText`, `escalationText`), not a second implementation. A used guard uses the frame's `deleteBlocked(item)`
(its bin is disabled and says why) and the new optional `onBlocked(item, reason)`: a click on such a bin shows the reason as a banner, as the
page did before; pages that do not set it behave as before.

## 6. Addendum (2026-11-26): the room of the panel, the page size in the toolbar

The owner's remarks on the pages as built (cards jumped when an entry was selected; the page size sat under the entries):

- **The room of the panel is always reserved** on a screen wide enough for it to stand beside the entries: two thirds of the width for the entries,
  one third for the panel (`grid-template-columns: 2fr 1fr`), whether or not an entry is selected. Without a selection the panel holds
  one quiet line that names the page (`panel.placeholder`, "Select an agent to see its details"; a dashed outline, no heavy box). The
  first card keeps its position and width when one is selected and when the panel is closed (an e2e test measures it on all four pages).
  The close button of the panel empties the selection; the room stays. A narrow screen is unchanged: the panel is a sheet from the bottom
  and there is no reserved room.
- **The page size is part of the toolbar**: "Per page [12] [cards][list]" is one group at the right end of the toolbar (it wraps as a whole);
  the pager under the entries keeps the range ("1–3 of 3") and the pages.
- **The card of an agent says its description**, when one is kept, and nothing otherwise (the prompt is in the panel).

## 7. Addendum (2026-11-25): the Versions tab of pipelines and actions is built

Pipelines and actions have versions ([ADR-070](070-versions-of-actions-and-pipelines.md)): the *Versions* tab is no longer greyed. It is
`static/js/editor/versions-tab.js` (a page's own tab, the frame knows nothing of it): *Publish* on top, the versions newest first with
*In use*, *Show* (the *Graph* tab shows that version read-only; the page sets `page.panelTab = "graph"` and calls `refreshPanel()`) and
*Publish again*; the chip of the card and of the panel is `publicationChip` (*Draft*, *v3 published*, *Draft has changes*). A tab that is not
built is still `disabled: true`.
