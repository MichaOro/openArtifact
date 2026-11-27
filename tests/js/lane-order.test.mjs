import assert from "node:assert/strict";
import test from "node:test";

import { clamp, moveLane, orderChanged } from "../../openartifact/static/js/tasks/lane-order-model.js";

const lanes = ["a", "b", "c", "d"];

test("a lane moves to a place and the others close up", () => {
  assert.deepEqual(moveLane(lanes, 0, 2), ["b", "c", "a", "d"]);
  assert.deepEqual(moveLane(lanes, 3, 0), ["d", "a", "b", "c"]);
  assert.deepEqual(moveLane(lanes, 1, 2), ["a", "c", "b", "d"]);
});

test("a move past either end stops at the end, and a move to the same place changes nothing", () => {
  assert.deepEqual(moveLane(lanes, 3, 9), lanes);
  assert.deepEqual(moveLane(lanes, 0, -5), lanes);
  assert.deepEqual(moveLane(lanes, 2, 2), lanes);
  assert.deepEqual(moveLane(lanes, 1, 99), ["a", "c", "d", "b"]);
});

test("a place that is not in the list moves nothing, and the list is never changed in place", () => {
  assert.deepEqual(moveLane(lanes, 7, 0), lanes);
  assert.deepEqual(moveLane(lanes, -1, 0), lanes);
  const copy = [...lanes];
  moveLane(copy, 0, 3);
  assert.deepEqual(copy, lanes);
});

test("clamp keeps a number between its bounds", () => {
  assert.equal(clamp(5, 0, 3), 3);
  assert.equal(clamp(-2, 0, 3), 0);
  assert.equal(clamp(2, 0, 3), 2);
});

test("an order changed only when a lane stands somewhere else", () => {
  assert.equal(orderChanged(lanes, [...lanes]), false);
  assert.equal(orderChanged(lanes, ["b", "a", "c", "d"]), true);
  assert.equal(orderChanged(lanes, ["a", "b"]), true);
});
