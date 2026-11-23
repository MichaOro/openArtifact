import assert from "node:assert/strict";
import { test } from "node:test";

const { Selection } = await import("../../openartifact/static/js/components/selection.js");

test("toggling adds and removes an id and tells the owner once per change", () => {
  const seen = [];
  const selection = new Selection((ids) => seen.push([...ids]));
  selection.toggle("a");
  selection.toggle("b");
  selection.toggle("a");
  selection.toggle("b", true); // already in: nothing changes, nothing is announced
  assert.deepEqual(seen, [["a"], ["a", "b"], ["b"]]);
  assert.equal(selection.size, 1);
  assert.ok(selection.has("b") && !selection.has("a"));
});

test("setting several ids replaces the selection; clearing empties it and tells nobody twice", () => {
  const seen = [];
  const selection = new Selection((ids) => seen.push(ids.size));
  selection.set(["a", "b", "c"]);
  selection.set(["a", "b", "c"]); // the same: no change
  selection.clear();
  selection.clear();
  assert.deepEqual(seen, [3, 0]);
});

test("ids that are no longer there can be dropped, which keeps the rest", () => {
  const selection = new Selection();
  selection.set(["a", "b", "c"]);
  selection.keepOnly(new Set(["b", "x"]));
  assert.deepEqual([...selection.ids], ["b"]);
});

test("the state of a header checkbox follows how many of the shown ids are selected", () => {
  const selection = new Selection();
  const shown = ["a", "b", "c"];
  assert.deepEqual(selection.stateOf(shown), { checked: false, indeterminate: false });
  selection.set(["a"]);
  assert.deepEqual(selection.stateOf(shown), { checked: false, indeterminate: true });
  selection.set(["a", "b", "c", "z"]);
  assert.deepEqual(selection.stateOf(shown), { checked: true, indeterminate: false });
  assert.deepEqual(selection.stateOf([]), { checked: false, indeterminate: false });
});
