import assert from "node:assert/strict";
import { test } from "node:test";
import { describeDuration, splitDuration, toMilliseconds } from "../../openartifact/static/js/components/duration-model.js";

test("a value is shown in the largest unit that divides it evenly", () => {
  assert.deepEqual(splitDuration(3467), { value: 3467, unit: "ms" }); // nobody converts 3467 ms by hand
  assert.deepEqual(splitDuration(1000), { value: 1, unit: "sec" });
  assert.deepEqual(splitDuration(90000), { value: 90, unit: "sec" }); // 1.5 min is no whole minute
  assert.deepEqual(splitDuration(120000), { value: 2, unit: "min" });
  assert.deepEqual(splitDuration(600000), { value: 10, unit: "min" });
  assert.deepEqual(splitDuration(1500), { value: 1500, unit: "ms" });
});

test("nothing, zero and what is no duration are 0 ms", () => {
  for (const bad of [0, -5, null, undefined, "abc", NaN, Infinity]) assert.deepEqual(splitDuration(bad), { value: 0, unit: "ms" }, String(bad));
});

test("a number in a unit becomes milliseconds, whole", () => {
  assert.equal(toMilliseconds("5", "sec"), 5000);
  assert.equal(toMilliseconds(2, "min"), 120000);
  assert.equal(toMilliseconds("250", "ms"), 250);
  assert.equal(toMilliseconds("1.5", "sec"), 1500);
  assert.equal(toMilliseconds("0.0004", "sec"), 0); // rounded to whole milliseconds
});

test("an empty field, a word or an unknown unit is no number of milliseconds", () => {
  assert.ok(Number.isNaN(toMilliseconds("", "sec")));
  assert.ok(Number.isNaN(toMilliseconds("  ", "sec")));
  assert.ok(Number.isNaN(toMilliseconds("x", "ms")));
  assert.ok(Number.isNaN(toMilliseconds("5", "hours")));
});

test("what the form shows and what it keeps agree both ways", () => {
  for (const ms of [0, 1, 250, 999, 1000, 3467, 59999, 60000, 90000, 120000, 600000]) {
    const { value, unit } = splitDuration(ms);
    assert.equal(toMilliseconds(value, unit), ms, `${ms} ms`);
  }
});

test("a duration is described for a message", () => {
  assert.equal(describeDuration(90000), "90 sec");
  assert.equal(describeDuration(120000), "2 min");
  assert.equal(describeDuration(3467), "3467 ms");
});
