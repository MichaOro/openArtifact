/* The list of fields of a schema (components/schema-fields-model.js, ADR-080): the rules of the list as pure functions. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";

const {
  LIMITS, MAX_FIELDS, TYPES, addField, fieldProblem, freeName, listProblem, moveField, parseChoices, removeField, setProp, startField,
} = await import("../../openartifact/static/js/components/schema-fields-model.js");

/** What the server says about the setting: the live answer recorded for the editor tests. */
const description = JSON.parse(readFileSync(new URL("./../fixtures/node-types.json", import.meta.url), "utf8"));
const setting = description.find((d) => d.kind === "handover_tool").settings.find((s) => s.key === "fields");

test("the types and bounds of the editor are the server's (a test keeps both equal)", () => {
  assert.deepEqual(TYPES, setting.field_types);
  assert.equal(MAX_FIELDS, setting.max_fields);
  assert.deepEqual(LIMITS, setting.field_limits);
});

test("a new field gets a name no other field has and starts as an optional text", () => {
  assert.equal(freeName([]), "field");
  assert.equal(freeName([{ name: "field" }]), "field_2");
  assert.equal(freeName([{ name: "field" }, { name: "field_2" }, { name: "field_3" }]), "field_4");
  assert.deepEqual(startField([{ name: "field" }]), { name: "field_2", type: "text", required: false, description: "" });
  assert.equal(addField([{ name: "field" }]).length, 2);
});

test("add, remove and move return a new list and never change the one they were given", () => {
  const list = Object.freeze([{ name: "a" }, { name: "b" }, { name: "c" }]);
  assert.deepEqual(removeField(list, 1).map((f) => f.name), ["a", "c"]);
  assert.deepEqual(moveField(list, 0, 2).map((f) => f.name), ["b", "c", "a"]);
  assert.deepEqual(moveField(list, 2, 0).map((f) => f.name), ["c", "a", "b"]);
  assert.equal(moveField(list, 1, 1), list);
  assert.equal(moveField(list, 0, 3), list);
  assert.equal(moveField(list, -1, 0), list);
});

test("a property is set on one field only; a choice starts with no values, a field that is no choice has none", () => {
  const list = [{ name: "a", type: "text" }, { name: "b", type: "text" }];
  const next = setProp(list, 1, "required", true);
  assert.deepEqual(next, [{ name: "a", type: "text" }, { name: "b", type: "text", required: true }]);
  assert.equal(list[1].required, undefined);
  const choice = setProp(list, 0, "type", "choice");
  assert.deepEqual(choice[0], { name: "a", type: "choice", choices: [] });
  const back = setProp(setProp(choice, 0, "choices", ["x", "y"]), 0, "type", "number");
  assert.deepEqual(back[0], { name: "a", type: "number" });
});

test("the values of a choice are read one per line or separated by commas, trimmed, empty ones dropped", () => {
  assert.deepEqual(parseChoices(" approve , reject\n\nwait "), ["approve", "reject", "wait"]);
  assert.deepEqual(parseChoices(""), []);
  assert.deepEqual(parseChoices("a,,b"), ["a", "b"]);
});

test("what is wrong with a field is told as a code with its numbers, the first problem first", () => {
  const ok = { name: "verdict", type: "choice", choices: ["a", "b"], description: "" };
  assert.equal(listProblem([ok]), null);
  assert.deepEqual(listProblem([{ ...ok, name: "Bad" }]), { code: "name_format", params: { n: 1 } });
  assert.deepEqual(listProblem([{ ...ok, name: "9" }]), { code: "name_format", params: { n: 1 } });
  assert.deepEqual(listProblem([ok, { ...ok }]), { code: "name_twice", params: { name: "verdict" } });
  assert.deepEqual(listProblem([{ ...ok, choices: ["only"] }]), { code: "choice_count", params: { name: "verdict", min: 2, max: 20 } });
  assert.deepEqual(listProblem([{ ...ok, choices: ["a", "a"] }]), { code: "choice_twice", params: { name: "verdict" } });
  assert.deepEqual(listProblem([{ ...ok, choices: ["a", "b".repeat(61)] }]), { code: "choice_long", params: { name: "verdict", max: 60 } });
  assert.deepEqual(listProblem([{ ...ok, description: "x".repeat(301) }]), { code: "description_long", params: { name: "verdict", max: 300 } });
  assert.deepEqual(listProblem(Array.from({ length: 31 }, (_, i) => ({ name: `f${i}`, type: "text" }))), { code: "too_many", params: { max: 30 } });
});

