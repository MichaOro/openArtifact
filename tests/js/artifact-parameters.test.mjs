import assert from "node:assert/strict";
import { test } from "node:test";

const { displayValue, droppedBy, initialValue, isBlank, parameterOf, parseProblems } = await import("../../openartifact/static/js/tasks/parameters.js");
const model = await import("../../openartifact/static/js/artifact-types/model.js");
const { contextSummary, formatContext } = await import("../../openartifact/static/js/tasks/context-format.js");

const urgency = { name: "urgency", label: "Urgency", kind: "choice", options: ["low", "high"], default: "low" };
const tier = { name: "tier", label: "Customer tier", kind: "choice", options: ["free", "gold"], default: null };
const count = { name: "count", label: "Count", kind: "number", default: null };
const flag = { name: "flag", label: "Escalate", kind: "boolean", default: null };

test("a control starts with the stored value, else the default, and a switch is at least off", () => {
  assert.equal(initialValue(urgency, "high"), "high");
  assert.equal(initialValue(urgency, undefined), "low");
  assert.equal(initialValue(urgency, null), "low");
  assert.equal(initialValue(tier, undefined), "");
  assert.equal(initialValue(count, 0), 0);
  assert.equal(initialValue(flag, undefined), false);
  assert.equal(initialValue({ ...flag, default: true }, undefined), true);
  assert.equal(initialValue({ ...flag, default: true }, false), false);
});

test("what a control holds becomes a value or null", () => {
  assert.equal(parameterOf(count, "12"), 12);
  assert.equal(parameterOf(count, "-1.5"), -1.5);
  assert.equal(parameterOf(count, ""), null);
  assert.equal(parameterOf(count, "abc"), "abc"); // the server names the wrong value
  assert.equal(parameterOf(tier, ""), null);
  assert.equal(parameterOf(tier, "gold"), "gold");
  assert.equal(parameterOf(flag, false), false);
  assert.equal(parameterOf(flag, true), true);
  assert.equal(isBlank("  "), true);
  assert.equal(isBlank(0), false);
});

test("values are shown as people read them", () => {
  assert.equal(displayValue(flag, true), "Yes");
  assert.equal(displayValue(flag, false), "No");
  assert.equal(displayValue(count, 3), "3");
  assert.equal(displayValue(count, null), "");
});

test("the server's parameter messages map to their fields, the rest stays general", () => {
  const { byField, other } = parseProblems('Parameter urgency: "hgh" is not one of low, high. Did you mean "high"?\nParameter count: 5 is above the maximum 3\nParameters are limited to 4 KiB (got 5000 bytes)\nSomething else');
  assert.deepEqual([...byField], [
    ["urgency", '"hgh" is not one of low, high. Did you mean "high"?'],
    ["count", "5 is above the maximum 3"],
  ]);
  assert.deepEqual(other, ["Parameters are limited to 4 KiB (got 5000 bytes)", "Something else"]);
  assert.deepEqual(parseProblems(undefined), { byField: new Map(), other: [] });
});

test("changing the type drops only the set values of parameters the new type lacks", () => {
  const ticket = { fields: [urgency, tier, flag] };
  const bug = { fields: [urgency, count] };
  assert.deepEqual(droppedBy(ticket, bug, { urgency: "high", tier: "gold", flag: true }), ["Customer tier", "Escalate"]);
  assert.deepEqual(droppedBy(ticket, bug, { urgency: "high", tier: null, flag: false }), []);
  assert.deepEqual(droppedBy(ticket, null, { urgency: "low" }), ["Urgency"]);
  assert.deepEqual(droppedBy(null, bug, { urgency: "low" }), []);
});

test("a parameter name comes from its label", () => {
  assert.equal(model.nameFromLabel("Customer tier"), "customer_tier");
  assert.equal(model.nameFromLabel("  Größe (cm) "), "gro_e_cm");
  assert.equal(model.nameFromLabel("Éclair!"), "eclair");
  assert.equal(model.nameFromLabel("3rd party"), "p_3rd_party");
  assert.equal(model.nameFromLabel("***"), "");
  assert.ok(model.nameFromLabel("x".repeat(50)).length <= 32);
});

test("an editor field is written with what its kind uses and a blank default as none", () => {
  const field = { ...model.blankField("choice"), name: " urgency ", label: "Urgency ", options: "low\n\n high \nlow2", default: "high", required: true };
  assert.deepEqual(model.toWrite(field), { name: "urgency", label: "Urgency", kind: "choice", required: true, default: "high", options: ["low", "high", "low2"] });
  const number = { ...model.blankField("number"), name: "n", label: "N", min_value: "0", max_value: "", integer_only: true, default: "5" };
  assert.deepEqual(model.toWrite(number), { name: "n", label: "N", kind: "number", required: false, default: 5, options: [], min_value: 0, max_value: null, integer_only: true });
  const text = { ...model.blankField("text"), name: "t", label: "T", max_length: "40" };
  assert.deepEqual(model.toWrite(text), { name: "t", label: "T", kind: "text", required: false, default: null, options: [], max_length: 40 });
  assert.equal(model.toWrite({ ...model.blankField("boolean"), name: "b", label: "B", default: "false" }).default, false);
});

test("a stored field is edited as text and the type page's messages split by field", () => {
  const edited = model.editable({ name: "n", label: "N", kind: "number", required: false, default: 3, options: [], max_length: null, min_value: 0, max_value: null, integer_only: true });
  assert.equal(edited.default, "3");
  assert.equal(edited.min_value, "0");
  assert.equal(edited.max_value, "");
  assert.equal(edited.nameEdited, true);
  const { byField, name, other } = model.parseProblems("2 artifacts use this type.\nField a: cannot be removed\nField a: the kind cannot change\nName: no control characters");
  assert.deepEqual([...byField], [["a", "cannot be removed the kind cannot change"]]);
  assert.equal(name, "no control characters");
  assert.deepEqual(other, ["2 artifacts use this type."]);
  assert.equal(model.summary({ fields: [1, 2], artifact_count: 1 }), "2 parameters · 1 artifact");
});

test("the context shows the card between the variables and the nodes, only when there is one", () => {
  assert.deepEqual(Object.keys(JSON.parse(formatContext({ vars: {}, card: { urgency: "high" }, nodes: {} }))), ["vars", "card", "nodes"]);
  assert.deepEqual(Object.keys(JSON.parse(formatContext({ vars: {}, card: {}, nodes: {} }))), ["vars", "nodes"]);
  assert.equal(contextSummary({ vars: {}, card: { a: 1, b: null }, nodes: {} }), "0 variables · 2 parameters · 0 node results");
  assert.equal(contextSummary({ vars: {}, card: {}, nodes: {} }), "empty");
});
