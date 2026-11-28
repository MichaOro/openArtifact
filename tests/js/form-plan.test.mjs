/* The pure part of the form renderer (components/form-plan.js): paths into nested values, which fields are there, how
 * sections are laid out in columns and blocks, what is folded away as advanced, and what breaks a limit. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { dependencies, drawn, getPath, isEnabled, isVisible, planForm, problems, setPath } from "../../openartifact/static/js/components/form-plan.js";

const field = (key, extra = {}) => ({ key, widget: "text", label: key, ...extra });
const FORM = {
  name: "demo",
  columns: 2,
  sections: [
    { key: "trigger", title: "Trigger", column: 1, fields: [field("trigger.type"), field("trigger.every", { visible_when: { field: "trigger.type", equals: "interval" } }), field("trigger.held", { advanced: true, visible_when: { field: "trigger.type", equals: "interval" } })] },
    { key: "then", title: "Then", column: 2, fields: [field("consequence")] },
    { key: "condition", title: "Condition", column: "full", fields: [field("when")] },
    { key: "a", title: "A", column: "auto", weight: 1, fields: [field("a")] },
    { key: "b", title: "B", column: "auto", weight: 1, fields: [field("b")] },
    { key: "c", title: "C", column: "auto", weight: 3, fields: [field("c")] },
  ],
};

test("a dotted path reads and writes nested values, making the objects on the way", () => {
  const values = {};
  setPath(values, "trigger.every_seconds", 60);
  assert.deepEqual(values, { trigger: { every_seconds: 60 } });
  assert.equal(getPath(values, "trigger.every_seconds"), 60);
  assert.equal(getPath(values, "trigger.missing.deep"), undefined);
  assert.equal(getPath({}, "a.b"), undefined);
});

test("a field with visible_when is there only while the other field has the value (equals) or one of them (in)", () => {
  const f = field("x", { visible_when: { field: "kind", equals: "a" } });
  assert.equal(isVisible(f, { kind: "a" }), true);
  assert.equal(isVisible(f, { kind: "b" }), false);
  assert.equal(isVisible(f, {}), false);
  const g = field("y", { visible_when: { field: "kind", in: ["a", "b"] } });
  assert.equal(isVisible(g, { kind: "b" }), true);
  assert.equal(isVisible(g, { kind: "c" }), false);
  assert.equal(isVisible(field("z"), {}), true);
});

test("sections go into blocks in manifest order: a full section stands alone, the rest share two columns", () => {
  const { blocks } = planForm(FORM, { trigger: { type: "interval" } });
  assert.deepEqual(blocks.map((b) => (b.full ? `full:${b.full.key}` : b.columns.map((c) => c.map((s) => s.key).join("+")).join("|"))), ["trigger|then", "full:condition", "a+c|b"]);
});

test("auto sections fill the column with less weight; one column keeps manifest order", () => {
  const two = planForm(FORM, {}).blocks.at(-1).columns;
  assert.deepEqual(two.map((c) => c.map((s) => s.key)), [["a", "c"], ["b"]]);
  const one = planForm(FORM, {}, { columns: 1 }).blocks;
  assert.equal(one[0].columns.length, 1);
  assert.deepEqual(one[0].columns[0].map((s) => s.key), ["trigger", "then"]);
});

test("a section whose fields are all hidden is dropped, and the advanced fields are folded until the section is expanded", () => {
  const event = planForm(FORM, { trigger: { type: "event" } }).blocks[0].columns[0][0];
  assert.deepEqual(event.shown.map((f) => f.key), ["trigger.type"]);
  assert.equal(event.advanced.length, 0);
  const interval = planForm(FORM, { trigger: { type: "interval" } }).blocks[0].columns[0][0];
  assert.deepEqual(interval.shown.map((f) => f.key), ["trigger.type", "trigger.every"]);
  assert.equal(interval.folded, true);
  assert.deepEqual(drawn(interval).map((f) => f.key), ["trigger.type", "trigger.every"]);
  const open = planForm(FORM, { trigger: { type: "interval" } }, { expanded: new Set(["trigger"]) }).blocks[0].columns[0][0];
  assert.equal(open.folded, false);
  assert.deepEqual(drawn(open).map((f) => f.key), ["trigger.type", "trigger.every", "trigger.held"]);
  const hidden = { name: "x", columns: 2, sections: [{ key: "s", title: "S", fields: [field("k", { visible_when: { field: "m", equals: 1 } })] }] };
  assert.deepEqual(planForm(hidden, {}).blocks, []);
});

test("required, min and max are checked for the fields that are there and not for hidden ones", () => {
  const form = {
    name: "p",
    sections: [{ key: "s", title: "S", fields: [field("events", { required: true }), field("n", { min: 1, max: 10 }), field("only", { required: true, visible_when: { field: "kind", equals: "x" } })] }],
  };
  assert.deepEqual(problems(form, { events: [], n: 5, kind: "y" }), { events: { code: "required" } });
  assert.deepEqual(problems(form, { events: ["a"], n: 0, kind: "y" }), { n: { code: "min", limit: 1 } });
  assert.deepEqual(problems(form, { events: ["a"], n: 11, kind: "y" }), { n: { code: "max", limit: 10 } });
  assert.deepEqual(problems(form, { events: ["a"], n: 3, kind: "x" }), { only: { code: "required" } });
  assert.deepEqual(problems(form, { events: ["a"], n: 3, kind: "y" }), {});
});

test("what a visible_when looks at and what a field names in depends_on draws the form again", () => {
  const form = { name: "d", sections: [{ key: "s", title: "S", fields: [field("a", { visible_when: { field: "kind", equals: 1 } }), field("b", { config: { depends_on: ["other", "b"] } })] }] };
  assert.deepEqual([...dependencies(form)].sort(), ["b", "kind", "other"]);
});

test("a field with an enabled_when is drawn always but can be changed only while the other field has the value; a change of that field draws the form again", () => {
  const view = field("view", { widget: "select" });
  const groups = field("groups", { widget: "select", enabled_when: { field: "view", equals: "grouped" }, disabled_help: "Only the grouped view" });
  assert.equal(isEnabled(view, { view: "classic" }), true); // no enabled_when
  assert.equal(isEnabled(groups, { view: "classic" }), false);
  assert.equal(isEnabled(groups, { view: "grouped" }), true);
  assert.equal(isEnabled(field("x", { enabled_when: { field: "view", in: ["a", "b"] } }), { view: "b" }), true);
  assert.equal(isVisible(groups, { view: "classic" }), true); // greyed, not hidden
  const form = { name: "p", sections: [{ key: "s", title: "S", column: 1, fields: [view, groups] }] };
  assert.deepEqual([...dependencies(form)], ["view"]);
});
