/* The model of the status bar in the corner of the editor's canvas (components/status-bar.js): a small list of entries, each with a fixed
 * place (`order`), shown only while it is active. Pure, so the order and the "no gap" rule are tested on their own. */

/** The place of the "+" entry: always the last one, at the right edge. */
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
