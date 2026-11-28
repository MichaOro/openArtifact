/* The pure part of the Grouped board view (static/js/tasks/grouping-model.js, ADR-095): which cards leave their lane, which rows an
 * accordion holds, what a search keeps, and what is stored about the open accordions. */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  accordionRows,
  archivedCount,
  childrenByParent,
  hasAccordion,
  hiddenIds,
  isOpen,
  laneGrouped,
  laneTotal,
  plan,
  readOpen,
  rowLabel,
  writeOpen,
} from "../../openartifact/static/js/tasks/grouping-model.js";
import { matches, parseQuery } from "../../openartifact/static/js/tasks/board-search-model.js";

const card = (number, title, status, parent = null) => ({ id: `id${number}`, number, title, status, parent_id: parent ? `id${parent}` : null });
/** An epic (#1) with a work package (#6) that has three tasks, one more task directly under the epic, and a card of nobody. */
const TREE = [
  card(1, "Epic", "next"),
  card(6, "Work package", "progress", 1),
  card(100, "Task a", "backlog", 6),
  card(200, "Task b", "progress", 6),
  card(300, "Task c", "done", 6),
  card(7, "Loose task under the epic", "backlog", 1),
  card(9, "Nobody's card", "backlog"),
];
const numbers = (ids) => [...ids].map((id) => Number(id.slice(2))).sort((a, b) => a - b);

test("a card with a parent on the board and no children of its own is hidden from its lane", () => {
  assert.deepEqual(numbers(hiddenIds(TREE)), [7, 100, 200, 300]);
});

test("a card that is a child and a parent (#6 under #1) stays on the board, with its own accordion, and is a row under its parent too", () => {
  const { hidden, children, rows } = plan(TREE);
  assert.equal(hidden.has("id6"), false); // it is a parent itself: it stays in its lane
  assert.deepEqual(children.get("id1").map((c) => c.number), [6, 7]); // and it is a row of #1
  assert.deepEqual(children.get("id6").map((c) => c.number), [100, 200, 300]); // the rows of #6 are its own children, one level only
  assert.deepEqual(rows.get("id1").map((c) => c.number), [6, 7]);
  assert.equal(children.has("id100"), false); // a task without children has no accordion
});

test("the rows are the direct children only, in the order of their numbers, whatever order the cards come in", () => {
  const shuffled = [TREE[5], TREE[3], TREE[0], TREE[4], TREE[1], TREE[2], TREE[6]];
  assert.deepEqual(childrenByParent(shuffled).get("id6").map((c) => c.number), [100, 200, 300]);
  assert.deepEqual(childrenByParent(shuffled).get("id1").map((c) => c.number), [6, 7]); // not the grandchildren
});

test("a parent that is not on the board (archived, deleted) makes its children cards of their own again", () => {
  const withoutParent = TREE.filter((task) => task.number !== 6); // #6 was archived: the board has no card of it
  const { hidden, children } = plan(withoutParent);
  assert.deepEqual(numbers(hidden), [7]); // #100, #200, #300 stand in their lanes: nobody would show them otherwise
  assert.equal(children.has("id6"), false);
  assert.deepEqual(children.get("id1").map((c) => c.number), [7]);
});

test("a card whose parent is unknown to the board is not hidden", () => {
  assert.deepEqual([...hiddenIds([card(5, "Orphan", "next", 99)])], []);
});

test("the lane counts the cards it draws; the cards in accordions are counted apart", () => {
  const { hidden } = plan(TREE);
  assert.equal(laneTotal(TREE, hidden, "backlog"), 1); // #9 only: #100 and #7 are rows
  assert.equal(laneGrouped(TREE, hidden, "backlog"), 2);
  assert.equal(laneTotal(TREE, hidden, "progress"), 1); // #6 stays, #200 is a row
  assert.equal(laneGrouped(TREE, hidden, "progress"), 1);
  assert.equal(laneTotal(TREE, hidden, "next"), 1);
  assert.equal(laneGrouped(TREE, hidden, "next"), 0);
});

test("a search keeps the parent of a row that matches and shows only the rows that match; a hidden card is never shown by itself", () => {
  const keeps = (query) => (task) => matches(task, parseQuery(query));
  const found = plan(TREE, keeps("task b"));
  assert.deepEqual(found.rows.get("id6").map((c) => c.number), [200]);
  assert.deepEqual(numbers(found.shown), [6]); // #6 has the matching row; #1 has no matching row (its rows #6 and #7 do not match) and does not match itself
  assert.equal(found.shown.has("id200"), false); // a row is drawn by its parent, not in the lane
  const word = plan(TREE, keeps("work"));
  assert.deepEqual(numbers(word.shown), [1, 6]); // #6 matches itself, so #1 has a matching row
  assert.deepEqual(word.rows.get("id1").map((c) => c.number), [6]); // the row of #7 does not match and is not drawn
  const none = plan(TREE, keeps("nothing like it"));
  assert.deepEqual([...none.shown], []);
  assert.deepEqual(none.rows.get("id6"), []);
});

