# ADR-092: The lanes can be put in a new order, in a mode of the board

**Status:** Accepted  
**Date:** 2026-11-27  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-011](011-board-interactions-sse-and-pointer-dnd.md) (the board's interactions: a mode in which only lanes move), [ADR-090](090-lane-ids-and-names.md) (the order is the lane's `position`)  
**Implemented in:** `tasks/lanes.py` (`reorder_lanes`), `tasks/service.py`, `api/lanes.py` and `api/v1.py` (`POST …/lanes/order`), `static/js/tasks/lane-order.js` and `lane-order-model.js`, `static/js/components/sortable.js` (the `axis` and `scroller` options), `static/js/tasks/board.js`, `main.js`, `dnd.js`, `templates/components/lane.html`  
**Affected chapters:** guides [concepts](../../guides/concepts.md), [API reference](../../guides/api-reference.md), [UI catalog](../../guides/ui-catalog.md)

## 1. Context

Lanes can be added, renamed and deleted, but not moved: their order was the order they were made in. The owner works on the board far more often than he
reorders it, so the board must not carry a permanent handle row, and dragging a card must not be confused with dragging a lane.

## 2. Decision

- **A mode, not a permanent handle.** The board's menu (next to *Add lane*) has *Reorganize lanes*; while the mode is on it reads *Stop reorganizing lanes*,
  the same toggle as *Show archive* / *Hide archive*. The mode is not stored (a reload ends it), Escape ends it, and showing the archive ends it.
- **The lanes slide down.** In the mode the board gets `padding-top` for one handle row (`--lane-strip`, 2.5 rem, a 0.18 s transition, none with
  `prefers-reduced-motion`) and every lane shows a centred pill handle (the grip icon, 3.5 × 1.75 rem) above its column. Off, the room is gone: no strip is
  left between the header row and the lanes (a test measures the lanes' top before, in and after the mode).
- **Only lanes move in the mode.** Card drag and drop and Alt+arrow card moves are off (`board.reordering`); cards still open on a click.
- **How a lane moves.** By its handle with the pointer: the shared `Sortable` now has `axis: "x"` (the pointer's X decides, the neighbour is passed beyond its
  middle) and `scroller` (the board scrolls sideways: a drag near the left or right edge scrolls it). By keyboard: the handle is a focusable button
  (`aria-label` *Move lane <name>*) and **ArrowLeft / ArrowRight on the focused handle** move the lane one place (the same plain arrow keys as every other
  `Sortable` list; cards use Alt+arrows because a card has other meanings for the plain keys). After each move the lane's handle keeps the focus and the live region
  says *<name> moved to position 3 of 6*.
- **Saved at once, with a route.** `POST /api/lanes/order` (and `POST /api/v1/lanes/order`) takes `{"lanes": [...]}`: every lane exactly once, each by title, id
  or old key (the resolver of ADR-090). `position` becomes 0 to n−1 in one commit, the answer is the lanes, `board.lanes` is published, so other open pages
  redraw in the new order. 422 when a lane is unknown, named twice or missing (the message says which), nothing changes. It is a **POST** so that a lane whose
  title is *Order* (key `order`) keeps its own `PUT` and `DELETE` routes. A failed save draws the lanes the server has again and shows the error.
- **MCP stays read-only.** `list_lanes` lists the lanes in the new order; there is no tool that reorders.

## 3. Consequences

- **The first lane is where a card goes when none is named** (`first_lane`, and the home of a hidden dry-run card): reordering changes that. The colour of a lane
  follows its place (`hue` is the index), so it changes when the lane moves.
- Move-to-lane menus, the card dialog's lane choice and `list_lanes` follow the new order without a reload.
- Cards keep their lane: only `lanes.position` is written.
