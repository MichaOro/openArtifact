import assert from "node:assert/strict";
import { test } from "node:test";

const JS = "../../openartifact/static/js/editor/";
const { formOf, mockActive, mockOfResult, mockOfStep, mockable, parseData, payloadOf } = await import(`${JS}mock-model.js`);

test("only a node that leaves a result of its own takes a mock", () => {
  assert.equal(mockable({ produces_result: true }, { kind: "http" }), true);
  assert.equal(mockable({ produces_result: true }, { kind: "if" }), false, "it chooses a connector, it has no result to hand over");
  assert.equal(mockable({ produces_result: true }, { kind: "timer" }), false);
  assert.equal(mockable({ produces_result: false }, { kind: "trigger" }), false);
});

test("the pin shows only while the mock is switched on", () => {
  assert.equal(mockActive({ mock: { enabled: true } }), true);
  assert.equal(mockActive({ mock: { enabled: false } }), false);
  assert.equal(mockActive({ mock: null }), false);
});

test("a node without a mock starts as a passing, empty result that is switched off", () => {
  assert.deepEqual(formOf({ mock: null }), { enabled: false, outcome: "pass", output: "", data: "", reason: "" });
});

test("the data text is a JSON object: empty is {}, anything else is told in a plain key", () => {
  assert.deepEqual(parseData("  "), { value: {} });
  assert.deepEqual(parseData('{"id": 7}'), { value: { id: 7 } });
  assert.deepEqual(parseData("{id: 7"), { error: "invalid" });
  assert.deepEqual(parseData("[1, 2]"), { error: "not_object" });
  assert.deepEqual(parseData("7"), { error: "not_object" });
});

test("a form with bad data sends nothing; a good one becomes the body", () => {
  assert.deepEqual(payloadOf({ enabled: true, outcome: "pass", output: "", data: "nope", reason: "" }), { error: "invalid" });
  assert.deepEqual(payloadOf({ enabled: true, outcome: "fail", output: "o", data: '{"a": 1}', reason: "r" }), { mock: { enabled: true, outcome: "fail", output: "o", data: { a: 1 }, reason: "r" } });
});

test("the result of the last run and a kept step become a switched-on mock without the marks of a dry run", () => {
  assert.deepEqual(mockOfResult({ outcome: "pass", output: "x", data: { id: 1 }, reason: "" }), { enabled: true, outcome: "pass", output: "x", data: { id: 1 }, reason: "" });
  const step = { outcome: "fail", output: "boom", reason: "no", data: { code: 500, mock: true, dry_run: true } };
  assert.deepEqual(mockOfStep(step), { enabled: true, outcome: "fail", output: "boom", data: { code: 500 }, reason: "no" });
});
