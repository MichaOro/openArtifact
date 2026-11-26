import assert from "node:assert/strict";
import { test } from "node:test";

const M = await import("../../openartifact/static/js/components/rule-model.js");

const SCHEMA = {
  actions: [{ key: "delete", label: "Delete the execution", phrase: "Delete finished executions where", effect: "deletes" }],
  fields: [
    { key: "status", label: "Status", kind: "choice", options: [{ value: "done", label: "Done" }, { value: "failed", label: "Failed" }], operators: [{ key: "is", label: "is" }, { key: "is_not", label: "is not" }] },
    { key: "pipeline", label: "Pipeline", kind: "text", operators: [{ key: "is", label: "is" }, { key: "contains", label: "contains" }] },
    { key: "age", label: "Age", kind: "duration", operators: [{ key: "older_than", label: "is older than" }] },
    { key: "position", label: "Position", kind: "count", default: 50, operators: [{ key: "beyond", label: "is beyond the newest" }] },
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

test("a count field starts at its default, is complete when positive and is told with the number", () => {
  assert.deepEqual(M.newCondition(SCHEMA, "position"), { type: "condition", field: "position", op: "beyond", value: 50 });
  const rule = { type: "group", mode: "all", items: [{ type: "condition", field: "position", op: "beyond", value: 20 }] };
  assert.equal(M.isComplete(rule), true);
  assert.equal(M.describe(rule, SCHEMA), "Position is beyond the newest 20");
  rule.items[0].value = 0;
  assert.equal(M.isComplete(rule), false);
});

test("a new rule has an empty condition tree and the first action; a rule is told with its action's phrase", () => {
  assert.deepEqual(M.emptyRule(SCHEMA), { when: M.emptyGroup(), action: "delete" });
  const rule = { when: { type: "group", mode: "all", items: [{ type: "condition", field: "status", op: "is", value: ["failed"] }] }, action: "delete" };
  assert.equal(M.describeRule(rule, SCHEMA), "Delete finished executions where Status is Failed.");
  assert.equal(M.describeRule(M.emptyRule(SCHEMA), SCHEMA), "", "no conditions, nothing to tell");
});

test("what saving does is named after the actions of the rules that match something", () => {
  const two = { ...SCHEMA, actions: [...SCHEMA.actions, { key: "archive", label: "Archive", phrase: "Archive", effect: "archives" }] };
  const rules = [{ action: "delete" }, { action: "archive" }];
  assert.equal(M.effectOf(two, rules, [2, 0]), "deletes");
  assert.equal(M.effectOf(two, rules, [2, 1]), "deletes or archives");
  assert.equal(M.effectOf(two, rules, [0, 0]), "");
});

// ── the guard schema (ADR-060): seconds, numbers and result fields ──────────

const GUARD = {
  actions: [{ key: "pause", label: "Pause", phrase: "Pause when", effect: "pauses" }],
  fields: [
    { key: "idle", label: "Time without progress", kind: "duration", minimum: 0, units: ["hours", "minutes", "seconds"], operators: [{ key: "at_least", label: "is at least" }] },
    { key: "var.", prefix: "var.", label: "Result field", kind: "number", operators: [{ key: "below", label: "is below" }] },
    { key: "runs", label: "Rounds", kind: "count", minimum: 0, operators: [{ key: "at_least", label: "is at least" }] },
  ],
};

test("a duration offers the units of its field, seconds included, and splits into the largest of them", () => {
  assert.deepEqual(M.durationUnits(GUARD.fields[0]), ["hours", "minutes", "seconds"]);
  assert.deepEqual(M.durationUnits(SCHEMA.fields[2]), ["days", "hours", "minutes"]); // retention keeps its units
  assert.deepEqual(M.splitDuration(90, ["hours", "minutes", "seconds"]), { amount: 90, unit: "seconds" });
  assert.deepEqual(M.splitDuration(180, ["hours", "minutes", "seconds"]), { amount: 3, unit: "minutes" });
  assert.deepEqual(M.splitDuration(90), { amount: 2, unit: "minutes" }); // without seconds as before
  assert.equal(M.joinDuration(45, "seconds"), 45);
});

test("a result field is the prefix and a name; it is complete only with a valid name", () => {
  const fresh = M.newCondition(GUARD, "var.");
  assert.deepEqual(fresh, { type: "condition", field: "var.", op: "below", value: 0 });
  assert.equal(M.fieldOf(GUARD, "var.gain").key, "var.");
  const named = M.withName(M.fieldOf(GUARD, "var."), fresh, "gain");
  assert.equal(named.field, "var.gain");
  assert.equal(M.isComplete({ type: "group", mode: "all", items: [fresh] }, GUARD), false);
  assert.equal(M.isComplete({ type: "group", mode: "all", items: [{ ...named, value: -0.5 }] }, GUARD), true);
  assert.equal(M.describe({ type: "group", mode: "all", items: [{ ...named, value: 0.05 }] }, GUARD), "Result field gain is below 0.05");
});

test("with the schema a count may be 0 where its field allows it; without, the old rule holds", () => {
  const zero = { type: "group", mode: "all", items: [{ type: "condition", field: "runs", op: "at_least", value: 0 }] };
  assert.equal(M.isComplete(zero, GUARD), true);
  assert.equal(M.isComplete(zero), false);
});
