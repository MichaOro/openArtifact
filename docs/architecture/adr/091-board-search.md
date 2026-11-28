# ADR-091: The board has a search by title and number, never by content

**Status:** Accepted  
**Date:** 2026-11-27  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-011](011-board-interactions-sse-and-pointer-dnd.md) (the board's interactions: a filter hides cards, drag and drop and the keyboard keep working)  
**Implemented in:** `static/js/tasks/board-search-model.js` (the matching), `static/js/tasks/board-search.js` (the field), `static/js/tasks/board.js` (`setFilter`, `keepVisible`, the lane badges), `static/js/tasks/main.js`, `templates/index.html`, `templates/components/lane.html`  
**Affected chapters:** guides [concepts](../../guides/concepts.md), [UI catalog](../../guides/ui-catalog.md)

## 1. Context

The board had no search: with a few hundred cards the owner could not find *Zusammenfassung* by its title or card 154 by its number. The MCP tool `search_artifacts` searches title and body; the owner decided the **board** must not search content.

## 2. Decision

- **A search field in the board header** (left of *Add lane*): the title and the number of a card, **never the body**. It is a client-side filter over the cards the board has already loaded: no request, no API change, no stored state.
- **What matches** (pure, `board-search-model.js`): an empty query keeps everything; `#154` keeps the card with exactly that number; `154` keeps that card **and** the cards whose title contains the digits; otherwise every word must be in the title, case ignored and accents folded (`ä` is `ae`, `ö` `oe`, `ü` `ue`, `ß` `ss`, `é` is `e`), so `ueber` finds *Überblick*.
- **What is shown:** a card that does not match is **hidden** (not dimmed); the lanes stay. While a query is on, a lane's count reads `3/16` (title and name for assistive technology: "3 of 16 match in this lane"); a lane with cards but no match shows "No matching cards" in place of its cards; a lane with no cards keeps the look of an empty lane. A line next to the field says "N cards match" (`aria-live`, polite). The query is kept in the address (`?q=`, `replaceState`): a reload and a link keep it.
- **Escape** and the clear button empty the field; `/` focuses it when no field has the focus and no dialog is open.
- **Cards that change while a query is on:** the board applies the filter whenever a card is added, changed or removed, whatever the source (own change, another tab, an agent). **A card the user makes by hand stays shown** until the query changes (a made card must not vanish). A card that has the focus and is hidden by a change gives the focus to the field.
- **Drag and drop and the keyboard:** hidden cards stay in the lane in their order, and a position is always computed from the neighbours in the **whole** lane, so a card dropped between visible cards is placed right for the hidden ones too. A drop on a lane works as before. The keyboard reorder (`Alt+↑/↓`) passes the next **visible** card (a hidden card is not a place).
- **The archive view** replaces the board and the field is hidden with it.
- **Cost:** filtering toggles `hidden` on the existing cards; the board is not drawn again, so hundreds of cards stay cheap.

## 3. Consequences

- The board search and `search_artifacts` differ on purpose: the board finds by title and number, the MCP tool also reads the body.
- A card hidden by the query is still in the data (references with `#` offer it, a rule acts on it).
