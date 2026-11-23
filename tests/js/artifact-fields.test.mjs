/* The pure helpers of the artifact fields (static/js/artifact-fields/model.js): what the editor sends,
 * what a card shows and what a control gives. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { blankField, editable, effectiveValue, nameFromLabel, newOption, optionProblem, parseProblems, removedWithValues, toWrite, typeText, valueOf } from "../../openartifact/static/js/artifact-fields/model.js";

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

test("what is sent for a field: only what its type uses, a blank default is none", () => {
  const single = { ...blankField("single"), name: "size", label: "Size", options: [newOption("S"), newOption("M"), newOption(" "), newOption("L")], default: "M" };
  assert.deepEqual(toWrite(single), { name: "size", label: "Size", kind: "choice", default: "M", options: ["S", "M", "L"], multiple: false });
  const number = { ...blankField("number"), name: "n", label: "N", min_value: "1", max_value: "", integer_only: true, default: "" };
  assert.deepEqual(toWrite(number), { name: "n", label: "N", kind: "number", default: null, options: [], multiple: false, min_value: 1, max_value: null, integer_only: true });
  assert.equal(toWrite({ ...blankField("boolean"), name: "b", label: "B", default: "false" }).default, false);
});

test("a multi select sends a list default of its options and says that it is multiple", () => {
  const multi = { ...blankField("multi"), name: "tags", label: "Tags", options: [newOption("bug"), newOption("ui")], default: ["ui", "gone"] };
  assert.deepEqual(toWrite(multi), { name: "tags", label: "Tags", kind: "choice", default: ["ui"], options: ["bug", "ui"], multiple: true });
  assert.equal(toWrite({ ...multi, default: [] }).default, null);
  assert.equal(typeText(multi), "Multi select · 2 options");
});

test("a stored select comes back with its options' original texts, so a rename is sent as a rename", () => {
  const state = editable({ name: "size", label: "Size", kind: "choice", multiple: false, options: ["S", "M"], default: "M", artifact_count: 2 });
  assert.equal(state.type, "single");
  assert.equal(state.saved, true);
  state.options[1].text = "Medium";
  state.default = "Medium";
  state.options.push(newOption("L"));
  assert.deepEqual(toWrite(state).renamed_options, { M: "Medium" }); // L is new: no rename
  assert.equal(editable({ name: "t", label: "T", kind: "choice", multiple: true, options: ["a"], default: ["a"] }).type, "multi");
});

test("an option needs a text of its own", () => {
  const state = { ...blankField("single"), options: [newOption("Bug"), newOption("UI")] };
  assert.equal(optionProblem(state, "  "), "An option needs a text.");
  assert.equal(optionProblem(state, "bug"), '"bug" is already an option.'); // ignoring case
  assert.equal(optionProblem(state, "Bug", state.options[0]), null); // itself
  assert.equal(optionProblem(state, "x".repeat(41)), "An option is at most 40 characters.");
});

test("a multi select's control gives its list, an empty one is not set", () => {
  assert.deepEqual(valueOf({ kind: "choice", multiple: true }, ["a", "b"]), ["a", "b"]);
  assert.equal(valueOf({ kind: "choice", multiple: true }, []), null);
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

test("the artifact fields are offered as card.NAME references", async () => {
  const { candidatesFor } = await import("../../openartifact/static/js/editor/reference-completion.js");
  const found = candidatesFor([], { cardFields: [{ name: "size", label: "Size" }, { name: "estimate", label: "Estimate" }] });
  assert.deepEqual(found.map((c) => c.insert), ["card.size", "card.estimate"]);
  assert.equal(found[0].detail, "Size: field of the artifact");
  assert.equal(found[0].complete, true);
  assert.deepEqual(candidatesFor([], {}), []); // without fields nothing is offered
});