test("a number in the search finds a card that is a row, through its parent", () => {
  const found = plan(TREE, (task) => matches(task, parseQuery("#300")));
  assert.deepEqual(numbers(found.shown), [6]);
  assert.deepEqual(found.rows.get("id6").map((c) => c.number), [300]);
});

test("an accordion follows the user's choice for the card, else the setting, and is open while a search has rows in it", () => {
  const stored = new Map([["id1", true], ["id7", false]]);
  assert.equal(isOpen(stored, "id1", false, 3), true);
  assert.equal(isOpen(stored, "id6", false, 3), false); // closed by default
  assert.equal(isOpen(stored, "id6", false, 3, true), true); // the setting "open" is the default of a card without a choice
  assert.equal(isOpen(stored, "id7", false, 3, true), false); // a card closed by hand stays closed under that setting
  assert.equal(isOpen(stored, "id6", true, 2), true); // a search opens it
  assert.equal(isOpen(stored, "id6", true, 0), false); // a search without a row in it does not
  assert.equal(isOpen(stored, "id1", true, 0), true); // the user's choice stays
});

test("what is kept about the accordions is read back, an earlier list reads as open, and a damaged value is no choice", () => {
  assert.deepEqual([...readOpen('{"a":true,"b":false}')], [["a", true], ["b", false]]);
  assert.deepEqual([...readOpen('["a","b"]')], [["a", true], ["b", true]]); // the format of the first version of the view
  assert.deepEqual([...readOpen(null)], []);
  assert.deepEqual([...readOpen("not json")], []);
  assert.deepEqual([...readOpen('{"a":1}')], []);
  assert.deepEqual([...readOpen('["a",1,null]')], [["a", true]]);
  assert.equal(writeOpen(new Map([["a", true], ["b", false]])), '{"a":true,"b":false}');
});

test("a row names its card by number and title", () => {
  assert.equal(rowLabel({ number: 21, title: "Run history" }), "#21 Run history");
});

const withArchived = (task, n) => ({ ...task, archived_children: n });

test("the number of archived children is what the server says, and nothing else counts", () => {
  assert.equal(archivedCount(withArchived(card(1, "E", "next"), 4)), 4);
  assert.equal(archivedCount(card(1, "E", "next")), 0); // the server did not say
  assert.equal(archivedCount({ archived_children: -2 }), 0);
  assert.equal(archivedCount({ archived_children: "x" }), 0);
});

test("the archive row is the last row of an accordion, and only there when a child is archived", () => {
  const epic = withArchived(card(1, "Epic", "next"), 3);
  const rows = accordionRows(epic, [card(6, "WP", "progress", 1), card(7, "Task", "backlog", 1)], false);
  assert.deepEqual(rows.map((r) => r.kind), ["child", "child", "archived"]);
  assert.equal(rows.at(-1).count, 3);
  assert.deepEqual(accordionRows(card(1, "Epic", "next"), [card(6, "WP", "progress", 1)], false).map((r) => r.kind), ["child"]); // none archived: no row
  assert.deepEqual(accordionRows(epic, [card(6, "WP", "progress", 1)], true).map((r) => r.kind), ["child"]); // a search looks at the board only
});

test("a parent whose children are all archived still has an accordion, with the archive row only", () => {
  const parent = withArchived(card(1, "Epic", "next"), 2);
  const tasks = [parent];
  assert.equal(hasAccordion(parent, childrenByParent(tasks).get("id1")), true);
  assert.deepEqual(accordionRows(parent, [], false), [{ kind: "archived", count: 2 }]);
  assert.equal(hasAccordion(card(9, "Alone", "next"), undefined), false);
});

test("a child with archived children of its own stays on the board: its accordion is where they are reached", () => {
  const tasks = [card(1, "Epic", "next"), withArchived(card(6, "WP", "progress", 1), 1), card(7, "Task", "backlog", 1)];
  assert.deepEqual(numbers(hiddenIds(tasks)), [7]); // #6 stays, #7 becomes a row
  assert.deepEqual(numbers(plan(tasks).shown), [1, 6]);
});