test("only a choice is checked for values", () => {
  assert.equal(fieldProblem([{ name: "a", type: "text" }], 0), null);
  assert.equal(fieldProblem([{ name: "a", type: "list" }], 0), null);
});

test("the compact row of the wide list is handle, name, type, required and the menu; an output has its value as a column, the rest comes on lines of its own", async () => {
  const { rowPlan } = await import("../../openartifact/static/js/components/schema-fields-model.js");
  const inputs = rowPlan({ showRequired: true, extra: "default" });
  assert.deepEqual(inputs.columns, ["grip", "name", "type", "required", "more"], "an input row is compact: no description and no default column");
  assert.equal(inputs.row, '"grip name type required more"');
  assert.equal(inputs.description, '". description description description ."');
  assert.equal(inputs.extra, '". extra extra extra ."');
  assert.equal(inputs.choices, '". choices choices choices ."');
  const outputs = rowPlan({ showRequired: false, extra: "value" });
  assert.deepEqual(outputs.columns, ["grip", "name", "type", "extra", "more"], "an output has no required box but always its value");
  assert.equal(outputs.template.split(" ").length >= outputs.columns.length, true);
  assert.equal(outputs.extra, '". . . . ."', "the value is a column of the row: no second place for the area extra (an area may not be in two places)");
  const plain = rowPlan({ showRequired: true, extra: null });
  assert.deepEqual(plain.columns, ["grip", "name", "type", "required", "more"]);
});

test("a row shows a description or a default only when the field has it (or the menu added it); an output always shows its value", async () => {
  const { shownOf } = await import("../../openartifact/static/js/components/schema-fields-model.js");
  assert.deepEqual(shownOf({ name: "a", description: "", default: "" }, "default"), { description: false, extra: false });
  assert.deepEqual(shownOf({ name: "a", description: "who", default: "x" }, "default"), { description: true, extra: true });
  assert.deepEqual(shownOf({ name: "a", description: "" }, "value"), { description: false, extra: true });
  assert.deepEqual(shownOf({ name: "a", description: "" }, null), { description: false, extra: false });
});

test("the row menu offers add or remove for the description (and the default of an input) and then Delete", async () => {
  const { menuPlan } = await import("../../openartifact/static/js/components/schema-fields-model.js");
  assert.deepEqual(menuPlan({ extra: "default", shown: { description: false, extra: false } }), [
    { key: "description", on: false },
    { key: "extra", on: false },
    { key: "delete", on: false },
  ]);
  assert.deepEqual(menuPlan({ extra: "default", shown: { description: true, extra: true } }).map((e) => e.on), [true, true, false], "shown entries offer removing");
  assert.deepEqual(menuPlan({ extra: "value", shown: { description: false, extra: true } }).map((e) => e.key), ["description", "delete"], "an output has no default to add");
});

test("when some row shows a description or a default, they are columns of the inline layout, to the right of the compact row", async () => {
  const { rowPlan } = await import("../../openartifact/static/js/components/schema-fields-model.js");
  const none = rowPlan({ showRequired: true, extra: "default" });
  assert.equal(none.isInline, false, "nothing shown: the list stays compact");
  const both = rowPlan({ showRequired: true, extra: "default", inline: { description: true, extra: true } });
  assert.deepEqual(both.inlineColumns, ["grip", "name", "type", "required", "extra", "description", "more"]);
  assert.equal(both.inlineRow, '"grip name type required extra description more"');
  assert.equal(both.inlineChoices, '". choices choices choices choices choices ."');
  assert.equal(both.isInline, true);
  const onlyDescription = rowPlan({ showRequired: false, extra: "value", inline: { description: true, extra: true } });
  assert.deepEqual(onlyDescription.inlineColumns, ["grip", "name", "type", "extra", "description", "more"], "an output's value is a column already; its description comes after it");
  const noDefaultColumnForOutputs = rowPlan({ showRequired: true, extra: null, inline: { extra: true } });
  assert.equal(noDefaultColumnForOutputs.isInline, false, "no default without a default setting");
});
