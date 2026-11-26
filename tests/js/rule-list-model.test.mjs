/* The data of the rule list (components/rule-list-model.js): the name and the switch of a rule, what a row says about
 * its rule, staged removal with undo, and what is saved. No DOM. */
import assert from "node:assert/strict";
import { test } from "node:test";

const L = await import("../../openartifact/static/js/components/rule-list-model.js");
const M = await import("../../openartifact/static/js/components/rule-model.js");

const SCHEMA = {
  actions: [{ key: "delete", label: "Delete the execution", phrase: "Delete finished executions where", effect: "deletes" }],
  fields: [
    { key: "status", label: "Status", kind: "choice", options: [{ value: "done", label: "Done" }, { value: "failed", label: "Failed" }], operators: [{ key: "is", label: "is" }] },
    { key: "age", label: "Age", kind: "duration", operators: [{ key: "older_than", label: "is older than" }] },
  ],
};
const failed = { type: "group", mode: "all", items: [{ type: "condition", field: "status", op: "is", value: ["failed"] }] };
const old = { type: "group", mode: "all", items: [{ type: "condition", field: "age", op: "older_than", value: 7 * 86400 }] };

test("a stored rule without name or switch reads as unnamed and on", () => {
  const [rule] = L.normalize([{ when: failed, action: "delete" }]);
  assert.deepEqual(rule, { when: failed, action: "delete", name: "", enabled: true });
  assert.deepEqual(L.normalize([{ when: failed, action: "delete", name: null, enabled: false }])[0].enabled, false, "a stored off stays off");
  assert.deepEqual(L.normalize(null), []);
});

test("a rule is called by its name, else Rule N counted from one", () => {
  assert.equal(L.labelOf({ name: "Old ones" }, 3), "Old ones");
  assert.equal(L.labelOf({ name: "  " }, 1), "Rule 2");
  assert.equal(L.labelOf({}, 0), "Rule 1");
});

test("the switch, the name and any other part of a rule change that rule only and never the list in place", () => {
  const rules = L.normalize([{ when: failed, action: "delete" }, { when: old, action: "delete" }]);
  const off = L.setEnabled(rules, 1, false);
  assert.deepEqual(off.map((r) => r.enabled), [true, false]);
  assert.deepEqual(rules.map((r) => r.enabled), [true, true], "the original is untouched");
  assert.equal(L.setName(rules, 0, "Failed ones")[0].name, "Failed ones");
  assert.deepEqual(L.patch(rules, 1, { when: failed })[1].when, failed);
});

test("a new rule is on and has no conditions; the list has a maximum", () => {
  const one = L.append([], M.emptyRule(SCHEMA), 2);
  assert.deepEqual(one[0], { when: M.emptyGroup(), action: "delete", name: "", enabled: true });
  assert.equal(L.append(L.append(one, M.emptyRule(SCHEMA), 2), M.emptyRule(SCHEMA), 2).length, 2, "the second fits");
  assert.equal(L.append(L.append(one, M.emptyRule(SCHEMA), 2), M.emptyRule(SCHEMA), 2).length, 2);
  const full = L.append(one, M.emptyRule(SCHEMA), 1);
  assert.equal(full.length, 1, "a full list takes no more");
});

test("a removed rule is only marked until saving, and undo brings it back as it was", () => {
  const rules = L.normalize([{ when: failed, action: "delete", name: "A" }, { when: old, action: "delete", name: "B" }]);
  const marked = L.removeStaged(rules, 0);
  assert.equal(marked.length, 2, "still listed, so Undo can reach it");
  assert.equal(marked[0].removed, true);
  assert.deepEqual(L.kept(marked).map((r) => r.name), ["B"], "saving leaves it out");
  const back = L.restore(marked, 0);
  assert.equal(back[0].removed, undefined);
  assert.deepEqual(back[0], rules[0]);
});

test("what is saved: name or null, the switch, no client-only keys", () => {
  const rules = L.normalize([{ when: failed, action: "delete", name: " Old " }, { when: old, action: "delete", enabled: false }]);
  assert.deepEqual(L.kept(rules), [
    { when: failed, action: "delete", name: "Old", enabled: true },
    { when: old, action: "delete", name: null, enabled: false },
  ]);
});

test("a row says what its rule does, or that it is empty or unfinished", () => {
  assert.deepEqual(L.summaryOf({ when: failed, action: "delete" }, SCHEMA), { state: "ok", text: "Delete finished executions where Status is Failed." });
  assert.equal(L.summaryOf(M.emptyRule(SCHEMA), SCHEMA).state, "empty");
  const unfinished = { when: { type: "group", mode: "all", items: [{ type: "condition", field: "status", op: "is", value: [] }] }, action: "delete" };
  assert.equal(L.summaryOf(unfinished, SCHEMA).state, "incomplete");
});

test("only rules that are on and not removed are told in the footer line, in the order of the list", () => {
  const rules = L.removeStaged(L.setEnabled(L.normalize([{ when: failed, action: "delete" }, { when: old, action: "delete", name: "Old ones" }, { when: failed, action: "delete" }]), 2, false), 0);
  assert.deepEqual(L.activeSentences(rules, SCHEMA), [{ label: "Old ones", text: "Delete finished executions where Age is older than 7 days." }]);
  assert.equal(L.countOn(rules), 1);
  assert.equal(L.countOn(L.normalize([{ when: failed, action: "delete", enabled: false }])), 0);
});

test("words in a rule's description come from the dictionary: and/or, plural units", () => {
  const both = { type: "group", mode: "any", items: [failed.items[0], old.items[0]] };
  assert.equal(M.describe(both, SCHEMA), "Status is Failed, or Age is older than 7 days");
  const one = { type: "group", mode: "all", items: [{ type: "condition", field: "age", op: "older_than", value: 86400 }] };
  assert.equal(M.describe(one, SCHEMA), "Age is older than 1 day");
});
