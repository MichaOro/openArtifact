import assert from "node:assert/strict";
import test from "node:test";

import { canReset, defaultOf, isOn, onValueOf, shown, switched, textAfterBlur, toStored, zeroHintShown } from "../../openartifact/static/js/components/limit-model.js";

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

test("an emptied field is the default again when the user leaves it, and never 0", () => {
  assert.equal(textAfterBlur("", null, 50), "50", "an empty field shows the default");
  assert.equal(textAfterBlur("  ", null, 50), "50");
  assert.equal(textAfterBlur("", 7, 50), "7", "a stored number stays what it is");
  assert.equal(textAfterBlur("12", null, 50), "12", "a typed number is kept");
  assert.equal(textAfterBlur("0", null, 50), "0", "0 typed on purpose is kept");
  assert.notEqual(textAfterBlur("", null, 50), "0");
});

test("the hint that 0 keeps everything shows only for a field that says what its 0 means and while it holds 0", () => {
  assert.equal(zeroHintShown("0", true), true);
  assert.equal(zeroHintShown("0", false), false, "a field without that meaning shows no hint");
  assert.equal(zeroHintShown("3", true), false);
  assert.equal(zeroHintShown("", true), false, "an empty field is not 0");
  assert.equal(zeroHintShown(undefined, true), false);
});
