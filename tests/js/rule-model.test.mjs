import assert from "node:assert/strict";
import { test } from "node:test";

const M = await import("../../openartifact/static/js/components/rule-model.js");

const SCHEMA = {
  fields: [
    { key: "status", label: "Status", kind: "choice", options: [{ value: "done", label: "Done" }, { value: "failed", label: "Failed" }], operators: [{ key: "is", label: "is" }, { key: "is_not", label: "is not" }] },
    { key: "pipeline", label: "Pipeline", kind: "text", operators: [{ key: "is", label: "is" }, { key: "contains", label: "contains" }] },
    { key: "age", label: "Age", kind: "duration", operators: [{ key: "older_than", label: "is older than" }] },
  ],
};

test("a new condition starts with the first field, its first operator and an empty value of its kind", () => {
  assert.deepEqual(M.newCondition(SCHEMA), { type: "condition", field: "status", op: "is", value: [] });
  assert.deepEqual(M.newCondition(SCHEMA, "pipeline"), { type: "condition", field: "pipeline", op: "is", value: "" });
  assert.deepEqual(M.newCondition(SCHEMA, "age"), { type: "condition", field: "age", op: "older_than", value: 86400 });
});

test("changing the field resets operator and value, changing only the operator keeps the value", () => {
  const c = { type: "condition", field: "status", op: "is", value: ["done"] };
  assert.deepEqual(M.withField(SCHEMA, c, "age"), { type: "condition", field: "age", op: "older_than", value: 86400 });
  assert.deepEqual(M.withOperator(c, "is_not"), { type: "condition", field: "status", op: "is_not", value: ["done"] });
});

test("groups are edited by path without touching the original", () => {
  const root = M.emptyGroup();
  const one = M.addItem(root, [], M.newCondition(SCHEMA));
  const two = M.addItem(one, [], M.emptyGroup("any"));
  const three = M.addItem(two, [1], M.newCondition(SCHEMA, "age"));
  assert.equal(root.items.length, 0);
  assert.equal(M.countConditions(three), 2);
  assert.equal(three.items[1].items[0].field, "age");
  const removed = M.removeItem(three, [1, 0]);
  assert.equal(M.countConditions(removed), 1);
  assert.equal(three.items[1].items.length, 1, "the original keeps its item");
  const flipped = M.setMode(three, [1], "all");
  assert.equal(flipped.items[1].mode, "all");
  assert.equal(three.items[1].mode, "any");
});

test("groups may nest only so deep", () => {
  let tree = M.emptyGroup();
  let path = [];
  for (let i = 0; i < 3; i++) {
    tree = M.addItem(tree, path, M.emptyGroup());
    path = [...path, 0];
  }
  assert.equal(M.depthOf(tree), 4);
  assert.equal(M.canNest(tree, path, 4), false, "a group at the deepest level cannot hold another");
  assert.equal(M.canNest(tree, [0], 4), true);
});

test("a rule is complete when every condition has what it needs", () => {
  assert.equal(M.isComplete(M.emptyGroup()), true); // nothing: nothing is deleted
  const open = { type: "group", mode: "all", items: [{ type: "condition", field: "status", op: "is", value: [] }] };
  assert.equal(M.isComplete(open), false);
  const pipeline = { type: "group", mode: "all", items: [{ type: "condition", field: "pipeline", op: "is", value: "  " }] };
  assert.equal(M.isComplete(pipeline), false);
  const ok = { type: "group", mode: "any", items: [{ type: "condition", field: "age", op: "older_than", value: 3600 }] };
  assert.equal(M.isComplete(ok), true);
});

test("durations are shown in the largest whole unit and read back as seconds", () => {
  assert.deepEqual(M.splitDuration(7 * 86400), { amount: 7, unit: "days" });
  assert.deepEqual(M.splitDuration(90 * 60), { amount: 90, unit: "minutes" });
  assert.deepEqual(M.splitDuration(7200), { amount: 2, unit: "hours" });
  assert.equal(M.joinDuration(3, "hours"), 10800);
  assert.equal(M.joinDuration(2, "days"), 172800);
});

test("a rule is told in words", () => {
  const tree = {
    type: "group", mode: "all",
    items: [
      { type: "condition", field: "status", op: "is", value: ["done", "failed"] },
      { type: "condition", field: "age", op: "older_than", value: 7 * 86400 },
      { type: "group", mode: "any", items: [{ type: "condition", field: "pipeline", op: "contains", value: "Build" }, { type: "condition", field: "status", op: "is_not", value: ["failed"] }] },
    ],
  };
  assert.equal(
    M.describe(tree, SCHEMA),
    'Status is Done or Failed, and Age is older than 7 days, and (Pipeline contains "Build" or Status is not Failed)',
  );
  assert.equal(M.describe(M.emptyGroup(), SCHEMA), "");
});
