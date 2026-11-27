/* The maths of the page size of a management page (components/page-size.js): what fits, the base with its minimum, the steps, the clamp
 * to 500, the stored step and the first visible item that stays on the page. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { MAXIMUM, MINIMUM, baseOf, choices, firstOf, fit, pageOf, sizeOf, stepOf, usableStep } from "../../openartifact/static/js/components/page-size.js";

test("whole items fit: the gap lies between two items, not after the last, and a half item does not count", () => {
  assert.equal(fit(304, 304, 16), 1);
  assert.equal(fit(303, 304, 16), 0, "one pixel short of one card is none");
  assert.equal(fit(624, 304, 16), 2); // 304 + 16 + 304 = 624
  assert.equal(fit(623, 304, 16), 1);
  assert.equal(fit(1000, 304, 16), 3);
  assert.equal(fit(0, 304, 16), 0);
  assert.equal(fit(-5, 304, 16), 0);
  assert.equal(fit(500, 0, 16), 0, "no size, no count");
});

test("the base is columns times rows, at least 12", () => {
  assert.equal(baseOf(4, 6), 24);
  assert.equal(baseOf(3, 6), 18);
  assert.equal(baseOf(4, 3), 12);
  assert.equal(baseOf(2, 2), MINIMUM, "a small area still loads 12");
  assert.equal(baseOf(1, 5), MINIMUM, "a phone: one column");
});

test("an area that could not be measured gives the minimum", () => {
  assert.equal(baseOf(0, 0), MINIMUM);
  assert.equal(baseOf(4, 0), MINIMUM);
  assert.equal(baseOf(0, 6), MINIMUM);
  assert.equal(baseOf(Number.NaN, 6), MINIMUM);
});

test("the choices are the base and twice and four times the base", () => {
  assert.deepEqual(choices(18).map((c) => c.size), [18, 36, 72]);
  assert.deepEqual(choices(24).map((c) => c.size), [24, 48, 96]);
  assert.deepEqual(choices(12).map((c) => c.size), [12, 24, 48]);
  assert.deepEqual(choices(18).map((c) => c.step), [1, 2, 4]);
});

test("no choice is larger than what the server gives in one request, and a clamped choice appears once", () => {
  assert.equal(MAXIMUM, 500);
  assert.deepEqual(choices(200).map((c) => c.size), [200, 400, 500]);
  assert.deepEqual(choices(300).map((c) => c.size), [300, 500], "twice is 600, which is clamped to 500, four times is 500 again");
  assert.deepEqual(choices(500).map((c) => c.size), [500]);
  assert.equal(sizeOf(450, 4), 500);
  assert.equal(baseOf(30, 30), 500, "the base itself is clamped");
});

test("the size of a step is the base times the step; an unknown step is the first", () => {
  assert.equal(sizeOf(18, 1), 18);
  assert.equal(sizeOf(18, 2), 36);
  assert.equal(sizeOf(18, 4), 72);
  assert.equal(sizeOf(18, 3), 18);
  assert.equal(sizeOf(18, undefined), 18);
});

test("the browser remembers the step, and an unknown or old value falls back to the first step", () => {
  assert.equal(stepOf(1), 1);
  assert.equal(stepOf(2), 2);
  assert.equal(stepOf("4"), 4);
  assert.equal(stepOf(24), 1, "an old absolute size is not a step");
  assert.equal(stepOf(48), 1);
  assert.equal(stepOf(null), 1);
  assert.equal(stepOf(undefined), 1);
  assert.equal(stepOf("many"), 1);
  assert.equal(stepOf(3), 1);
});

test("a stored step that has no choice of its own any more (the base at the maximum) moves to the largest step there is", () => {
  assert.equal(usableStep(18, 4), 4);
  assert.equal(usableStep(300, 4), 2, "300 and 500 are the choices: four times is the same size as twice");
  assert.equal(usableStep(500, 2), 1);
  assert.equal(usableStep(18, 1), 1);
});

test("the first visible item stays on the page when the size changes", () => {
  // page 2 of 18 starts at item 36; with 24 per page item 36 is on page 1 (24..47), with 12 on page 3 (36..47)
  assert.equal(firstOf(2, 18), 36);
  assert.equal(pageOf(36, 24), 1);
  assert.equal(pageOf(36, 12), 3);
  assert.equal(pageOf(36, 36), 1);
  assert.equal(pageOf(0, 24), 0);
  assert.equal(pageOf(35, 36), 0);
  assert.equal(pageOf(10, 0), 0, "no size: the first page");
  assert.equal(firstOf(-1, 18), 0);
});
