/* The pure part of the Grouped board view (ADR-095): which cards leave their lane column and which rows an accordion holds.
 *
 * Nothing here changes a card. The view only decides where a card is drawn: a card with a parent that is on the board and without
 * children of its own is not drawn in its lane but as a row in the accordion of its parent. A card that is a child AND has children
 * (a work package between an epic and its tasks) is both: a row under its parent and a card of its own in its lane, with its own
 * accordion. Each accordion holds the direct children only, so the depth comes from cards standing on the board, not from nesting.
 *
 * A task here is `{id, number, title, status, parent_id}`; `tasks` is what is on the board (archived cards are not). */

/** The direct children of every card that has some on the board: `Map<parentId, task[]>`, each list in the order of the numbers. */
export function childrenByParent(tasks) {
  const ids = new Set(tasks.map((task) => task.id));
  const found = new Map();
  for (const task of tasks) {
    if (!task.parent_id || !ids.has(task.parent_id)) continue; // no parent, or one that is archived or deleted: the card is nobody's child here
    if (!found.has(task.parent_id)) found.set(task.parent_id, []);
    found.get(task.parent_id).push(task);
  }
  for (const list of found.values()) list.sort((a, b) => a.number - b.number);
  return found;
}

/** The ids of the cards the Grouped view does not draw in their lane: a child (its parent is on the board) that has no children itself. */
export function hiddenIds(tasks) {
  const children = childrenByParent(tasks);
  const hidden = new Set();
  for (const list of children.values()) {
    for (const child of list) if (!children.has(child.id)) hidden.add(child.id);
  }
  return hidden;
}

/**
 * What the Grouped view shows for the cards on the board.
 * @param {object[]} tasks the cards on the board
 * @param {(task: object) => boolean} [keeps] the board search: whether a card matches (omitted: no search is on)
 * @returns {{hidden: Set<string>, children: Map<string, object[]>, rows: Map<string, object[]>, shown: Set<string>}}
 *   `hidden`: cards not drawn in their lane. `children`: the direct children of every parent. `rows`: the rows its accordion shows
 *   (all children, or only those that match while a search is on). `shown`: the cards that stay drawn in a lane while a search is
 *   on: a card that matches itself or has a row that matches, and no card at all that is hidden (its parent shows it).
 */
export function plan(tasks, keeps = null) {
  const children = childrenByParent(tasks);
  const hidden = hiddenIds(tasks);
  const rows = new Map();
  for (const [parentId, list] of children) rows.set(parentId, keeps ? list.filter(keeps) : list);
  const shown = new Set();
  for (const task of tasks) {
    if (hidden.has(task.id)) continue;
    if (!keeps || keeps(task) || (rows.get(task.id)?.length ?? 0) > 0) shown.add(task.id);
  }
  return { hidden, children, rows, shown };
}

/** How many cards a lane draws in the Grouped view: the cards of the lane that are not hidden. */
export function laneTotal(tasks, hidden, status) {
  let n = 0;
  for (const task of tasks) if (task.status === status && !hidden.has(task.id)) n += 1;
  return n;
}

/** How many cards of a lane are in the accordions of other cards (not counted in the lane's badge in the Grouped view). */
export function laneGrouped(tasks, hidden, status) {
  let n = 0;
  for (const task of tasks) if (task.status === status && hidden.has(task.id)) n += 1;
  return n;
}

/** Whether the accordion of a card is open: the user's choice, kept in the browser; while a search has rows for it, it is open. */
export function isOpen(stored, id, searching, rowCount) {
  if (searching && rowCount > 0) return true;
  return stored.has(id);
}

/** The ids of the open accordions as stored (a damaged value is no choice at all). */
export function readOpen(raw) {
  try {
    const list = JSON.parse(raw ?? "[]");
    return new Set(Array.isArray(list) ? list.filter((id) => typeof id === "string") : []);
  } catch {
    return new Set();
  }
}

/** The text a row shows for a card: its number and title (the row cuts it to one line). */
export function rowLabel(task) {
  return `#${task.number} ${task.title}`;
}
