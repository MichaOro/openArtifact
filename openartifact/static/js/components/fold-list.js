/* A long list that folds its middle (the way GitHub folds the comments of a long issue): the first and the last entries stay, the rest
 * is hidden behind one separator ("Show more versions (4)", a vertical line through the middle of its button). The separator is a
 * button (aria-expanded, Enter and Space) and opens or closes the hidden entries; an entry hidden before can be reached after.
 *
 *   const entries = foldEntries(items, { head: 2, tail: 1, expanded });   // pure, unit-tested
 *   for (const entry of entries) {
 *     list.append(entry.fold ? foldSeparator({ count: entry.fold, expanded, label, onToggle }) : render(entry.item));
 *   }
 *
 * A list of `head + tail + 1` entries or fewer is shown as it is (a fold of one entry would hide less than it says). */

/**
 * @param {unknown[]} items in the order they are shown
 * @param {{head?: number, tail?: number, expanded?: boolean}} [options] `head` entries stay at the start, `tail` at the end
 * @returns {({item: unknown, hidden?: boolean} | {fold: number})[]} the entries to draw: items, and one `{fold: n}` between the head and
 *   the tail when more than one entry can be folded; when expanded the hidden items follow the separator (marked `hidden: true`)
 */
export function foldEntries(items, { head = 1, tail = 1, expanded = false } = {}) {
  const all = items.map((item) => ({ item }));
  if (items.length <= head + tail + 1) return all;
  const middle = items.slice(head, items.length - tail);
  const folded = [...all.slice(0, head), { fold: middle.length }];
  if (expanded) folded.push(...middle.map((item) => ({ item, hidden: true })));
  folded.push(...all.slice(items.length - tail));
  return folded;
}

/**
 * The separator of a folded list as a list entry.
 * @param {{count: number, expanded: boolean, label: string, onToggle: () => void, controls?: string}} options
 *   `label` is the words on the button ("Show more versions (4)" or "Hide 4 versions")
 */
export function foldSeparator({ count, expanded, label, onToggle, controls }) {
  const item = document.createElement("li");
  item.className = "fold-separator";
  item.dataset.fold = String(count);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "button button--ghost button--sm fold-separator__button";
  button.textContent = label;
  button.setAttribute("aria-expanded", String(expanded));
  if (controls) button.setAttribute("aria-controls", controls);
  button.addEventListener("click", onToggle);
  item.append(button);
  return item;
}
