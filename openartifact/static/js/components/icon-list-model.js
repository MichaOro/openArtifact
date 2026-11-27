/* The model of every flexible icon list (components/icon-list.js): a small list of entries, each with a fixed place (`order`), shown only
 * while it is active. Pure, so the order, the "no gap" rule and the whitelist are tested on their own. */

/** The place of an entry that is always the last one, at the right edge (the "+" of the canvas corner). */
export const LAST = 1000;

/**
 * The entries in the order they are drawn, left to right. An entry that is not shown takes no room, so the ones beside it close up
 * (no gap), and one that appears takes its place in the order, not at the end.
 * @param {{key: string, order: number, visible: boolean}[]} entries
 * @returns {{key: string, order: number, visible: boolean}[]}
 */
export function arrange(entries) {
  return [...entries].sort((a, b) => a.order - b.order || a.key.localeCompare(b.key));
}

/** The keys of the entries that are shown, left to right. */
export function shownKeys(entries) {
  return arrange(entries)
    .filter((entry) => entry.visible)
    .map((entry) => entry.key);
}

/**
 * A variant of the icon list: what differs between the lists, nothing else. `allow` is the whitelist of entry keys the list may show, `order`
 * the place of each of them, `inactive` says what a hidden entry is (`"hide"`: it stays in the page with the attribute hidden, `"detach"`:
 * it is not in the page), `attrs` the data attributes of an entry's element (`key`, and optionally `order`), `cssOrder` whether the order is
 * also written as the CSS `order`, `buttonClass` the class of a button the list makes for an entry (icon + label).
 * @param {{name: string, allow: string[], order: Record<string, number>, inactive?: "hide"|"detach", attrs?: {key: string, order?: string},
 *   cssOrder?: boolean, buttonClass?: string}} variant
 */
export function defineVariant(variant) {
  if (!variant?.name) throw new Error("an icon list variant needs a name");
  if (!Array.isArray(variant.allow) || !variant.allow.length) throw new Error(`icon list "${variant.name}": the whitelist of keys is empty`);
  for (const key of variant.allow) {
    if (!Number.isFinite(variant.order?.[key])) throw new Error(`icon list "${variant.name}": "${key}" has no place in the order table`);
  }
  return Object.freeze({ inactive: "hide", attrs: { key: "iconKey" }, cssOrder: false, buttonClass: "icon-button", ...variant });
}

/** The place of an entry: the one it is given, else the one of the variant's table; a key the variant does not allow is an error that says so. */
export function placeOf(variant, key, order) {
  if (!variant.allow.includes(key)) {
    throw new Error(`icon list "${variant.name}": "${key}" is not allowed here (allowed: ${variant.allow.join(", ")})`);
  }
  return Number.isFinite(order) ? order : variant.order[key];
}
