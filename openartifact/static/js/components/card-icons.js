/* The small icons in the top right corner of a node card on the canvas (the mock pin, the shield of the guards): ONE flexible list, with the
 * same rule as the status bar of the canvas corner (status-bar-model.js): every entry has a fixed place in the order, only an entry that is
 * active is in the card at all, so the shown ones sit next to each other with no gap, anchored at the right edge and growing to the left. Another
 * icon costs one `placeCardIcon` call with its own order. The look (the quiet icon button with its hover) is the shared one of the guard's shield. */
import { arrange } from "./status-bar-model.js";

/** The places of the icons on a card, left to right: the mock pin, then the shield of the guards (the right-most, where it always was). */
export const CARD_ORDER = { mock: 10, guard: 20 };

function listOf(card) {
  let list = card.querySelector(":scope > .ge-node__icons");
  if (!list) {
    list = document.createElement("div");
    list.className = "ge-node__icons";
    card.append(list);
  }
  return list;
}

/** Put an entry's element in the card's list, at its place in the order (a second call with the same key replaces it). */
export function placeCardIcon(card, key, order, element) {
  const list = listOf(card);
  list.querySelector(`:scope > [data-card-icon="${key}"]`)?.remove();
  element.dataset.cardIcon = key;
  element.dataset.cardOrder = String(order);
  list.append(element);
  const entries = [...list.children].map((child) => ({ key: child.dataset.cardIcon, order: Number(child.dataset.cardOrder), visible: true, element: child }));
  list.append(...arrange(entries).map((entry) => entry.element));
}

/** Take an entry away: the others close up. The list goes with its last entry. */
export function removeCardIcon(card, key) {
  const list = card.querySelector(":scope > .ge-node__icons");
  list?.querySelector(`:scope > [data-card-icon="${key}"]`)?.remove();
  if (list && !list.children.length) list.remove();
}

/** The element of an entry, if it is on the card. */
export function cardIcon(card, key) {
  return card.querySelector(`:scope > .ge-node__icons > [data-card-icon="${key}"]`);
}
