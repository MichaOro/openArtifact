import assert from "node:assert/strict";
import { test } from "node:test";

import { LAST_LANE, NOT_EMPTY, deleteBlockedReason } from "../../openartifact/static/js/tasks/lane-rules.js";

test("a lane with artifacts cannot be deleted, and says why", () => {
  assert.equal(deleteBlockedReason(1, 3), NOT_EMPTY);
  assert.equal(NOT_EMPTY, "A lane can only be deleted when it contains no artifacts.");
});

test("the last lane cannot be deleted, even when it is empty", () => {
  assert.equal(deleteBlockedReason(0, 1), LAST_LANE);
});

test("an empty lane among others can be deleted", () => {
  assert.equal(deleteBlockedReason(0, 2), null);
});

test("artifacts are the first reason when the lane is also the last", () => {
  assert.equal(deleteBlockedReason(2, 1), NOT_EMPTY);
});
