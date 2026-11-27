import assert from "node:assert/strict";
import { test } from "node:test";
import { describeSize, splitSize, toBytes } from "../../openartifact/static/js/components/size-model.js";

test("a value is shown in the largest unit that divides it evenly", () => {
  assert.deepEqual(splitSize(65536), { value: 64, unit: "KiB" });
  assert.deepEqual(splitSize(1048576), { value: 1, unit: "MiB" });
  assert.deepEqual(splitSize(1500), { value: 1500, unit: "B" }); // nobody converts 1500 bytes by hand
  assert.deepEqual(splitSize(1536), { value: 1536, unit: "B" }); // 1.5 KiB is no whole KiB
  assert.deepEqual(splitSize(3 * 1048576), { value: 3, unit: "MiB" });
});

test("nothing, zero and what is no size are 0 B", () => {
  for (const bad of [0, -5, null, undefined, "abc", NaN, Infinity]) assert.deepEqual(splitSize(bad), { value: 0, unit: "B" }, String(bad));
});

test("a number in a unit becomes bytes, whole", () => {
  assert.equal(toBytes("64", "KiB"), 65536);
  assert.equal(toBytes(2, "MiB"), 2097152);
  assert.equal(toBytes("1.5", "KiB"), 1536);
  assert.equal(toBytes("300", "B"), 300);
  assert.equal(toBytes("0.4", "B"), 0); // rounded to whole bytes
});

test("an empty field, a word or an unknown unit is no number of bytes", () => {
  assert.ok(Number.isNaN(toBytes("", "KiB")));
  assert.ok(Number.isNaN(toBytes("x", "B")));
  assert.ok(Number.isNaN(toBytes("5", "GiB")));
});

test("a size in words for a message", () => {
  assert.equal(describeSize(65536), "64 KiB");
  assert.equal(describeSize(67108864), "64 MiB");
  assert.equal(describeSize(1500), "1500 B");
});
