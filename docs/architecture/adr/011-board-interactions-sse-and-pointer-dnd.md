# ADR-011: Board interactions — SSE-driven UI and Pointer-Events drag & drop

**Status:** Accepted  
**Date:** 2026-11-20  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-009](009-technology-summary.md) (real-time updates)  
**Amended by:** —

## 1. Context

The board must support creating, deleting and moving cards (lane switch, including drag & drop),
and every change must show up in all open browser tabs. ADR-010 left two questions open: how
drag & drop works and how real-time updates are delivered.

## 2. Decisions

### 2.1 Real-time: Server-Sent Events, not WebSocket

- `GET /api/events` streams `task.created`, `task.updated`, `task.moved` (all three carry the full
  task) and `task.deleted` (`{"id": …}`). `PATCH /api/tasks/{id}` is a partial update: it publishes
  `task.moved` when only the lane changed, `task.updated` for any other change and nothing when
  nothing changed.
- Commands stay plain REST (`POST`, `PATCH`, `DELETE /api/tasks…`); the stream is one-way.
  SSE needs no extra protocol, passes proxies as ordinary HTTP and `EventSource` reconnects
  by itself. A WebSocket would only add a second command channel next to REST.
- An **in-process `EventBus`** fans events out to subscriber queues. Events are published only
  after the database commit, never for failed requests or no-ops.
- **No replay.** Events missed while disconnected are not stored. The client therefore reloads
  `GET /api/tasks` and reconciles on every (re)connect.
- A subscriber that stops reading (full queue) is dropped; the browser reconnects and resyncs.
- A comment heartbeat every 15 s keeps idle connections open. `uvicorn` runs with
  `--timeout-graceful-shutdown 3` so open streams cannot delay container shutdown.

### 2.2 The UI is event-driven and idempotent

All changes reach the board through two functions, `Board.upsert(task)` and `Board.remove(id)`,
whether they originate from the tab's own API response, an SSE event or an optimistic update.
Applying the same change twice is harmless, so the tab that caused a change and all other tabs
converge on the same state without special cases.

- Moves are **optimistic**: the card moves immediately, `PATCH` runs, and a failure restores the
  previous lane and shows an error (a `404` means "deleted elsewhere" and removes the card).
- Deleting asks for confirmation in a dialog (there is no undo); a `404` counts as success.
- **Editing:** clicking a card (or `Enter` on the focused card) opens the task dialog in edit mode,
  prefilled; saving sends only title/body. A click that ends a drag is swallowed so a drop never
  opens the editor. A `404` while saving means the task was deleted elsewhere; it is removed from
  the board. A half-typed *create* draft is parked while an edit is open and restored afterwards.

### 2.3 Drag & drop: Pointer Events (decides the open question of ADR-010)

- One code path for mouse, pen and touch; the drag visuals (ghost, faded placeholder, highlighted
  target lane) are fully under our control, which native HTML5 drag & drop does not offer on touch.
- Mouse/pen start after a few pixels of movement. **Touch: the card itself is the handle, there is
  no grip icon.** Users grab the card with the finger, they do not look for an anchor. Cards get
  `touch-action: pan-y`: a vertical swipe stays a native scroll of the lane, a **sideways swipe
  starts the drag at once** (cards move between lanes sideways), and a 250 ms press without
  movement also picks the card up. (A first long-press-only version looked broken on phones,
  because pressing and dragging immediately was read as a scroll; a visible grip was tried and
  dropped as undiscoverable.)
- Near the left/right board edge the board auto-scrolls (narrow layout); scroll snapping is
  switched off while dragging so it cannot fight the auto-scroll. Escape aborts.
- The controller only reports `(task, targetStatus)` and knows nothing about the API.
- **Keyboard alternative** (drag is pointer-only): focus a card, `Alt+←/→` moves it between lanes,
  `Delete` opens the delete dialog. Moves and deletions are announced in an `aria-live` region.

### 2.4 Ordering

Cards are ordered inside a lane by `tasks.position` (fractional, ascending; ties: newest first).
New cards start at the top. Dropping a card between two others stores the midpoint of their
positions, so only one row changes. `PATCH` takes `before_id` (place before that task, `null` = end
of the lane); a lane change without `before_id` lands at the top. When the gap between two
neighbours drops below 1e-6 the lane is renumbered and the server publishes `board.resync`, which
makes every client reload the list. While dragging, the original card moves live to its new place
(no extra indicator); Escape or a drop outside every lane restores it. Alt+↑/↓ reorders by keyboard.

### 2.5 Static asset caching

Assets are not fingerprinted. Without a cache policy browsers may reuse a stale script for a
while (heuristic freshness) and combine it with newer HTML, which breaks the UI after a
deployment. Static files are served with `Cache-Control: no-cache`, so every load revalidates via
ETag and normally costs a `304`.

### 2.6 Card navigation (task dialog)

