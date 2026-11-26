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
