# ADR-011: Board interactions — SSE-driven UI and Pointer-Events drag & drop

**Status:** Accepted  
**Date:** 2026-11-20  
**Supersedes:** —  
**Superseded by:** —

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

Layout rules: text sits left of the icon (*text | icon*), the icon column hugs the right edge. The
form column keeps its width (`--form-w`); expanding the rail makes the **card** grow leftwards
(`--rail-w` is a registered, transitioned length, the panel is translated by half the growth), so
the right edge and with it the toggle stay where the mouse is. The main sidebar follows the same
idea: its toggle is the first footer item, in the icon column, and does not move when the sidebar
expands or collapses.

### 2.7 Lane switch in the dialog, and lanes as configuration

- Clicking the lane chip under the dialog title ("In Backlog") unrolls the other lanes as coloured
  chips in a row *inside* the header; the form slides down to make room (no popup, so no edge to
  fade). The chip deliberately has no icon or caret (an easter egg). The Lane field of the rail uses a regular menu. The
  rail's *Lane* field opens the same menu. In edit mode the task moves immediately (optimistic,
  like drag & drop); in create mode the chip only changes the target lane.
- The menu (`LanePicker`) only receives `{status, title}` pairs. The board reads the lanes from
  the DOM, and the page renders them from `BOARD_LANES` (`openartifact/tasks/lanes.py`), the single
  definition of lanes, their order and titles.
- **Not implemented, architecture only:** user-defined lanes. They would replace `BOARD_LANES`
  with a `lanes` table and replace the `CHECK` constraint on `tasks.status` (migration 0003) with a
  foreign key. The frontend would need no change.

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
`board.resync`. There is no database foreign key (SQLite cannot add one to an existing table
without rebuilding it); the repository keeps the relation consistent. Moving a parent to another
lane does not move its children.

## 3. Consequences

- **Easier:** consistent multi-tab behaviour with little code; no polling; no client framework.
- **Limitation:** the bus is process-local. With several worker processes a client would only see
  events published by its own worker. The container runs a single `uvicorn` process; scaling out
  needs a shared broker (e.g. Redis pub/sub) behind the same `EventBus` interface.
- **Limitation:** an event stream holds one connection per open tab.
- **Risk:** hand-written drag & drop needs browser/device testing (touch behaviour differs per
  OS). The behaviour is covered by browser tests, not by unit tests.