The edit dialog has a right-hand rail, styled like the main navigation: collapsed (icon only) by
default, expandable to icon + label, state remembered in `localStorage`. It exists only for saved
tasks. **Fields** sit at the top (today: *Lane*, later e.g. stage and action of the artifact, in
the spirit of GitHub's project fields); **actions** (today: *Delete*) and the collapse toggle sit
at the bottom, the toggle in the same column as the item icons. On narrow screens the rail is a
fixed icon rail. Built from the reusable `CollapsibleNav` component.

Layout rules: icon left of the text (*icon | text*), the icon column sits right next to the form.
The form column keeps its width and **position** (`--form-w`); expanding the rail makes the card
grow **rightwards** (`--rail-w` is a registered, transitioned length; the panel is translated by
half the growth so its left edge stays put, limited so the right edge never leaves the viewport).
The labels fade in while the card widens. The toggle stays in the icon column, so the mouse can
stay where it is. On viewports too tight for the growth the card shifts left by just the missing
amount. The main sidebar follows the same
idea: its toggle is the first footer item, in the icon column, and does not move when the sidebar
expands or collapses.

### 2.7 Lane switch in the dialog, and lanes as configuration

- Clicking the lane chip under the dialog title ("In Backlog") unrolls the other lanes as coloured
  chips in a row *inside* the header; the form slides down to make room (no popup, so no edge to
  fade). The chip deliberately has no icon or caret (an easter egg). The Lane field of the rail uses a regular menu. The
  rail's *Lane* field opens the same menu. In edit mode the task moves immediately (optimistic,
  like drag & drop); in create mode the chip only changes the target lane.
- The menu (`LanePicker`) only receives `{status, title}` pairs. The board reads the lanes from
  the DOM, and the page renders them from the `lanes` table (`openartifact/tasks/lanes.py`); lanes are
  user-defined, see the update "lanes are rows" below.

### 2.8 Responsive layout

- The page is exactly one viewport tall; each lane scrolls internally.
- **Narrow** (≤ 960 px): lanes form a horizontal snap-scrolling board, the next lane peeks in.
- **Narrow landscape** (height ≤ 500 px): compact header, sidebar and lanes.
- **Main sidebar on narrow screens** (≤ 640 px wide, or ≤ 500 px high and ≤ 960 px wide): it always
  starts collapsed and collapses when the viewport becomes narrow. Expanding it there is temporary
  and not stored, so the desktop preference survives. An expanded sidebar **overlays** the board
  instead of taking width from the lanes; tapping outside or Escape closes it.

### 2.9 Lane colours

Tokens `--lane-hue-1 … --lane-hue-8` (own values per theme, in `tokens.css`). Lane N always uses hue
N (violet, amber, green, blue, pink, teal, orange, slate), cycling after eight. An element with
`data-lane-hue="N"` receives `--lane-color`; used for the lane dot, counter, lane chip and chips.

### 2.10 Parent / child artifacts

`tasks.parent_id` (migration 0005): an artifact has at most one parent and can be the parent of any
number of artifacts, which can in turn be parents (a tree). The rail's *Parent* field opens a picker
(*No parent* plus every artifact that is not the task itself or one of its descendants); the card
shows *Parent: …* and the number of sub-artifacts. The server rejects cycles with 422. Deleting a
parent **detaches** its children instead of deleting them (the delete dialog says so) and publishes
`board.resync`. The relation is a database foreign key since migration 0007 (§2.12); the repository
adds what SQL cannot express (cycle check). Moving a parent to another
lane does not move its children.

### 2.11 Artifact numbers and `#` references

