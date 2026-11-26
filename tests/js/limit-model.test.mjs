import assert from "node:assert/strict";
import test from "node:test";

import { canReset, defaultOf, isOn, onValueOf, shown, switched, toStored } from "../../openartifact/static/js/components/limit-model.js";

test("a field nobody set shows its default, and a set one shows its number", () => {
  assert.equal(shown(null, 50), 50);
  assert.equal(shown(undefined, 256), 256);
  assert.equal(shown(5, 50), 5);
  assert.equal(shown(0, 50), 0, "0 keeps everything: it is a number, not an empty field");
});

test("typing the default back stores nothing, so a later change of the default still applies", () => {
  assert.equal(toStored(50, 50), null);
  assert.equal(toStored(7, 50), 7);
  assert.equal(toStored(0, 50), 0);
  assert.equal(toStored(null, 50), null, "an emptied field is the default again");
  assert.equal(toStored(Number.NaN, 50), null);
});

test("Reset to default is offered only while another number is stored", () => {
  assert.equal(canReset(null, 50), false);
  assert.equal(canReset(50, 50), false, "a stored default is the default");
  assert.equal(canReset(5, 50), true);
  assert.equal(canReset(0, 50), true);
});

test("an optional limit is on while a number is stored, and the switch stores the suggested number or nothing", () => {
  assert.equal(isOn(null), false);
  assert.equal(isOn(undefined), false);
  assert.equal(isOn(30), true);
  assert.equal(switched(true, 30), 30);
  assert.equal(switched(false, 30), null, "off forgets the number");
});

test("the default and the suggestion come from the page first, then from the manifest", () => {
  const field = { key: "storage_keep_executions", config: { default_value: 50, on_value: 24 }, min: 1 };
  assert.equal(defaultOf(field, { defaults: { storage_keep_executions: 100 } }), 100, "the operator's number wins");
  assert.equal(defaultOf(field, {}), 50);
  assert.equal(defaultOf({ key: "x", config: {} }, {}), null);
  assert.equal(onValueOf(field, { on_values: { storage_keep_executions: 12 } }), 12);
  assert.equal(onValueOf(field, {}), 24);
  assert.equal(onValueOf({ key: "x", config: {}, min: 3 }, {}), 3);
});
