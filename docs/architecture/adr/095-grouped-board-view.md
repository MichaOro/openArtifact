# ADR-095: The board has a Grouped view: a card with a parent is a row under its parent

**Status:** Accepted  
**Date:** 2026-11-28  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-011](011-board-interactions-sse-and-pointer-dnd.md) (the cards of a lane can be drawn under another card), [ADR-091](091-board-search.md) (the search finds a card that is a row)  
**Implemented in:** `static/js/tasks/grouping-model.js` (the rules, pure), `static/js/tasks/board.js` (`setView`, the accordions, the counts), `static/js/tasks/main.js`, `templates/index.html`, `static/css/components.css`, `ui/forms/personal.yaml` and `api/settings.py` (the setting `board_view`), `tests/js/grouping-model.test.mjs`, `tests/e2e/test_grouped_view.py`  
**Affected chapters:** guides [UI catalog](../../guides/ui-catalog.md)

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
