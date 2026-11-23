import assert from "node:assert/strict";
import { test } from "node:test";

const { bubbleSpec, FAILING_PORTS } = await import("../../openartifact/static/js/execution/flow-bubbles.js");

test("a longer edge takes longer and carries more bubbles, at one speed", () => {
  const short = bubbleSpec(120);
  const long = bubbleSpec(900);
  assert.ok(long.duration > short.duration);
  assert.ok(long.count > short.count);
  assert.ok(short.count >= 1 && long.count <= 6, "never none on a short edge, never a crowd on a long one");
  assert.ok(Math.abs(long.length / long.duration - short.length / short.duration) < 1, "the same speed on every edge");
});

test("the bubbles of one edge are spread evenly over one trip", () => {
  const spec = bubbleSpec(600);
  assert.equal(spec.delays.length, spec.count);
  const gaps = spec.delays.slice(1).map((d, i) => d - spec.delays[i]);
  for (const gap of gaps) assert.ok(Math.abs(gap - spec.duration / spec.count) < 1e-9);
});

test("the phase follows the clock, so an edge drawn again does not restart its bubbles", () => {
  const a = bubbleSpec(600, 1000).begins;
  const b = bubbleSpec(600, 1000 + 250).begins;
  assert.notDeepEqual(a, b);
  const spec = bubbleSpec(600, 7300);
  for (const begin of spec.begins) assert.ok(begin <= 0 && begin > -spec.duration - 1e-9, "begins in the past, within one trip");
});

test("only the failing ports make red bubbles", () => {
  assert.deepEqual(FAILING_PORTS, ["error", "fail", "else"]);
});
