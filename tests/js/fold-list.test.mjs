/* The folded middle of a long list (components/fold-list.js): which entries stay and how many are hidden. */
import assert from "node:assert/strict";
import { test } from "node:test";

const { foldEntries } = await import("../../openartifact/static/js/components/fold-list.js");

const items = (n) => Array.from({ length: n }, (_, i) => `v${n - i}`); // newest first: v7 v6 ... v1
const names = (entries) => entries.map((e) => (e.fold ? `fold:${e.fold}` : e.hidden ? `(${e.item})` : e.item));

test("a list of three or four stays as it is: a fold of one entry would hide less than it says", () => {
  assert.deepEqual(names(foldEntries(items(3), { head: 2, tail: 1 })), ["v3", "v2", "v1"]);
  assert.deepEqual(names(foldEntries(items(4), { head: 2, tail: 1 })), ["v4", "v3", "v2", "v1"]);
});

test("seven versions show the newest two and the first, and fold four", () => {
  assert.deepEqual(names(foldEntries(items(7), { head: 2, tail: 1 })), ["v7", "v6", "fold:4", "v1"]);
});

test("expanded, the hidden ones follow the separator so they can be reached", () => {
  assert.deepEqual(names(foldEntries(items(7), { head: 2, tail: 1, expanded: true })), ["v7", "v6", "fold:4", "(v5)", "(v4)", "(v3)", "(v2)", "v1"]);
});

test("five is the shortest list that folds (two shown at the start, one at the end, two folded)", () => {
  assert.deepEqual(names(foldEntries(items(5), { head: 2, tail: 1 })), ["v5", "v4", "fold:2", "v1"]);
});

test("an empty list is empty", () => {
  assert.deepEqual(foldEntries([], { head: 2, tail: 1 }), []);
});
