# ADR-095: The board has a Grouped view: a card with a parent is a row under its parent

**Status:** Accepted  
**Date:** 2026-11-28  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-011](011-board-interactions-sse-and-pointer-dnd.md) (the cards of a lane can be drawn under another card), [ADR-091](091-board-search.md) (the search finds a card that is a row)  
**Implemented in:** `static/js/tasks/grouping-model.js` (the rules, pure), `static/js/tasks/archived-children.js` (the list of archived children), `static/js/components/form-plan.js` and `form-view.js` (`enabled_when`), `static/js/tasks/board.js` (`setView`, the accordions, the counts), `static/js/tasks/main.js`, `templates/index.html`, `static/css/components.css`, `ui/forms/personal.yaml` and `api/settings.py` (the setting `board_view`), `tests/js/grouping-model.test.mjs`, `tests/e2e/test_grouped_view.py`  
**Affected chapters:** guides [UI catalog](../../guides/ui-catalog.md), [API reference](../../guides/api-reference.md)

## 1. Context

A card has at most one parent and any number of children (a tree). With an epic, its work packages and their tasks the board shows every card
in its lane, and a card with many children is one card among dozens. The owner wanted a second way to look at the same cards, chosen by each user.

## 2. Decision

- **A personal setting *Board view***: `classic` (the default, every card in its lane) or `grouped`. It is stored with the other personal settings (`personal.board_view`, no migration), saved when it is changed, and the board follows it **live** (`settings.changed`), also in other tabs.
- **Presentation only.** Nothing about a card changes: its lane, status, position and parent stay as they are; a card is moved to another lane only in its own dialog, and a parent never moves its children. Back in the classic view every card stands in its own lane.
- **Which cards leave their lane.** A card that has a parent **on the board** and **no children of its own** is not drawn in its lane; it is a row in the accordion of its parent. A parent that is archived or deleted is not on the board: its children are cards of their lanes again.
- **A card with children is an accordion.** Below its text a button (a chevron and the number of children) opens a list of its **direct** children, one row each: `#number title` on one line cut with `…`, the lane of the child itself as a chip, and the state of its run when it has one. A row opens the card like a click on the card; rows cannot be dragged. The list has a fixed height and scrolls itself. Open or closed is kept per card in the browser (`oa-board-groups`), closed by default.
- **Depth without nesting.** An accordion holds one level. A card that is a child **and** has children (a work package under an epic) is both: a row under its parent and a card of its own in its lane with its own accordion. The depth of the tree is the depth of cards on the board, not of accordions in accordions.
- **Counts.** A lane's badge counts the cards the lane draws; its title says how many more are in the accordions of their parents.
- **Search.** A card that matches its query and is a row is found through its parent: the parent is shown, its accordion opens by itself and holds the rows that match. A card is never shown in its lane by the search while it is a row.
- **The line of a card** reads `Parent: #15 Title` (the number before the title, here and in the card dialog). The count of sub-artifacts is written only in the classic view; in the grouped view the accordion says it.

## 3. Consequences

- A card is drawn twice only when it is both child and parent (as a row and as a card), by design.
- A child in the accordion of a parent in another lane stands visually in a lane it is not in; the chip on the row names its real lane.
- The classic view is the default; the grouped view has no effect on the API, the MCP tools, the rules of the lanes or the runs.

## Addition 1 (2026-11-28): archived children, the list window, the way back, and the setting Accordions

The board loads only cards that are not archived, so an archived child was invisible: nothing on its parent said that there was one. The owner decided:

- **The server counts them.** Every card read carries `archived_children` (an integer, **direct** children only; an archived card keeps its parent link, ADR-071). It is derived on every read (`GET /api/tasks`, one card, and the card of every event after a save), never stored. `GET /api/tasks` and `GET /api/v1/artifacts` take `parent` (an id or a number, `#` allowed): only the direct children of that card; with `archived=only` that is the list of its archived children (newest archived first); `X-Total-Count` counts the filtered list. A `parent` that names no card matches no card.
- **The last row of an accordion is "+N archived".** It is a row of the same style (a dashed outline, muted), shown as soon as one direct child is archived, and always last. A card whose children are **all** archived still has an accordion; it holds this one row and its header counts the visible children (0). A child that has archived children of its own stays on the board (its accordion is where they are reached), like a child with live children. While a search is on the row is not drawn (a search looks at the board only).
- **The list window.** The row opens a window (`#archived-children-modal`, `tasks/archived-children.js`) with a row per archived child: `#number title` on one line cut with `…`, the lane it was archived from and the day. It keeps itself current while open (a card archived or restored changes it). A click on a row hands the card to the page: the archive view replaces the lanes and the card is open in its read-only window.
- **Back to board.** That window gets a button *Back to board* before its close button (`data-modal-origin`, set with `ArtifactDialog.setOrigin`, dropped when the window closes or another card is opened, so the normal ways into the archive show none). It returns to the board; the list window stays **closed** (my call: the owner did not say whether the list should come back). *Close* leaves the user in the archive to pick another card.
- **Live.** Archiving and restoring publish `board.resync` after `task.updated` (as before), and the board reloads on it, so the count and the row follow at once without a new event; a deleted archived card (the rules of ADR-071) also reloads the board. No event was added or changed.
- **The classic view** writes `N sub-artifacts · M archived` in the line of a card (M is **not** part of N) and M is a link to the same window. The grouped view has it as the row instead.
- **The setting *Accordions*** (`board_groups_open`: `closed` default or `open`, directly under *Board view* in the personal settings, German *Akkordeons: offen / geschlossen*) is the state of an accordion the user has not touched. It is greyed unless the Board view is Grouped, with the reason under it: this is the form manifest's new `enabled_when` (same shape as `visible_when`, with `disabled_help` for the reason; the field stays drawn). What the user opened or closed by hand is kept per card in the browser (`oa-board-groups`, now `{id: open}`; the first version's list of open ids still reads as open); **changing the setting forgets those choices** so it takes effect at once, in this tab and, through `settings.changed`, in the others.
