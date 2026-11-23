/* The pure helpers of the artifact fields (static/js/artifact-fields/model.js): what the editor sends,
 * what a card shows and what a control gives. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { blankField, editable, effectiveValue, nameFromLabel, parseProblems, removedWithValues, toWrite, valueOf } from "../../openartifact/static/js/artifact-fields/model.js";

test("a field name comes from its label", () => {
  assert.equal(nameFromLabel("Target date"), "target_date");
  assert.equal(nameFromLabel("Über uns"), "uber_uns");
  assert.equal(nameFromLabel("2nd try"), "f_2nd_try");
  assert.equal(nameFromLabel(""), "");
});

test("a field has no required setting: the editor neither holds nor sends one", () => {
  assert.equal("required" in blankField(), false);
  assert.equal("required" in editable({ name: "a", label: "A", kind: "text", required: true }), false);
  assert.equal("required" in toWrite({ ...blankField(), name: "a", label: "A" }), false);
});

test("what is sent for a field: only what its kind uses, a blank default is none", () => {
  const choice = toWrite({ ...blankField("choice"), name: "size", label: "Size", options: "S\nM\n\nL", default: "M" });
  assert.deepEqual(choice, { name: "size", label: "Size", kind: "choice", default: "M", options: ["S", "M", "L"] });
  const number = toWrite({ ...blankField("number"), name: "n", label: "N", min_value: "1", max_value: "", integer_only: true, default: "" });
  assert.deepEqual(number, { name: "n", label: "N", kind: "number", default: null, options: [], min_value: 1, max_value: null, integer_only: true });
  assert.equal(toWrite({ ...blankField("boolean"), name: "b", label: "B", default: "false" }).default, false);
});

test("a card shows the stored value, else the default, else nothing", () => {
  const field = { name: "size", default: "M" };
  assert.equal(effectiveValue(field, { size: "L" }), "L");
  assert.equal(effectiveValue(field, {}), "M");
  assert.equal(effectiveValue(field, { size: "" }), "M");
  assert.equal(effectiveValue({ name: "x", default: null }, {}), null);
  assert.equal(effectiveValue({ name: "on", default: true }, { on: false }), false); // false is a value
});

test("a control gives a number, true/false, a text or null for an empty one", () => {
  assert.equal(valueOf({ kind: "number" }, " 4.5 "), 4.5);
  assert.equal(valueOf({ kind: "number" }, ""), null);
  assert.equal(valueOf({ kind: "boolean" }, true), true);
  assert.equal(valueOf({ kind: "boolean" }, false), false);
  assert.equal(valueOf({ kind: "text" }, "  hi "), "hi");
  assert.equal(valueOf({ kind: "choice" }, ""), null);
});

test("removing a field that artifacts have values for is named with the count", () => {
  const before = [
    { name: "a", label: "A", artifact_count: 2 },
    { name: "b", label: "B", artifact_count: 0 },
    { name: "c", label: "C", artifact_count: 1 },
  ];
  assert.deepEqual(removedWithValues(before, ["c"]), [{ label: "A", count: 2 }]); // B had no values: nothing lost
  assert.deepEqual(removedWithValues(before, ["a", "b", "c"]), []);
});

test("the server's refusal is split by field", () => {
  const { byField, other } = parseProblems('Field size: "XL" is not one of S, M\nField size: second\nSomething else');
  assert.equal(byField.get("size"), '"XL" is not one of S, M second');
  assert.deepEqual(other, ["Something else"]);
});
