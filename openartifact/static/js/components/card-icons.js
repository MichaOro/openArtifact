/* The small icons in the top right corner of a node card on the canvas (the mock pin, the shield of the guards): a variant of the flexible
 * icon list (icon-list.js), with the same rule as the status bar of the canvas corner: every entry has a fixed place in the order, only an entry
 * that is active is in the card at all, so the shown ones sit next to each other with no gap, anchored at the right edge and growing to the left.
 * Another icon costs its key in `CARD_ORDER` and one `placeCardIcon` call. The look (the quiet icon button with its hover) is the shared one. */
import { IconList } from "./icon-list.js";
import { defineVariant } from "./icon-list-model.js";

/** The places of the icons on a card, left to right: the skip marker of a dry run (the flow page; it never comes with the mock pin: a mocked node is not skipped), the mock pin, then the shield of the guards (the right-most, where it always was). */
export const CARD_ORDER = { skipped: 5, mock: 10, guard: 20 };

/** What a card's corner allows. */
export const CARD_ICONS = defineVariant({
  name: "node card",
  allow: Object.keys(CARD_ORDER),
  order: CARD_ORDER,
  inactive: "detach",
  attrs: { key: "cardIcon", order: "cardOrder" },
});

const lists = new WeakMap();

function listOf(card) {
  let list = lists.get(card);
  if (!list) {
    list = new IconList(null, CARD_ICONS);
    lists.set(card, list);
  }
  let row = card.querySelector(":scope > .ge-node__icons");
  if (!row) {
    row = document.createElement("div");
    row.className = "ge-node__icons";
    card.append(row);
  }
  list.row = row;
  return list;
}

/** Put an entry's element in the card's list, at its place in the order (a second call with the same key replaces it). */
export function placeCardIcon(card, key, order, element) {
  listOf(card).add({ key, order, element, visible: true });
}

/** Take an entry away: the others close up. The list goes with its last entry. */
export function removeCardIcon(card, key) {
  lists.get(card)?.remove(key);
  card.querySelector(`:scope > .ge-node__icons > [data-card-icon="${key}"]`)?.remove(); // an element placed by an older list
  const row = card.querySelector(":scope > .ge-node__icons");
  if (row && !row.children.length) row.remove();
}

/** The element of an entry, if it is on the card. */
export function cardIcon(card, key) {
  return card.querySelector(`:scope > .ge-node__icons > [data-card-icon="${key}"]`);
}
