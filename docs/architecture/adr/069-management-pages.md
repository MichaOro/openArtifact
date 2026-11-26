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

## 7. Addendum (2026-11-26): two toolbar rows with tabs, no picture on the cards

- **The toolbar of a page with tabs has two rows.** Row one is search, order, "Per page" and cards or list and never changes; row two (only with
  tabs) holds the tabs and the filter, so that search and order stay where they are while the tabs are clicked through (Actions: Pipeline
  actions, Guard actions). A page without tabs has one row: search, order, filter (Pipelines), then the group at the right end.
- **A card has no picture of its graph.** The picture made the grid restless and turned vertical on a small screen for a long graph, which looked
  odd. The graph is shown in the panel only (tab *Graph*, `GraphPreview`, horizontal or vertical by the room it has). A card shows the name, the
  chips, the description when one is kept, the number of nodes and the date of the change; the grid is denser (cards from 15 rem).
  `lazyPreview` is not used any more and is in `quarantine.json` (14 days) in case a page wants a picture again.

## 8. Addendum (2026-11-26): the Versions tab of pipelines and actions is built

Pipelines and actions have versions ([ADR-070](070-versions-of-actions-and-pipelines.md)): the *Versions* tab is no longer greyed. It is
`static/js/editor/versions-tab.js` (a page's own tab, the frame knows nothing of it): *Publish* on top, the versions newest first with
*In use*, *Show* (the *Graph* tab shows that version read-only; the page sets `page.panelTab = "graph"` and calls `refreshPanel()`) and
*Publish again*; the chip of the card and of the panel is `publicationChip` (*Draft*, *v3 published*, *Draft has changes*). A tab that is not
built is still `disabled: true`.

## 9. Addendum (2026-11-26): one size for every card, the mark of the editor

- **A card has one size** on all four pages (Actions, Pipelines, Agents, Guards): **19 rem wide and 13 rem high (11 rem since §10)** (`--mg-card-w`, `--mg-card-h` on
  `.mg`). The grid is `repeat(auto-fill, 19rem)` and never stretches a card: it starts a new row only when the room beside the panel no longer holds
  another card. 19 rem is the width in which a title, the chips of a guard ("On entered", "Run the guard's action") and a line of facts stand without
  being squeezed, and two cards stand beside each other in the two thirds that remain next to the panel on a 1440 px screen; 13 rem is the height
  in which the parts below fit *at their maximum*: a title of two lines, a text of two lines, two rows of chips and two lines of facts. A card that
  holds less keeps the same size (the free room is in the middle), so no row has two heights.
- **The arrangement is one function**, `cardBody({title, text, chips, facts})` of `management-page.js`, which the four pages use instead of
  building their own: the title on top (up to two lines, then an ellipsis, and never under the pencil and the bin: it has their room reserved), the text
  in the middle (up to two lines; there is no element when there is no text: an agent without a description shows nothing there, a guard shows its condition
  in words), at the bottom, flush to the edge, the chips and the facts. In rows the same parts stand in one line. The day of the change, not the time,
  stands on a card (the panel has both).
- **The mark in the editor.** The toolbar of the pipeline and the action editor shows, right beside "All pipelines" / "All actions", the same chip as the
  pages: **Draft** while nothing is published or the draft differs from the published version, **v3 published** while they are equal (`editorChip` in
  `versions-tab.js`; its tooltip says what executions run). It follows every change the server accepts (`GraphModel.onChange`, asked again 250 ms later)
  and asks again when the tab gets the focus back, because a publication happens on the management page. Guards have no versions and no mark.

## 10. Addendum (2026-11-26): the card is 19 rem by 11 rem

- **The height of the card is 11 rem** (`--mg-card-h`), not 13 rem. The owner drew his wish into a screenshot of the Agents page; measured at the first card
  (width 273 px in both pictures = 19 rem at a browser zoom of about 90 %, height 185 px = 13 rem before and 157 px = 11 rem in his draft) the height of the draft is
  11 rem. The width stays 19 rem.
- **The arrangement under the title is tighter** and the big empty block between the text and the chips is gone: title (two lines, then "…"), text (two lines, then
  "…"), a short space, **one row of chips** (it never wraps: a chip that does not fit is cut with an ellipsis), a short space, **one line of additional facts**
  where there are some (the engine and the use of an agent, the nodes of an action or a pipeline, where a guard is used) and, alone on the last line, **the date**
  (`cardBody({title, text, chips, facts, date})`; a guard has no date). Title 0.9375 rem, text 0.8125 rem, facts and date 0.75 rem; the free room of a card that
  holds less is between the text and the chips. All four pages measure 19 rem by 11 rem (`tests/e2e/test_uniform_cards.py`) and nothing runs out of a card.

## 11. Addendum (2026-11-26): the picture of the Graph tab draws every connection and the stages
The first picture (§1) laid the nodes in a grid and drew one line from the middle of a column to the next: the connections of a pipeline were
wrong and its stages were not there. It is now drawn from the graph as the API gives it (`GET /api/pipelines|actions/{id}` or one version):
- **Layers from the connections** (`preview-layout.js`, `sceneOfGraph` and `layoutScene`, no DOM): the longest way to a node, connections that lead
  back (a retry, a loop; found by a walk from the nodes nothing leads to) left out; the order inside a layer follows the editor's y.
- **Every connection once**, in the colours of the editor's lines: a pass green, an error red and dashed, a tool dashed grey, the others neutral.
  A connection to the next layer is a curve in the gap; one that skips layers runs in a channel above the nodes, one that leads back in a channel
  below them; the channels use the gaps between the layers, so a line crosses no node it does not belong to (a unit test and a browser test
  measure it on the owner's pipeline: trigger, three stages of three actions with retries, the end).
- **A stage is a frame** around its actions (small symbol, the name as tooltip and in the description of the picture), laid out by the stage's own
  connections; the lines to the stage start and end at the middle of its two sides, the lines to the first and from the last actions start there.
- **Too narrow for a row:** the whole picture turns (layers one below the other), frames and channels with it.
- `structureOfGraph`, `structureOfChain` and `layoutPreview` are replaced by `sceneOfGraph` and `layoutScene`; the panel loads the graph itself
  (the stage chain `/stages` is no longer needed for the picture, the versions' `nodes` and `edges` serve the same way).


## 12. Addendum (2026-11-26): the page size follows the room

Before, "Per page" offered 12, 24 and 48 whatever the screen was, so a large screen showed one block of cards, empty room below it and a pager.
The page size now comes from the room of the list (`components/management-page.js`, the maths in `components/page-size.js`, no DOM there).

- **The base is what fits.** The card has a fixed size (19 rem by 11 rem, §10) and the gap is known, so the count is exact: columns = whole cards that
  fit the width of the list, rows = whole rows that fit the height from the top of the list down to the bottom of the area that scrolls (less the pager
  and the padding below); base = columns times rows. A half row is never drawn. The size of a card is read from the page (a hidden probe with
  `--mg-card-w` and `--mg-card-h`), not guessed. The room of the panel is reserved (§6), so the width does not change when an entry is selected.
- **Never fewer than 12.** A phone has one column and loads 12 (the page scrolls); an area that cannot be measured (hidden, no size) gives 12.
- **The "Per page" choices are steps of the base:** the base, twice and four times the base (18, 36 and 72; 24, 48 and 96; 12, 24 and 48 on a phone).
  The default is the base. No choice is larger than 500, the most the server gives in one request (the lists of the pages are cut in the browser; the
  archive reads up to 500 cards, ADR-071): a base of 300 offers 300 and 500, a clamped size appears once.
- **The browser remembers the step, not the number.** `localStorage` key `oa-management-<page>` holds `{view, sort, step}` with `step` 1, 2 or 4, per kind of
  page, no setting on the server. A value stored before (a number of entries as `size`) is not a step and the first step is used. A step that has no
  choice of its own any more (a base at the maximum) moves to the largest choice there is.
- **The list view** (rows) uses the same rule with the height of its rows (the first row is measured; 56 px until there is one; one column) and the same
  minimum of 12. The rows are measured after they are drawn and the base is corrected once if that changes the page size.
- **Window and turned screens:** the base is measured again 150 ms after the size of the page or the window changed, and the page is drawn again only when
  the size of a page really changed (no refetch: the pages hold their list in the browser). The first entry on the screen stays on the page: the new page is
  the one that holds the entry that was first before.
- **With twice or four times the base the page scrolls**; the pager sticks to the lower edge of the area (`position: sticky`), so "Next" is always in reach.
- **Everything is in `ManagementPage`**: Actions, Pipelines, Agents, Guards and the archive of the board get it; no page passes a number of entries
  any more (the option `pageSizes` is gone). The component sets `data-base` and `data-size` on its root, which the tests read.