`tasks.number` (migration 0006): every artifact gets a sequential number (#1, #2 …), unique and
**never reused**: it comes from a counter table (`task_number_seq`), not from `max(number)+1`, so
a `#12` written into another artifact never silently changes its meaning after a delete. Existing
artifacts were numbered oldest first. The number is read-only in the API (PATCH with `number` is a
422) and shown quietly (muted, small) left of the close button of the edit dialog.

In the body field, typing `#` (at the start or after whitespace) opens a small menu with the other
artifacts of the board (`ReferencePicker`); digits or title text filter it, Enter/Tab inserts
`#<number>`, Escape closes only the menu. Parent fields still show the **title**, not the number.

**Read and edit mode.** An existing artifact opens read-only (title, body, rail); *Edit* switches
the same dialog to the form, *Save* returns to the read view, *Cancel* discards. In the read view
`#12` is a link to that artifact (followed inside the dialog, with a *Back* button); a number that
does not exist is shown struck through. References are resolved when displaying, not validated on
save: a body may legitimately contain text like `#5` or `C#3`, and an artifact referenced later may
not exist yet. Rendering uses DOM nodes, never `innerHTML`.

### 2.12 Foreign key on `parent_id`

Migration 0007 rebuilds `tasks` (SQLite needs that for a new constraint) with
`parent_id REFERENCES tasks(id) ON DELETE SET NULL`; dangling references are cleared first. Every
connection enables `PRAGMA foreign_keys=ON`. The repository still rejects unknown parents and
cycles (the database cannot express acyclicity) and still detaches children explicitly so it can
report how many were affected; the constraint guarantees integrity for any other writer, and
queries or dashboards can rely on the relation.

## 3. Consequences

- **Easier:** consistent multi-tab behaviour with little code; no polling; no client framework.
- **Limitation:** the bus is process-local. With several worker processes a client would only see
  events published by its own worker. The container runs a single `uvicorn` process; scaling out
  needs a shared broker (e.g. Redis pub/sub) behind the same `EventBus` interface.
- **Limitation:** an event stream holds one connection per open tab.
- **Risk:** hand-written drag & drop needs browser/device testing (touch behaviour differs per
  OS). The behaviour is covered by Playwright browser tests (`apps/backend/tests/e2e/`, CI job `e2e`), including touch gestures via the DevTools protocol.

## Update (2026-11-22): the full event list

`GET /api/events` carries more than the `task.*` events of §2.1: `task.created`, `task.updated`, `task.moved`,
`task.deleted`, `run.updated` (a run, same schema as the REST run), `execution.updated` (`task_id` and the summary of
an execution, when it starts and when its status changes), `execution.deleted` (`task_id` and `id`) and
`board.resync` (the client should reload). The pages of the execution history use them ([ADR-025](025-execution-history-and-retention.md), [ADR-028](028-global-executions-page-and-keyset-paging.md)). The
board's keyboard operation and the known limits of the editor are in [ADR-030](030-accessibility-scope.md).


## Update (2026-11-22): lane titles are renamable (superseded by "lanes are rows" below)

The three lanes stay fixed (`backlog`, `in_progress`, `done`, the codes the API and MCP use); their **titles** can be changed by the
user. The table `lane_titles` (migration 0027) holds only the overrides, `BOARD_LANES` supplies the defaults and a lane without a row
shows its default. `GET /api/lanes` and `PUT /api/lanes/{status}` (mirrored on `/api/v1/lanes`, MCP tool `list_lanes`) read and change
them: titles are trimmed, 1 to 40 characters, free of control characters and unique among the lanes ignoring case (422 otherwise);
`null`, empty or the default text restores the default. A rename publishes `board.lanes` (`{"lanes": [...]}`); the other tabs update
headers, labels and an open dialog without a reload. Like every event it is not replayed, so the page reads `GET /api/lanes` again on
every (re)connect. The page renders the effective lanes on the server and the board JavaScript still reads the titles from the DOM. The
pencil in the lane header opens a one-field `FormDialog` with "Reset to default". The sidebar entry that was called Projects is called
**Board**.

## Update (2026-11-22): lanes are rows

The planned `lanes` table is implemented (migration 0029). A lane has a `key` (primary key, at most 32 characters, generated from the first
title as `[a-z][a-z0-9_]{0,31}` with a numeric suffix when taken, never changed: the three existing lanes keep `backlog`, `in_progress`,
`done`), a `title` (1 to 40 characters, unique ignoring case) and a `position`. `tasks.status` holds the key and references it (foreign key,
`ON DELETE RESTRICT`) instead of the `CHECK` constraint of migration 0003, so the database itself refuses an artifact in a lane that does
not exist and the deletion of a lane that still holds artifacts; the service turns that integrity error into `409` (a lane deleted while an
artifact moves in). `lane_titles` and `BOARD_LANES` are gone, and so is "reset to default".

Rules (`tasks/lanes.py`): at most 12 lanes, at least one; a new lane is appended; a lane can be deleted only when it holds no artifacts
(`409`, "A lane can only be deleted when it contains no artifacts.") and not as the last lane; titles are trimmed, free of control
characters and unique ignoring case (`422`). A new artifact without a lane goes to the first lane; an unknown key is `422` and lists the valid ones.
`GET/POST /api/lanes`, `PUT/DELETE /api/lanes/{status}` (mirrored on `/api/v1/lanes`; MCP `list_lanes` stays read only) answer the lane list
(`status`, `key`, `title`, `position`, `hue`, `artifact_count`, `deletable`); every change publishes `board.lanes`. A lane change never moves
an artifact, so no `task.*` event or resync follows.

The page renders the lanes from the table with the `lane()` macro and once more, empty, into `<template id="lane-template">`; `Board.setLanes`
clones that template for a lane that appears and removes one that disappears, so lanes come and go without a reload (drag and drop, the lane
picker and the dialog chips read the lanes from the board). Each lane header has the name (click to rename in place, `InlineName`, the same
component as the graph editor), the count, the plus and a menu button (`ActionMenu`: Rename, Delete; Delete is greyed out and explains why
while the lane holds artifacts). "Add lane" is in the page header and opens the shared `FormDialog`. With more than three lanes the board
scrolls sideways (lane width at least 17rem). Hues cycle by position (8 hues).
